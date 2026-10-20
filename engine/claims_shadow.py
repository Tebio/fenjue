#!/usr/bin/env python3
"""engine/claims_shadow.py — 存活主张的影子前向记录（L5 毕业条件的数据源）

每日收盘后（kcache 刷新后）跑：
1. 扫描期望登记日信号：REVERSAL（跌≥3%）/ LIMITDOWN（跌≤-9.5%，剔一字）/ PANIC_DEPTH 四档
2. 登记 shadow 单：{signal_date, claim, code, tier}
3. 回填历史单：次日开盘价（entry）、T+1/T+5/T+20 收盘收益
4. 汇总各主张的滚动影子表现 → data/claims_shadow_summary.json 供 claims_audit 读 L5

设计约束：只用 big_kcache（前复权日K），无新增数据依赖；净口径 -0.15%。
退出码契约（DATA-10）：0=正常/[SKIP] 非交易日（官方日历）；2=交易日但 kcache
未就绪 [NOT-READY]；1=DATA-07 熔断拒写。详见 CUTOFF_HHMM 上方 DATA-10 注释块。
"""
import json
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
KC = ROOT / "data/big_kcache"
SHADOW = ROOT / "data/claims_shadow.jsonl"
SUMMARY = ROOT / "data/claims_shadow_summary.json"
FEE = 0.0015
# 2026-09-27 实证修复：cron wrapper 用 runpy.run_path 调用本文件时，脚本目录不进 sys.path
# （实测 sys.path[0]=cwd），导致 _lp_universe() 里 import law_pipeline 静默失败、
# 注册表桥整整一周没记过一条单。显式把 engine 塞进 sys.path。
import sys as _sys
if str(ROOT / "engine") not in _sys.path:
    _sys.path.insert(0, str(ROOT / "engine"))
# FRONTRUN_V2（2026-09-12 注册）：首板+板块梯队≥3+市值20-400亿。
# 入场口径=信号日收盘（打板成交假设，fill 率由影子前向中的封板时间另行定量），
# 与框架默认的次日开盘不同——次日追是该主张内部已证伪的变体（-0.52%）。
CLOSE_ENTRY_CLAIMS = {"FRONTRUN_FIRSTBOARD_V2", "WATCHPOOL_GRAD", "YAO_LAUNCH_FIRSTBOARD"}  # 2026-09-26 加 YAO_LAUNCH（打板口径）

