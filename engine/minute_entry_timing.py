#!/usr/bin/env python3
"""engine/minute_entry_timing.py — 分钟级入场择时研究（kanban t_316237a5，第三波）

问题：信号日 T 次日（T+1 入场日）内部，三种入场哪个好——
  E0 开盘价直接买（现行口径）
  P* 盘中回踩买（VWAP 回踩 / 跌穿开盘价 X% 回收 / 日 MA5 触碰；回踩不到=踏空，踏空率必报）
  T1 尾盘 14:30 后确认买（当日走势定型后，买在 14:30-15:00 窗口 VWAP）

三条存活线的生产原口径探测器（禁手写近似）：
  LD   跌停接剔一字      = law_pipeline._limitdown（T 日 ≤-9.5%，剔全天一字锁死）
  DEEP 深档低位v2        = dashboard_build.deep_low_scan（簇门：全库「≤-9.5% 且收<MA60 且
                           收≤MA60×0.75」≥5；出手票=收≤MA60×0.65 深度最深前 5，剔 ST）
  REV  反转族确认后名单   = scripts/reversal_daily.py scan+confirm（T 日收跌≥3%、非一字跌停开、
                           成交额≥8e7（kcache 无 amount，用 v×c 代理）、剔 ST；
                           T+1 9:32 确认：剔一字跌停开、>1/3 候选高开>1% 当日作废）

通用可交易性过滤：T+1 一字跌停开（open ≤ 前收×0.905）买不进 → 事件剔除（全口径一致）；
信号日→入场日间隔 >10 自然日（长停牌）剔除。

数据：baostock 5 分钟线（2020-01-02 起，adjustflag=3 不复权，#274 实测可用）。
  禁双进程：本脚本单进程单登录串行拉取，0.12s 间隔+失败退避重登。
  分钟↔日K 对齐：entry_qfq = open_qfq(T+1) × entry_min / open_min(T+1)（日内同源比值，
  复权口径相消）；|open_min/open_qfq - 1| > 2% 判数据错位剔除（ex-div 哨兵同思路）。
  出场价用 big_kcache 前复权收盘：T+1 收盘（剩余段）/ T+5 收盘（全段）/ T+10（DEEP 补充，
  生产已切 T+10）。净口径 fee=0.0015（与 law_pipeline 一致，单扣）。

内存纪律：分钟数据流式逐 (code,date) 处理，算完 6 个口径入场价即弃，append JSONL 断点续跑。

用法：
  python engine/minute_entry_timing.py enum     # 日K 枚举事件集（快）
  python engine/minute_entry_timing.py fetch    # 拉 5 分钟线计入场价（慢，可断点续跑）
  python engine/minute_entry_timing.py report   # 聚合出三线×三口径矩阵
"""
import json, glob, math, random, statistics as st, sys, time
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
KC = ROOT / "data/big_kcache"
EVENTS_JSON = ROOT / "data/minute_timing_events.json"
FILLS_JSONL = ROOT / "data/minute_timing_fills.jsonl"
REPORT_JSON = ROOT / "data/minute_entry_timing_20261015.json"
from costs import FLAT_RT  # TAX-01 唯一真源 engine/costs.py（AGENTS #287）
FEE = FLAT_RT
MIN_START = "2020-01-02"          # baostock 5 分线起点（#274）
SPLIT = "2022-12-31"              # 双段：2020-22 / 2023-26
SEED = 20261015
CAP_REV, CAP_LD = 4500, 5000      # 宽族抽样上限（按年分层）
TRIALS = 18                       # 6 入场变体 × 3 线（DSR trials 如实报）
BJT = timezone(timedelta(hours=8))


# ---------------------------------------------------------------- 统计辅助（对齐 exec_timing_m60）
def nw_t(rs, lag=1):
    n = len(rs)
    if n < lag + 30:
        return None
    m = st.mean(rs)
    s = sum((r - m) ** 2 for r in rs) / n
    for L in range(1, lag + 1):
        cov = sum((rs[t] - m) * (rs[t - L] - m) for t in range(L, n)) / n
        s += 2 * (1 - L / (lag + 1)) * cov
    return round(m / math.sqrt(s / n), 1) if s > 0 else None