# 2026-09-19：注册表桥——夜间流水线新 PASS 组合进影子前向（L5）。
# 通过 law_pipeline REGISTRY 检测器原样执行，禁止在 detect() 里重复实现（口径漂移风险）。
# claim_id 必须与 data/claims_registry.yaml 的 id 一致。
REGISTRY_SHADOW_CLAIMS = {
    "COMP_LIMITDOWN_LOW_SHRINK_XFUND": "组合_跌停低_缩量_剔亏ST",
    "COMP_LIMITDOWN_LOW_LOSER250_OS20_SHRINK": "组合_跌停低_输家_超跌20_缩量",
    "COMP_LIMITDOWN_LOW_3DOWN_SHRINK": "组合_跌停低_三连阴_缩量",
    "COMP_LIMITDOWN_LOW_BIGUPPER_SHRINK": "组合_跌停低_避雷针_缩量",
    "COMP_LIMITDOWN_LOW_LOSER250_OS20_XFUND": "组合_跌停低_输家_超跌20_剔亏ST",
    "COMP_LIMITDOWN_LOW_TD9": "组合_跌停低_TD9买入滤",
    # 影子新线（2026-09-26 接线，#174/#177）：妖股启动期首板 + 主线深回踩
    "MAINLINE_DIP_RSI2": "主线深回踩_RSI2_v1",
    "YAO_LAUNCH_FIRSTBOARD": "妖股启动期首板_v1",
    "THREE_DOWN_GOLD": "三连阴_金股覆盖_v1",  # 2026-09-27（#208）金股确认层影子
    "PEAD_LOW_POOL": "预增低位池_v1",  # 2026-10-03 submit 7/7 PASS，名单制季节型（预告季外池空正常）
    "COMP_LIMITDOWN_LOW_LOSER250_OS20_TD9": "组合_跌停低_输家_超跌20_TD9滤",
    # 全交叉矩阵幸存对（2026-09-19 cross_matrix 8 PASS）
    "CROSS_LOW_SHRINK_BIGUPPER": "交叉_跌停低_缩量_避雷针低",
    "CROSS_LOW_SHRINK_XFUND": "交叉_跌停低_缩量_剔亏ST",
    "CROSS_LOW_SHRINK_GAPDOWN": "交叉_跌停低_缩量_缺口低开",
    "CROSS_LOW_3DOWN_LOSER250": "交叉_跌停低_三连阴_输家250",
    "CROSS_LOW_3DOWN_OS20": "交叉_跌停低_三连阴_超跌20",
    "CROSS_LOW_LOSER250_BIGUPPER": "交叉_跌停低_输家250_避雷针低",
    "CROSS_LOW_TD9_GAPDOWN": "交叉_跌停低_TD9买入_缺口低开",
    # 胜负解剖细分（2026-09-19，深度+恐慌强度分界）
    "COMP_LIMITDOWN_LOW_DEEP": "组合_跌停低_深跌",
    "COMP_LIMITDOWN_LOW_DEEP_LDC100": "组合_跌停低_深跌_跌停潮",
    "COMP_LIMITDOWN_LOW_3DOWN_DEEP": "组合_跌停低_三连阴_深跌",
    # 第二底座交叉幸存对（2026-09-19 gaplow 底座 8 PASS 中的 7 个新检测器）
    "CROSS_GAPLOW_3DOWN_BIGUPPER": "交叉_缺口低开低_三连阴_避雷针低",
    "CROSS_GAPLOW_3DOWN_TD9": "交叉_缺口低开低_三连阴_TD9买入",
    "CROSS_GAPLOW_3DOWN_XFUND": "交叉_缺口低开低_三连阴_剔亏ST",
    "CROSS_GAPLOW_LOSER250_XFUND": "交叉_缺口低开低_输家250_剔亏ST",
    "CROSS_GAPLOW_BIGUPPER_TD9": "交叉_缺口低开低_避雷针低_TD9买入",
    "CROSS_GAPLOW_BIGUPPER_XFUND": "交叉_缺口低开低_避雷针低_剔亏ST",
    "CROSS_GAPLOW_TD9_XFUND": "交叉_缺口低开低_TD9买入_剔亏ST",
}

# ── DATA-10（2026-10-20）：假绿灯修复 + 漏跑自愈 ─────────────────────────────
# 旧版把三类情况共用「[SILENT] → return → exit 0」：真非交易日 / 交易日但数据
# 未就绪 / 正常。「数据没准备好」被伪装成「成功」（2026-10-19 零产出而 cron 报 ok
# 事故：kcache 班 numpy ABI 故障整日无 bar，[SILENT] 兜底成绿灯）。
# 退出码契约（本文件唯一口径，wrapper 透传）：
#   0 = 正常处理，或 [SKIP] 非交易日（官方交易日历判定，严禁靠「有没有数据」反推）
#   2 = 期望登记日是交易日但 kcache 未就绪（上游刷新未完成/失败，非本脚本可自愈）
#   1 = DATA-07 熔断拒写（既有）
# 期望登记日（无 SHADOW_DATE 时）：BJT 今天是交易日且已过 15:30 → 今天；
# 否则 → 今天之前最近一个交易日（容器是 UTC，严禁 date.today()）。
# 漏跑自愈：除期望日外回看 WALKBACK_DAYS 个交易日，已就绪且零登记的日子一并
# 补登记；幂等由既有去重键 (signal_date, claim, code) 保证。
# 交易日历：freshness_core 本地缓存 data/trade_calendar/<year>.json（baostock
# 官方日历落盘副本，含未来日期），只读不联网；缓存缺失 → CalendarUnavailable
# 上浮（基建错误，不许猜节假日）。
CUTOFF_HHMM = (15, 30)   # BJT 收盘 15:00 + 30min 余量，此后「今天」才算到期
WALKBACK_DAYS = 5        # 自愈回看窗口（交易日）：覆盖一周漏跑；更长缺口用 SHADOW_DATE 显式回填


def _fc():
    import freshness_core as fc
    return fc


def _bjt_now():
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=8)))


def _expected_day(now):
    """期望登记日：今天(BJT)是交易日且已过 cutoff → 今天；否则前一交易日。"""
    fc = _fc()
    d = now.date().isoformat()
    if fc.is_trading_day(d) and (now.hour, now.minute) >= CUTOFF_HHMM:
        return d
    return fc.prev_trading_day(d)


def _candidate_days(expected, n=WALKBACK_DAYS):
    """期望日 + 回看 n 个交易日（新→旧）。"""
    fc = _fc()
    days, d = [expected], expected
    for _ in range(n):
        d = fc.prev_trading_day(d)
        days.append(d)
    return days


def _cs_coverage(stocks, day, lookback):
    """cs 宇宙里有当日 bar 的票数。lookback=None 全序列扫（显式回填较老日期）。"""
    n = 0
    for ks in stocks.values():
        lo = -1 if lookback is None else max(-1, len(ks) - 1 - lookback)
        for j in range(len(ks) - 1, lo, -1):
            if ks[j]["date"] == day:
                n += 1
                break
    return n


def _load_existing():
    """→ (existing, dates_any, dates_bridge)：一次性读账本。
    existing=(signal_date,claim,code) 去重键（既有语义）；dates_any=有任何登记的
    日期集合（主流程自愈判据）；dates_bridge=有桥登记的日期集合（桥自愈判据）。
    注意：「当日零信号」的合法空日会被判为未登记而重扫——重扫幂等无副作用，
    代价是窗口内多扫几天，可接受。"""
    existing, dates_any, dates_bridge = set(), set(), set()
    if SHADOW.exists():
        for line in SHADOW.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            existing.add((r["signal_date"], r["claim"], r["code"]))
            dates_any.add(r["signal_date"])
            if r["claim"] in REGISTRY_SHADOW_CLAIMS:
                dates_bridge.add(r["signal_date"])
    return existing, dates_any, dates_bridge


_LP_CACHE = None


def _lp_universe():
    """law_pipeline 宇宙懒加载（每跑一次日线影子只建一次，约 1-2 分钟）。"""
    global _LP_CACHE
    if _LP_CACHE is None:
        import law_pipeline as lp
        stocks = lp.load_universe()
        lp.build_xsection(stocks)
        idx = {c: {x: j for j, x in enumerate(s["date"])} for c, s in stocks.items()}
        _LP_CACHE = (lp, stocks, idx)
    return _LP_CACHE
_industry = None
_stock_cap = None
_regime_tl = None


def _regime_of(d):
    """当日周期标签（regime_timeline_hcap），懒加载。"""
    global _regime_tl
    if _regime_tl is None:
        try:
            _regime_tl = {r["date"]: r["regime"] for r in json.load(open(ROOT / "data/regime_timeline_hcap.json"))}
        except Exception:
            _regime_tl = {}
    return _regime_tl.get(d, "?")


def industry_map():
    global _industry
    if _industry is None:
        _industry = json.loads((ROOT / "data/industry_map.json").read_text())
    return _industry


def stock_caps():
    global _stock_cap
    if _stock_cap is None:
        import glob
        import bisect as _bis
        cap = {}
        for fp in glob.glob(str(ROOT / "data/cap_hist/*.json")):
            rows = sorted(json.loads(open(fp).read()), key=lambda r: r[0])
            # 2026-09-19 PIT 修复：存 (dates, caps) 日频，弃「月度=月末值」旧口径
            cap[Path(fp).stem] = ([r[0] for r in rows], [r[2] for r in rows])
        _stock_cap = cap
    return _stock_cap


def load_stocks():
    out = {}
    for fp in sorted(KC.glob("*.json")):
        ks = json.loads(fp.read_text())
        if len(ks) >= 65:
            out[fp.stem] = ks
    return out