def S(rs):
    rs = [r for r in rs if r is not None]
    if len(rs) < 30:
        return None
    wins = [r for r in rs if r > 0]
    loss = [r for r in rs if r <= 0]
    return {"n": len(rs), "win%": round(100 * len(wins) / len(rs), 1),
            "net%": round(100 * st.mean(rs), 2), "med%": round(100 * st.median(rs), 2),
            "odds": round(st.mean(wins) / abs(st.mean(loss)), 2) if wins and loss else None,
            "nw_t": nw_t(rs)}


def dsr_from_events(day_rets, trials=TRIALS):
    """日历时间口径 DSR：按入场日聚合等权日收益 → 日频 Sharpe → deflated_sharpe。"""
    try:
        sys.path.insert(0, str(ROOT / "engine"))
        from law_pipeline import deflated_sharpe
    except Exception:
        return None
    if len(day_rets) < 30:
        return None
    days = sorted(day_rets)
    series = [st.mean(day_rets[d]) for d in days]
    m = st.mean(series)
    sd = st.pstdev(series)
    if sd <= 0:
        return None
    sr = m / sd
    sk = st.mean([(x - m) ** 3 for x in series]) / sd ** 3
    ku = st.mean([(x - m) ** 4 for x in series]) / sd ** 4
    return deflated_sharpe(sr, len(series), sk, ku, trials=trials)


# ---------------------------------------------------------------- 事件枚举（日K，生产原口径）
def _load_names():
    try:
        return {str(s["code"]).zfill(6): s.get("name", "")
                for s in json.loads((ROOT / "data/main_board_codes.json").read_text())["stocks"]}
    except Exception:
        return {}


def _is_st(names, code):
    nm = names.get(code, "")
    return "ST" in nm or "退" in nm