def detect(code, ks, i, ladder=None):
    """返回第 i 根（信号日）触发的 (claim, tier) 列表。
    自查修正（2026-09-12）：①不再假设信号日=最后一根（SHADOW_DATE 回填历史时错位）；
    ②LIMITDOWN 不在信号日剔一字——可成交性只能在入场日（i+1）判，注册时全量登记。
    ③FRONTRUN_FIRSTBOARD_V2：首板（≥9.8% 且前60日无板）+可买（开盘<+9.5%）
      +梯队（ladder 同行业当日≥3）+市值带20-400亿（cap_hist 月度，缺数据=不触发）。"""
    if i < 65:
        return []
    c, pc = ks[i]["close"], ks[i - 1]["close"]
    if pc <= 0:
        return []
    chg = c / pc - 1
    hits = []
    if chg <= -0.03:
        hits.append(("REVERSAL_OPEN_T1", None))
        tier = ("-3~-5%" if chg > -0.05 else "-5~-7%" if chg > -0.07
                else "-7~-9.5%" if chg > -0.095 else "≤-9.5%")
        hits.append(("PANIC_DEPTH_DOSE", tier))
    if chg <= -0.095:
        hits.append(("LIMITDOWN_NEXT_DAY", None))
    if ladder is not None and chg >= 0.098:
        o = ks[i]["open"]
        if o > 0 and (o / pc - 1) < 0.095:  # 一字板买不进
            first = all(
                ks[j]["close"] <= 0 or ks[j - 1]["close"] <= 0
                or (ks[j]["close"] / ks[j - 1]["close"] - 1) < 0.098
                for j in range(max(1, i - 60), i))
            if first:
                industry = industry_map().get(code, {}).get("industry") or "?"
                if ladder.get(industry, 0) >= 3:
                    cap = None
                    packed = stock_caps().get(code)
                    if packed:  # 2026-09-19 PIT：不晚于当日的最近市值
                        import bisect as _b
                        dts, cps = packed
                        _j = _b.bisect_right(dts, ks[i]["date"]) - 1
                        cap = cps[_j] if _j >= 0 else None
                    if cap is not None and 20 <= cap <= 400:
                        # tier=当日regime（2026-09-12：反人群打板假设的前向测量——恐慌/平淡期fill是漏，主线/妖股期是坑）
                        reg = _regime_of(ks[i]["date"])
                        hits.append(("FRONTRUN_FIRSTBOARD_V2", reg))
    # WATCHPOOL_GRAD（G8，2026-09-12）：观察池毕业=今日首板 + 前15日内曾触发 B 变体池信号
    # （量比≥3、涨幅1~7.5%、未板、复牌守卫、额≥2亿）。入场=信号日收盘（打板口径同 FRONTRUN）。
    if chg >= 0.098 and i >= 6:
        import datetime as _dt
        for j in range(max(6, i - 15), i):
            if ks[j - 1]["close"] <= 0:
                continue
            try:
                d0 = _dt.date.fromisoformat(ks[j - 5]["date"]); d1 = _dt.date.fromisoformat(ks[j]["date"])
            except Exception:
                continue
            if (d1 - d0).days > 12 or any(ks[k]["volume"] <= 0 for k in range(j - 5, j)):
                continue
            pj = (ks[j]["close"] / ks[j - 1]["close"] - 1) * 100
            if not (1.0 <= pj <= 7.5):
                continue
            base = [ks[k]["volume"] for k in range(j - 5, j)]
            mb = sum(base) / len(base)
            if mb <= 0 or ks[j]["volume"] / mb < 3.0:
                continue
            if ks[j]["volume"] * ks[j]["close"] < 2e8:
                continue
            hits.append(("WATCHPOOL_GRAD", None))
            break
    # 注册表桥（2026-09-19）：新 PASS 组合委托 law_pipeline REGISTRY 检测器判定
    # 2026-09-27：默认不在主进程内联跑（双宇宙 OOM 教训），生产由 BRIDGE_ONLY 独立进程跑；
    # 仅当显式 BRIDGE_INLINE=1（研究/调试场景）才在 detect() 内联执行。
    import os as _os
    if REGISTRY_SHADOW_CLAIMS and _os.environ.get("BRIDGE_INLINE") == "1":
        try:
            lp, lp_stocks, lp_idx = _lp_universe()
            d = lp_stocks.get(code)
            j = lp_idx.get(code, {}).get(ks[i]["date"]) if d is not None else None
            if j is not None:
                for claim, detname in REGISTRY_SHADOW_CLAIMS.items():
                    try:
                        if lp.REGISTRY[detname](d, j):
                            hits.append((claim, None))
                    except KeyError:
                        print(f"[WARN] 注册表桥检测器不存在: {detname}")   # 红队M18：不再静默
                    except Exception as _e:
                        print(f"[WARN] 注册表桥 {claim} 异常: {_e}")
        except Exception as _e:
            print(f"[WARN] 注册表桥整体异常（桥可能整体失效）: {type(_e).__name__} {_e}")  # 2026-09-27：静默 pass 曾致桥死一周无人知
    return hits