def enum_events():
    names = _load_names()
    ev = {"LD": [], "DEEP": [], "REV": []}
    deep_by_day = {}   # date -> [(code, i, depth)]  簇门计数用
    rev_by_day = {}    # sig_date -> [(code, i, open_chg)] 确认作废规则用
    files = sorted(glob.glob(str(KC / "*.json")))
    for fp in files:
        code = Path(fp).stem
        if code[:2] not in ("60", "00") or _is_st(names, code):
            continue
        ks = json.loads(open(fp).read())
        n = len(ks)
        if n < 300:
            continue
        c = [k["close"] for k in ks]
        o = [k["open"] for k in ks]
        h = [k["high"] for k in ks]
        l = [k["low"] for k in ks]
        v = [k.get("volume", 0.0) for k in ks]
        dates = [k["date"] for k in ks]
        pre = [0.0]
        for x in c:
            pre.append(pre[-1] + x)
        for i in range(60, n - 1):
            d1 = dates[i + 1]
            if d1 < MIN_START:
                continue
            if c[i - 1] <= 0:
                continue
            chg = c[i] / c[i - 1] - 1
            # 通用：入场日一字跌停开 = 买不进，剔除；长停牌剔除
            if o[i + 1] / c[i] - 1 <= -0.095:
                continue
            try:
                gap = (datetime.strptime(d1, "%Y-%m-%d") - datetime.strptime(dates[i], "%Y-%m-%d")).days
            except Exception:
                continue
            if gap > 10:
                continue
            if chg <= -0.095:
                # LD：剔全天一字锁死（开盘≈跌停且振幅<1%）
                if not (o[i] / c[i - 1] - 1 <= -0.09 and (h[i] - l[i]) / c[i - 1] < 0.01):
                    ev["LD"].append((code, i, dates[i]))
                # DEEP 簇门件：≤-9.5% 且收<MA60 且收≤MA60×0.75
                ma60 = (pre[i + 1] - pre[i - 59]) / 60
                if c[i] < ma60 and c[i] <= ma60 * 0.75:
                    deep_by_day.setdefault(dates[i], []).append((code, i, c[i] / ma60 - 1))
            if chg <= -0.03:
                # REV scan：非一字跌停开 + 成交额≥8e7（v×c 代理）
                if o[i] / c[i - 1] - 1 > -0.095 and v[i] * c[i] >= 8e7:
                    open_chg = o[i + 1] / c[i] - 1
                    rev_by_day.setdefault(dates[i], []).append((code, i, open_chg))
    # DEEP：簇门 ≥5 → 出手票=深度≤-35% 最深前 5
    for d, lst in deep_by_day.items():
        if len(lst) < 5:
            continue
        picks = sorted((x for x in lst if x[2] <= -0.35), key=lambda x: x[2])[:5]
        ev["DEEP"].extend((code, i, d) for code, i, _ in picks)
    # REV：confirm——剔入场日一字跌停开（枚举时已剔），>1/3 候选高开>1% → 当日作废
    for d, lst in rev_by_day.items():
        n0 = len(lst)
        if n0 == 0:
            continue
        hi = sum(1 for _, _, oc in lst if oc >= 0.01)
        if hi / n0 > 1 / 3:
            continue
        ev["REV"].extend((code, i, d) for code, i, _ in lst)

    # 分层抽样（REV/LD 宽族封顶；DEEP 全量）
    rng = random.Random(SEED)
    for line, cap in (("REV", CAP_REV), ("LD", CAP_LD)):
        lst = ev[line]
        if len(lst) > cap:
            by_year = {}
            for code, i, sd in lst:
                by_year.setdefault(sd[:4], []).append((code, i, sd))
            years = sorted(by_year)
            per = max(1, cap // len(years))
            keep = []
            for y in years:
                pool = by_year[y]
                keep.extend(rng.sample(pool, min(per, len(pool))))
            ev[line] = keep

    out = {"_meta": {"built_at": datetime.now(BJT).isoformat(), "seed": SEED,
                     "caps": {"REV": CAP_REV, "LD": CAP_LD}, "min_start": MIN_START,
                     "note": "事件=(code, i)，i=信号日在 big_kcache 内的下标"},
           "counts_raw": None, "lines": {}}
    for line in ev:
        ev[line].sort(key=lambda x: (x[2], x[0]))
        out["lines"][line] = [{"code": c0, "i": i0, "sig_date": sd}
                              for c0, i0, sd in ev[line]]
    out["counts_raw"] = {k: len(v) for k, v in ev.items()}
    EVENTS_JSON.write_text(json.dumps(out, ensure_ascii=False))
    print("enum done:", json.dumps(out["counts_raw"]), "->", EVENTS_JSON, flush=True)


_KCACHE_IDX = {}
_KCACHE_FULL = {}

def _ks_of(code):
    if code not in _KCACHE_FULL:
        _KCACHE_FULL[code] = json.loads(open(KC / f"{code}.json").read())
    return _KCACHE_FULL[code]

def _date_of(code, i):
    if code not in _KCACHE_IDX:
        _KCACHE_IDX[code] = [k["date"] for k in _ks_of(code)]
    return _KCACHE_IDX[code][i]


# ---------------------------------------------------------------- 分钟入场价计算（5 分线）
def entry_prices(bars, ma5_min):
    """bars: 入场日 5 分 bar 列表 [{t,o,h,l,c,v,a}]（已按时间排序）；ma5_min: 日 MA5 换算到分钟尺度。
    返回 dict：E0/P1_vwap/P2_dip1/P3_dip2/P4_ma5/T1_tail 的入场价（None=踏空/不适用）。"""
    if len(bars) < 45:                      # 完整交易日 48 根；半日停牌剔除
        return None
    o0 = bars[0]["o"]
    if o0 <= 0:
        return None
    out = {"E0_open": o0}
    # P1 VWAP 回踩：先站上（bar 收>累计VWAP）后回落至 VWAP → 在 VWAP 成交
    cum_v = cum_a = 0.0
    seen_above = False
    p1 = None
    for b in bars:
        cum_v += b["v"]
        cum_a += b["a"]
        vw = cum_a / cum_v if cum_v > 0 else b["c"]
        if p1 is None:
            if b["c"] > vw:
                seen_above = True
            elif seen_above and b["l"] <= vw:
                p1 = vw
    out["P1_vwap"] = p1
    # P2/P3 跌穿开盘价 X% 回收：先破（low≤level）后回收（high≥level）→ 在 level 成交
    for key, x in (("P2_dip1", 0.99), ("P3_dip2", 0.98)):
        lvl = o0 * x
        dipped = False
        px = None
        for b in bars:
            if px is None:
                if not dipped and b["l"] <= lvl:
                    dipped = True
                elif dipped and b["h"] >= lvl:
                    px = lvl
        out[key] = px
    # P4 日 MA5 触碰：挂单价=MA5；开盘已破 → 开盘价成交；盘中 low 触 → MA5 成交
    if ma5_min and ma5_min > 0:
        if o0 <= ma5_min:
            out["P4_ma5"] = o0
        else:
            out["P4_ma5"] = ma5_min if min(b["l"] for b in bars) <= ma5_min else None
    else:
        out["P4_ma5"] = None
    # T1 尾盘：14:30 后（bar 标签 14:35..15:00）窗口 VWAP
    tail = [b for b in bars if b["t"] >= "14:35"]
    tv = sum(b["v"] for b in tail)
    out["T1_tail"] = (sum(b["a"] for b in tail) / tv) if tv > 0 else None
    return out


def _alarm_handler(signum, frame):
    raise TimeoutError("baostock query stall")


def _query_day(bs, sym, ed, timeout_s=40):
    """单股单日 5 分线，signal.alarm 硬超时（socket timeout 对 baostock 内部阻塞无效）。"""
    import signal
    signal.signal(signal.SIGALRM, _alarm_handler)
    signal.alarm(timeout_s)
    try:
        rs = bs.query_history_k_data_plus(
            sym, "date,time,open,high,low,close,volume,amount",
            start_date=ed, end_date=ed, frequency="5", adjustflag="3")
        bars = []
        while rs.error_code == "0" and rs.next():
            d, t, o, h, l, c, v, a = rs.get_row_data()
            bars.append({"t": f"{t[8:10]}:{t[10:12]}", "o": float(o), "h": float(h),
                         "l": float(l), "c": float(c), "v": float(v), "a": float(a)})
        return bars
    finally:
        signal.alarm(0)


def _enrich_events():
    """单遍过 kcache，把事件富化成标量记录（fetch 与 report 共用，不驻留全量日K）。"""
    events = json.loads(EVENTS_JSON.read_text())["lines"]
    need = {}
    for line, lst in events.items():
        for e in lst:
            need.setdefault(e["code"], []).append((line, e["i"]))
    out = []
    for code, evs in need.items():
        try:
            ks = json.loads(open(KC / f"{code}.json").read())
        except Exception:
            continue
        for line, i in evs:
            if i + 1 >= len(ks):
                continue
            o_qfq = ks[i + 1]["open"]
            if o_qfq <= 0:
                continue
            out.append({
                "fkey": f"{line}:{code}:{i}", "line": line, "code": code,
                "ed": ks[i + 1]["date"], "o_qfq": o_qfq,
                "ma5": sum(k["close"] for k in ks[i - 4:i + 1]) / 5,
                "c1": ks[i + 1]["close"],
                "c5": ks[i + 5]["close"] if i + 5 < len(ks) else None,
                "c10": ks[i + 10]["close"] if i + 10 < len(ks) else None})
    return out


def fetch_fills():
    """串行拉 baostock 5 分线，逐事件算入场价，append JSONL（断点续跑）。禁双进程。
    限流纪律：0.5s 间隔；卡死 40s 硬超时→重登退避；开跑前探针等待 penalty 解除（≤90min）。
    内存纪律：开跑前单遍过 kcache 只取涉事票的标量（open/ma5/收盘出场价），不驻留全量日K。"""
    sys.path.insert(0, "/opt/data/python-libs")
    import baostock as bs
    if not EVENTS_JSON.exists():
        raise SystemExit("先跑 enum")
    enriched = _enrich_events()
    todo = {}
    for en in enriched:
        todo.setdefault((en["code"], en["ed"]), []).append(en)
    del enriched
    done = set()
    if FILLS_JSONL.exists():
        for ln in FILLS_JSONL.read_text().splitlines():
            try:
                r = json.loads(ln)
                done.add((r["code"], r["date"]))
            except Exception:
                continue
    keys = sorted(k for k in todo if k not in done)
    print(f"fetch: {len(todo)} 个 (code,date)，已完成 {len(done)}，本轮 {len(keys)}", flush=True)

    lg = bs.login()
    if lg.error_code != "0":
        raise SystemExit(f"baostock login failed: {lg.error_msg}")
    # 探针：等限流 penalty 解除（同一 IP/账号快速二连查曾触发服务端挂起，2026-10-16 实测）
    probe_deadline = time.time() + 90 * 60
    while True:
        try:
            pb = _query_day(bs, "sz.000001", "2024-06-03", timeout_s=40)
            if pb:
                print(f"probe ok（{len(pb)} bars），开跑", flush=True)
                break
        except Exception as ex:
            print(f"[probe] stall: {ex}", flush=True)
        if time.time() > probe_deadline:
            raise SystemExit("探针 90 分钟未通——baostock 不可用，退出待重跑（断点保留）")
        try:
            bs.logout()
        except Exception:
            pass
        time.sleep(120)
        bs.login()
    fout = open(FILLS_JSONL, "a")
    n_ok = n_fail = consec_fail = 0
    t0 = time.time()
    try:
        for k_i, (code, ed) in enumerate(keys):
            if k_i > 0 and k_i % 500 == 0:          # 长连接保鲜
                try:
                    bs.logout()
                except Exception:
                    pass
                bs.login()
            sym = ("sh." if code.startswith("6") else "sz.") + code
            bars = []
            for attempt in range(3):
                try:
                    bars = _query_day(bs, sym, ed)
                    break
                except Exception as ex:
                    print(f"[WARN] {code} {ed} attempt{attempt}: {ex}", flush=True)
                    time.sleep(30)
                    try:
                        bs.logout()
                    except Exception:
                        pass
                    bs.login()
            if not bars:
                n_fail += 1
                consec_fail += 1
                fout.write(json.dumps({"code": code, "date": ed, "fills": None}) + "\n")
                fout.flush()
                if consec_fail >= 10:
                    raise SystemExit("连续 10 次失败，疑似断连/限流——退出让上层报警（不静默成功）")
                time.sleep(0.5)
                continue
            consec_fail = 0
            bars.sort(key=lambda x: x["t"])
            om = bars[0]["o"]
            # 逐事件算入场价（同一 (code,date) 可被多条线的不同信号日引用，MA5 各异）。
            # 存 qfq 等价入场价：entry_qfq = o_qfq × entry_min / om（日内同源比值，复权相消）。
            rec = {"code": code, "date": ed, "open_min": om, "fills": {}}
            for en in todo[(code, ed)]:
                o_qfq = en["o_qfq"]
                # 哨兵=分钟/日K 同日一致性：r_open=om/o_qfq 与 r_close=c_min/c1_qfq 应相等
                # （历史分红会让 om/o_qfq≠1，那是正常复权因子，不是错位——2026-10-16 实证误杀）
                rc = bars[-1]["c"]
                if (om <= 0 or rc <= 0 or en["c1"] <= 0
                        or abs((om / o_qfq) / (rc / en["c1"]) - 1) > 0.02):
                    rec["fills"][en["fkey"]] = None              # 分钟↔日K 错位哨兵
                    continue
                ma5_min = en["ma5"] * om / o_qfq                 # 日MA5 换算到分钟尺度
                ep = entry_prices(bars, ma5_min)
                if ep is None:
                    rec["fills"][en["fkey"]] = None              # 半日停牌等
                    continue
                rec["fills"][en["fkey"]] = {
                    v: (round(o_qfq * pm / om, 6) if pm is not None else None)
                    for v, pm in ep.items()}
            fout.write(json.dumps(rec) + "\n")
            fout.flush()
            n_ok += 1
            if (k_i + 1) % 200 == 0:
                el = time.time() - t0
                eta = el / (k_i + 1) * (len(keys) - k_i - 1) / 60
                print(f"  {k_i+1}/{len(keys)} ok={n_ok} fail={n_fail} "
                      f"elapsed={el/60:.1f}min eta={eta:.1f}min", flush=True)
            time.sleep(0.5)
    finally:
        fout.close()
        bs.logout()
    print(f"fetch done: ok={n_ok} fail={n_fail}", flush=True)


# ---------------------------------------------------------------- 聚合报告
VARIANTS = ["E0_open", "P1_vwap", "P2_dip1", "P3_dip2", "P4_ma5", "T1_tail"]


def report():
    enriched = _enrich_events()
    fills = {}
    for ln in FILLS_JSONL.read_text().splitlines():
        r = json.loads(ln)
        if r.get("fills"):
            for fk, ep in r["fills"].items():
                fills[fk] = ep
    R = {"_meta": {"built_at": datetime.now(BJT).isoformat(), "fee": FEE, "trials": TRIALS,
                   "split": SPLIT, "variants": VARIANTS,
                   "口径": "fills 存 qfq 等价入场价=open_qfq(T+1)×entry_min/open_min；净=毛-0.0015；"
                          "T+1剩余段=入场→T+1收盘；T+5全段=入场→T+5收盘；DEEP 另报 T+10"},
         "lines": {}}
    by_line = {}
    for en in enriched:
        by_line.setdefault(en["line"], []).append(en)
    for line, lst in by_line.items():
        per = {v: {"r1": [], "r5": [], "r10": [], "r5_all": [], "day5": {}} for v in VARIANTS}
        n_no_fill_row = n_total = 0
        pair = {}   # (fkey) -> {v: r5}  配对用
        for en in lst:
            ep = fills.get(en["fkey"])
            if not ep:
                n_no_fill_row += 1
                continue
            n_total += 1
            c1, c5, c10, ed = en["c1"], en["c5"], en["c10"], en["ed"]
            pr = {}
            for v in VARIANTS:
                eq = ep.get(v)
                if eq is None:
                    if c5 is not None:
                        per[v]["r5_all"].append(0.0)             # 踏空=0 全口径
                    continue
                per[v]["r1"].append(c1 / eq - 1 - FEE)
                if c5 is not None:
                    r5 = c5 / eq - 1 - FEE
                    per[v]["r5"].append(r5)
                    per[v]["r5_all"].append(r5)
                    per[v]["day5"].setdefault(ed, []).append(r5)
                    pr[v] = r5
                if c10 is not None:
                    per[v]["r10"].append(c10 / eq - 1 - FEE)
            pair[en["fkey"]] = (ed, pr)
        # 配对择时增益（共同成交事件上 variant - E0，T+5 全段净口径相消费用）
        paired = {}
        for v in VARIANTS[1:]:
            diffs, diffs_a, diffs_b = [], [], []
            for ed, pr in pair.values():
                if v in pr and "E0_open" in pr:
                    d = pr[v] - pr["E0_open"]
                    diffs.append(d)
                    (diffs_a if ed <= SPLIT else diffs_b).append(d)
            paired[v] = {"n": len(diffs),
                         "gain_pp": round(100 * st.mean(diffs), 3) if diffs else None,
                         "nw_t": nw_t(diffs),
                         "2020-22_pp": round(100 * st.mean(diffs_a), 3) if len(diffs_a) >= 30 else None,
                         "2023-26_pp": round(100 * st.mean(diffs_b), 3) if len(diffs_b) >= 30 else None,
                         "sign_ok": (len(diffs_a) >= 30 and len(diffs_b) >= 30
                                     and st.mean(diffs_a) > 0 and st.mean(diffs_b) > 0)}
        lv = {"n_events": n_total, "n_fetch_missing": n_no_fill_row, "variants": {}}
        for v in VARIANTS:
            p = per[v]
            fill_rate = (len(p["r5"]) / n_total) if n_total else None
            lv["variants"][v] = {
                "fill%": round(100 * fill_rate, 1) if fill_rate is not None else None,
                "T+1剩余段": S(p["r1"]),
                "T+5全段": S(p["r5"]),
                "T+5全样本_踏空0": S([x for x in p["r5_all"] if x is not None]),
                "T+10全段": S(p["r10"]) if line == "DEEP" else None,
                "DSR_T5": dsr_from_events(p["day5"]),
            }
        lv["paired_gain_vs_E0"] = paired
        R["lines"][line] = lv
    REPORT_JSON.write_text(json.dumps(R, ensure_ascii=False, indent=1))
    # 控制台矩阵
    for line in R["lines"]:
        lv = R["lines"][line]
        print(f"\n=== {line}（n={lv['n_events']}，缺分钟数据 {lv['n_fetch_missing']}）===", flush=True)
        print(f"{'变体':<10}{'fill%':>7}{'T+1净%':>9}{'T+5净%':>9}{'T+5胜率':>8}"
              f"{'增益pp':>8}{'配对t':>7}{'20-22':>8}{'23-26':>8}{'DSR':>6}", flush=True)
        for v in VARIANTS:
            vv = lv["variants"][v]
            pg = lv["paired_gain_vs_E0"].get(v, {})
            t1 = vv["T+1剩余段"] or {}
            t5 = vv["T+5全段"] or {}
            print(f"{v:<10}{str(vv['fill%']):>7}{str(t1.get('net%')):>9}{str(t5.get('net%')):>9}"
                  f"{str(t5.get('win%')):>8}{str(pg.get('gain_pp')):>8}{str(pg.get('nw_t')):>7}"
                  f"{str(pg.get('2020-22_pp')):>8}{str(pg.get('2023-26_pp')):>8}"
                  f"{str(vv['DSR_T5']):>6}", flush=True)
    print("\n->", REPORT_JSON, flush=True)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    {"enum": enum_events, "fetch": fetch_fills, "report": report}[cmd]()