def bridge_only(sd):
    """BRIDGE_ONLY 模式（2026-09-27，OOM 修复）：只跑注册表桥扫描，不载 cs 宇宙。

    根因：主流程 load_stocks()（全量 dict 列表）+ _lp_universe()（lp 数组宇宙+横截面）
    双宇宙同驻 → 15GB 机器 OOM（exit=137），桥自 9/19 起在 cron 里从没活过。
    拆成两个进程顺序跑（wrapper 第二步 BRIDGE_ONLY=1），峰值内存减半。
    登记的去重键与主流程一致（signal_date/claim/code），entry 由次日回填照常补。

    DATA-10：与主流程同一退出码契约（[SKIP] 非交易日=0 / [NOT-READY]=2 / 正常=0），
    自愈判据用「该日有无桥登记」（dates_bridge）——桥与主流程是两套登记族，
    不能用主流程的 dates_any 判（主流程有登记不代表桥跑过）。"""
    import bisect as _bis
    fc = _fc()
    lp, lp_stocks, lp_idx = _lp_universe()
    explicit = bool(sd)
    if explicit:
        if not fc.is_trading_day(sd):
            print(f"[SKIP] bridge: {sd} 非交易日（官方交易日历），无需登记")
            return 0
        expected, candidates = sd, [sd]
    else:
        now = _bjt_now()
        if not fc.is_trading_day(now.date().isoformat()):
            print(f"[SKIP] bridge: 今天 {now.date().isoformat()} 非交易日（官方交易日历）")
            return 0
        expected = _expected_day(now)
        candidates = _candidate_days(expected)

    def _lp_cov(day):
        n = 0
        for s in lp_stocks.values():
            p = _bis.bisect_left(s["date"], day)
            if 0 <= p < s["n"] and s["date"][p] == day:
                n += 1
        return n

    total = len(lp_stocks)
    cov = {d: _lp_cov(d) for d in candidates}
    existing, _dates_any, dates_bridge = _load_existing()

    def _register(days):
        out = {}
        for day in sorted(days):
            new = 0
            with SHADOW.open("a") as f:
                for code, d in lp_stocks.items():
                    j = lp_idx.get(code, {}).get(day)
                    if j is None:
                        continue
                    for claim, detname in REGISTRY_SHADOW_CLAIMS.items():
                        key = (day, claim, code)
                        if key in existing:
                            continue
                        try:
                            hit = lp.REGISTRY[detname](d, j)
                        except KeyError:
                            print(f"[WARN] 桥检测器不存在: {detname}")
                            continue
                        except Exception as _e:
                            print(f"[WARN] 桥 {claim}@{code} 异常: {_e}")
                            continue
                        if hit:
                            existing.add(key)
                            f.write(json.dumps({"signal_date": day, "claim": claim, "code": code,
                                                "tier": None, "entry": None,
                                                "r1": None, "r5": None, "r10": None, "r20": None},
                                               ensure_ascii=False) + "\n")
                            new += 1
            out[day] = new
        return out

    if cov[expected] < 0.5 * total:
        heal = [d for d in candidates if d != expected and cov[d] >= 0.5 * total and d not in dates_bridge]
        if heal:
            print(f"[HEAL] bridge 补登记 {_register(heal)}")
        print(f"[NOT-READY] bridge: 期望登记日 {expected} 是交易日，但 lp 宇宙仅 "
              f"{cov[expected]}/{total} 票有当日 bar——上游 kcache 未就绪，非桥可自愈")
        return 2
    todo = [expected] + [d for d in candidates
                         if d != expected and cov[d] >= 0.5 * total and d not in dates_bridge]
    r = _register(todo)
    print(f"bridge_only: 登记 {r}")
    return 0


def _register_days_cs(stocks, days, existing):
    """主流程逐日登记（行业梯队按日重算，detect 口径与旧版逐字一致）。
    返回 {day: new}。幂等：去重键已存在即跳过（旧版同款 guard）。"""
    out = {}
    for day in sorted(days):
        idx_map = {}
        ladder = {}
        for code, ks in stocks.items():
            idx = next((j for j in range(len(ks) - 1, -1, -1) if ks[j]["date"] == day), None)
            if idx is None:
                continue
            idx_map[code] = idx
            if idx >= 1 and ks[idx - 1]["close"] > 0 \
                    and ks[idx]["close"] / ks[idx - 1]["close"] - 1 >= 0.098:
                ind = industry_map().get(code, {}).get("industry") or "?"
                ladder[ind] = ladder.get(ind, 0) + 1
        new = 0
        with SHADOW.open("a") as f:
            for code, idx in idx_map.items():
                for claim, tier in detect(code, stocks[code], idx, ladder):
                    key = (day, claim, code)
                    if key in existing:
                        continue
                    existing.add(key)
                    f.write(json.dumps({"signal_date": day, "claim": claim, "code": code,
                                        "tier": tier, "entry": None,
                                        "r1": None, "r5": None, "r10": None, "r20": None},
                                       ensure_ascii=False) + "\n")
                    new += 1
        out[day] = new
    return out


def _backfill_summary(stocks):
    """回填（entry/r1/r5/r10/r20，整文件重写）+ 汇总落 SUMMARY。口径与旧版逐字一致。
    返回 (filled, 累计单数)。本步与「当日是否就绪」无关——kcache 增长多少补多少，
    故 [NOT-READY] 路径也照跑。"""
    lines = [json.loads(x) for x in SHADOW.read_text().splitlines() if x.strip()]
    filled = 0
    for r in lines:
        ks = stocks.get(r["code"])
        if not ks:
            continue
        idx = {k["date"]: j for j, k in enumerate(ks)}
        si = idx.get(r["signal_date"])
        if si is None or si + 1 >= len(ks):
            continue
        if r.get("entry") is None:
            if r["claim"] in CLOSE_ENTRY_CLAIMS:
                # 信号日收盘入场（打板成交假设）；信号日一字全天（high==low）判不可成交
                if ks[si]["high"] <= ks[si]["low"] and ks[si]["close"] > ks[si - 1]["close"]:
                    r["untradeable"] = "信号日一字涨停买不进"  # 红队S9 同上
                    continue
                e = ks[si]["close"]
                if e <= 0:
                    continue
                r["entry"] = e
                filled += 1
            else:
                e = ks[si + 1]["open"]
                if e <= 0:
                    continue
                # 入场日可成交性（自查修正：一字剔除在入场日判，与 s10_retest 口径一致）
                pc0 = ks[si]["close"]
                gap = e / pc0 - 1 if pc0 > 0 else 0
                amp = (ks[si + 1]["high"] - ks[si + 1]["low"]) / pc0 if pc0 > 0 else 1
                if gap >= 0.095:
                    r["untradeable"] = "一字涨停买不进"
                    continue
                if gap <= -0.095 and amp < 0.01:
                    r["untradeable"] = "一字跌停锁死"
                    continue
                r["entry"] = e
                filled += 1
        if r.get("entry"):
            e = r.get("entry")
            # T+1 时序硬断言（2026-09-18 修）：出场日必须严格晚于入场日。
            # 现改为从入场日 ei 起算：ei=si（收盘入场）/ei=si+1（次日开盘入场）。
            ei = si if r["claim"] in CLOSE_ENTRY_CLAIMS else si + 1
            for tag, off in [("r1", 1), ("r5", 5), ("r10", 10), ("r20", 20)]:
                if r.get(tag) is None and ei + off < len(ks):  # 2026-09-22 修：旧登记记录缺 r5 键 → r[tag] KeyError 崩全盘（影子日更连错）
                    assert ei + off > ei, "出场日必须晚于入场日"
                    r[tag] = round(ks[ei + off]["close"] / e - 1 - FEE, 5)
                    filled += 1
    SHADOW.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in lines) + "\n")

    # 3. 汇总（只统计 entry 已填的单）
    import statistics as st
    summ = {}
    for r in lines:
        if r.get("entry") is None:
            continue
        for tag in ("r1", "r5", "r10", "r20"):
            v = r.get(tag)  # 旧记录可能缺键（2026-09-22 修，同上方回填）
            if v is None:
                continue
            key = (r["claim"], r["tier"] or "-", tag)
            summ.setdefault(key, []).append(v)
    out = {}
    for (claim, tier, tag), vs in sorted(summ.items()):
        out.setdefault(claim, {}).setdefault(tier, {})[tag] = {
            "n": len(vs), "win%": round(100 * sum(x > 0 for x in vs) / len(vs), 1),
            "mean%": round(100 * st.mean(vs), 2)}
    SUMMARY.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    return filled, len(lines)


def run_daily(sd):
    """主流程（cs 宇宙）。返回退出码：0 正常/[SKIP]，2 [NOT-READY]。

    DATA-10 语义：
    - 显式 SHADOW_DATE：非交易日 → [SKIP] 0；交易日但未就绪 → [NOT-READY] 2；
      就绪 → 只登记该日（保留旧回填语义，不做 walk-back）。
    - 默认：BJT 非交易日 → [SKIP] 0；期望日=今天(过 15:30)或前一交易日。
      期望日就绪 → 登记期望日 + 窗口内零登记的已就绪旧日（自愈）；
      期望日未就绪 → 先自愈能补的旧日 + 照常回填，再 [NOT-READY] 退出 2。"""
    stocks = load_stocks()
    fc = _fc()
    last_max = max(ks[-1]["date"] for ks in stocks.values())
    explicit = bool(sd)
    if explicit:
        if not fc.is_trading_day(sd):
            print(f"[SKIP] {sd} 非交易日（官方交易日历），无需登记")
            return 0
        expected, candidates = sd, [sd]
    else:
        now = _bjt_now()
        if not fc.is_trading_day(now.date().isoformat()):
            print(f"[SKIP] 今天 {now.date().isoformat()} 非交易日（官方交易日历）")
            return 0
        expected = _expected_day(now)
        candidates = _candidate_days(expected)
    total = len(stocks)
    # 自动路径的候选日都贴近 kcache 尾部（≤ 期望日，期望日≤今天），只看末 15 根足够；
    # 显式回填可能指向更老的日期，全序列扫。
    cov = {d: _cs_coverage(stocks, d, None if explicit else 15) for d in candidates}
    existing, dates_any, _dates_bridge = _load_existing()
    holes = [d for d in candidates if d != expected and cov[d] < 0.5 * total]
    if cov[expected] < 0.5 * total:
        heal = [d for d in candidates if d != expected and cov[d] >= 0.5 * total and d not in dates_any]
        if heal:
            print(f"[HEAL] 补登记 {_register_days_cs(stocks, heal, existing)}")
        filled, n_lines = _backfill_summary(stocks)
        print(f"[NOT-READY] 期望登记日 {expected} 是交易日，但 kcache 仅 {cov[expected]}/{total} 票 "
              f"有当日 bar（kcache 末 bar={last_max}）——上游 kcache 刷新未完成或失败，"
              f"非本脚本可自愈；回填照常（本次回填 {filled}，累计 {n_lines} 单）")
        return 2
    todo = [expected] + [d for d in candidates
                         if d != expected and cov[d] >= 0.5 * total and d not in dates_any]
    reg = _register_days_cs(stocks, todo, existing)
    filled, n_lines = _backfill_summary(stocks)
    new_total = sum(reg.values())
    extra = f"，注意窗口内有 kcache 空洞日 {holes}" if holes else ""
    print(f"shadow: 新登记 {new_total}（{reg}），回填 {filled}，累计 {n_lines} 单{extra}")
    return 0


def main():
    import os
    # DATA-07 熔断（R1-①追加型拒写）：影子台账写错直接污染胜率统计。
    # 在任何写盘（SHADOW append/重写、SUMMARY）之前判定；默认路径用体检基准日。
    import breaker
    _sd = os.environ.get("SHADOW_DATE")
    _ok, _why = breaker.allow("影子盘", _sd if _sd else None)
    if not _ok:
        print(f"🚨 熔断拒写（DATA-07）：{_why}")
        _sys.exit(1)
    if os.environ.get("BRIDGE_ONLY"):
        _sys.exit(bridge_only(_sd))
    _sys.exit(run_daily(_sd))


if __name__ == "__main__":
    main()
