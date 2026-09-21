"""L3 组合层 v1 实测（2026-09-22 夜班，用户问「有没有综合在一起优化」——纲领空洞#2）。

问题：X3/X2/T1-MEGA/深档DEEP/PEAD 五条线各自独立跑仓位，同一天多线开火时无仲裁。
本模块（永久件，组合层第一块砖）：
  1) 逐日收集五线生产口径信号（探测器/簇门/streak 全部照抄 xrules_daily+deep_low 生产件）
  2) 共触发热力图 + 选票级重叠（同股同日多线命中）
  3) 联合资金曲线 vs 各线独立：100万、10槽、槽位=10万、优先级仲裁（声明在前：深档DEEP>X3>T1-MEGA>X2>PEAD，
     按主张等级排）、同股同日合并持仓（取高优先级线的出场规则）、PEAD 变体单独跑（T+20 占槽 4 倍于 T+5）
口径：入场次日开盘（一字跌停跳过），出场 T+3/T+5/T+20 收盘，X2/X3 -12% 收盘止损，费 0.3%（生产影子口径）。
"""
import collections
import json
import sys

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

ROOT = "/opt/data/fenjue"
FEE = 0.003
CAP0 = 1_000_000.0
SLOTS = 10
PRIORITY = ["深档DEEP", "X3", "T1-MEGA", "X2", "PEAD"]  # 预声明：按主张等级，非事后调
HOLD = {"T1-MEGA": 3, "X2": 5, "X3": 5, "深档DEEP": 5, "PEAD": 20}
STOP12 = {"X2", "X3"}

stocks = lp.load_universe()
lp.build_xsection(stocks)
regime = lp.load_regime()
idx = json.loads(open(f"{ROOT}/data/index_sh000001.json").read())
cal = [k["date"] for k in idx]
in_cal = set(cal)

# 恐慌期 streak
streak = {}
s = 0
for d in cal:
    s = s + 1 if regime.get(d) == "恐慌期" else 0
    streak[d] = s

DET_GAP = lp.REGISTRY["组合_缺口低开_低位阳线_避周一"]
DETS_PANIC = {k: lp.REGISTRY[v] for k, v in
              {"跌停底座": "组合_跌停低_三连阴", "复活门": "反转族_跌停潮50", "摇篮": "妖股摇篮_成簇",
               "TD9输家": "组合_跌停低_TD9买_输家250", "TD9超跌": "组合_跌停低_TD9买_超跌20"}.items()}
GATED = {"跌停底座", "TD9输家", "TD9超跌"}
DET_DEEP = lp.REGISTRY["组合_跌停低_深跌"]
PEAD = lp._pead_set()
print("universe", len(stocks), flush=True)

# ── 第一遍：逐股逐日收集各线信号 ──
# sigs[line][date] = [(code, i, sortkey)]
sigs = {k: collections.defaultdict(list) for k in PRIORITY}
for code, d in stocks.items():
    n = d["n"]
    c, h, v, ma = d["c"], d["h"], d["v"], d["ma60"]
    evmap = PEAD.get(code, {})
    for i in range(lp.START, n - 21):
        dt = d["date"][i]
        if dt not in in_cal or lp._epx(d, i) <= 0:
            continue
        hi60 = max(h[max(0, i - 60):i]) if i >= 1 else 0
        pos60 = c[i - 1] / hi60 - 1 if hi60 > 0 else 0
        vols = [v[x] for x in range(max(1, i - 5), i)]
        vr = v[i] / (sum(vols) / len(vols)) if vols and sum(vols) > 0 else 1
        try:
            if DET_GAP(d, i):
                sigs["T1-MEGA"][dt].append((code, i, vr))
        except Exception:
            pass
        # X2/X3 候选（恐慌族，含 claim 供 GATED 簇数）
        for cn, dn in DETS_PANIC.items():
            try:
                if dn(d, i):
                    sigs.setdefault("_pan", collections.defaultdict(list))[dt].append((code, i, pos60, cn))
            except Exception:
                pass
        try:
            if DET_DEEP(d, i):
                sigs["深档DEEP"][dt].append((code, i, c[i] / ma[i] if ma[i] else 0))
        except Exception:
            pass
        pe = evmap.get(dt)
        if pe and pe.get("FORECASTTYPE") in ("首亏", "扭亏"):
            sigs["PEAD"][dt].append((code, i, 0))
    if code.endswith("000"):
        print(".", end="", flush=True)
print("\n信号收集完", flush=True)

# ── 逐日判定开火 + 选票 ──
days_lines = {}   # date -> {line: [(code, i)]}
for dt in cal:
    rg = regime.get(dt, "?")
    ldc = lp._XLDC.get(dt, 0)
    gap = sigs["T1-MEGA"].get(dt, [])
    pan = sigs["_pan"].get(dt, [])
    pan_cl = len({c for c, _, _, cn in pan if cn in GATED})
    big = pan_cl >= 5 or len(gap) >= 8 or ldc >= 30
    fired = {}
    if len(gap) >= 20:
        fired["T1-MEGA"] = [(c, i) for c, i, _ in sorted(gap, key=lambda x: -x[2])[:10]]
    shallow = sorted(pan, key=lambda x: -x[2])
    if rg == "恐慌期" and streak.get(dt, 0) >= 2 and big:
        fired["X3"] = [(c, i) for c, i, _, _ in shallow[:3]]
    if rg in ("妖股期", "恐慌期") and big:
        fired["X2"] = [(c, i) for c, i, _, _ in shallow[:3]]
    deep = sigs["深档DEEP"].get(dt, [])
    if len(deep) >= 5:
        fired["深档DEEP"] = [(c, i) for c, i, _ in sorted(deep, key=lambda x: x[2])[:5]]
    pe = sigs["PEAD"].get(dt, [])
    if pe:
        fired["PEAD"] = [(c, i) for c, i, _ in pe[:5]]
    if fired:
        days_lines[dt] = fired

# 共触发统计
cofire = sum(1 for v in days_lines.values() if len(v) >= 2)
pair = collections.Counter()
pick_overlap = collections.Counter()
for dt, f in days_lines.items():
    lines = sorted(f)
    for a in range(len(lines)):
        for b in range(a + 1, len(lines)):
            pair[(lines[a], lines[b])] += 1
    allp = collections.Counter()
    for ln, pk in f.items():
        for c, _ in pk:
            allp[c] += 1
    for c, k in allp.items():
        if k >= 2:
            pick_overlap[dt] += 1
print(f"开火日 {len(days_lines)}，其中多线共触发 {cofire} 天")
print("线对共触发 TOP:", pair.most_common(8))
print(f"选票级重叠日（同股≥2线）: {len(pick_overlap)} 天", flush=True)

# ── 联合组合模拟 ──
didx = {c: {x: j for j, x in enumerate(s["date"])} for c, s in stocks.items()}


def run_sim(lines_on, label):
    cash, pos, trades, eqs = CAP0, [], [], []
    overflow = 0
    for day in cal:
        # 出场
        keep = []
        for p in pos:
            code, ei, xi, val, line = p["code"], p["ei"], p["xi"], p["val"], p["line"]
            j = didx[code].get(day, -1)
            if j < 0:
                keep.append(p)
                continue
            d = stocks[code]
            stop = line in STOP12 and j >= ei and d["c"][j] <= d["o"][ei] * 0.88
            if j >= xi or (stop and j >= ei):
                if d["o"][ei] <= 0:
                    keep.append(p)
                    continue
                r = d["c"][j] / d["o"][ei] - 1 - FEE
                cash += val * (1 + r)
                trades.append({"line": line, "ret": r, "exit": day, "how": "止损" if stop else "到期"})
            else:
                keep.append(p)
        pos = keep
        # 入场（昨日信号，今日开盘）
        k = cal.index(day)
        if k > 0:
            yday = cal[k - 1]
            f = days_lines.get(yday, {})
            for line in PRIORITY:
                if line not in f or line not in lines_on:
                    continue
                for code, i in f[line]:
                    if len(pos) >= SLOTS:
                        overflow += 1
                        break
                    if any(p["code"] == code for p in pos):
                        continue  # 同股合并
                    j = didx[code].get(day, -1)
                    if j != i + 1 or j >= stocks[code]["n"]:
                        continue
                    o = stocks[code]["o"][j]
                    if o <= 0:
                        continue
                    pc = stocks[code]["c"][i]
                    # 一字跌停买不进（开≈跌停且振幅极小近似）
                    if pc > 0 and o <= pc * 0.905 and stocks[code]["h"][j] <= o * 1.001:
                        continue
                    xi = i + 1 + HOLD[line]
                    val = min(CAP0 / SLOTS, cash)
                    if val < 1000:
                        overflow += 1
                        continue
                    cash -= val
                    pos.append({"code": code, "ei": j, "xi": xi, "val": val, "line": line})
        eqs.append((day, cash + sum(p["val"] for p in pos), cash))
    # 指标
    eq = [v for _, v, _ in eqs]
    years = len(cal) / 244
    total_ret = eq[-1] / CAP0 - 1
    ann = (eq[-1] / CAP0) ** (1 / years) - 1
    peak, mdd = eq[0], 0.0
    for v in eq:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    wr = sum(1 for t in trades if t["ret"] > 0) / len(trades) if trades else 0
    mean_r = sum(t["ret"] for t in trades) / len(trades) if trades else 0
    avg_cash = sum(c for _, _, c in eqs) / len(eqs) / CAP0
    by_line = collections.defaultdict(list)
    for t in trades:
        by_line[t["line"]].append(t["ret"])
    yearly = collections.defaultdict(list)
    for t in trades:
        yearly[t["exit"][:4]].append(t["ret"])
    res = {
        "label": label, "lines": lines_on, "笔数": len(trades),
        "年化%": round(ann * 100, 2), "总收益%": round(total_ret * 100, 1),
        "最大回撤%": round(mdd * 100, 1), "胜率": round(wr, 4), "均笔%": round(mean_r * 100, 2),
        "溢出跳过": overflow, "平均空仓比例": round(avg_cash, 3),
        "分线": {k: {"n": len(v), "胜率": round(sum(1 for x in v if x > 0) / len(v), 3),
                     "均笔%": round(sum(v) / len(v) * 100, 2)} for k, v in by_line.items()},
        "逐年收益事件和%": {y: round(sum(v) * 100, 1) for y, v in sorted(yearly.items())},
    }
    print(f"\n═══ {label} ═══")
    print(f"  笔数{res['笔数']} 年化{res['年化%']}% 回撤{res['最大回撤%']}% 胜率{res['胜率'] * 100:.0f}% 均笔{res['均笔%']}% 空仓比{res['平均空仓比例']:.0%} 溢出{overflow}")
    for k, v in res["分线"].items():
        print(f"    {k}: n={v['n']} {v['胜率'] * 100:.0f}%/{v['均笔%']}%")
    print("  逐年:", res["逐年收益事件和%"], flush=True)
    return res


results = {
    "共触发": {"开火日": len(days_lines), "多线共触发日": cofire,
               "线对TOP": {f"{a}&{b}": n for (a, b), n in pair.most_common(10)},
               "选票重叠日": len(pick_overlap)},
    "联合五线": run_sim(set(PRIORITY), "联合五线（含PEAD T+20）"),
    "联合四线": run_sim({"X3", "X2", "T1-MEGA", "深档DEEP"}, "联合四线（不含PEAD）"),
    "单线_深档DEEP": run_sim({"深档DEEP"}, "单线 深档DEEP"),
    "单线_X3": run_sim({"X3"}, "单线 X3"),
    "单线_T1-MEGA": run_sim({"T1-MEGA"}, "单线 T1-MEGA"),
    "单线_X2": run_sim({"X2"}, "单线 X2"),
    "单线_PEAD": run_sim({"PEAD"}, "单线 PEAD(T+20)"),
}
json.dump(results, open(f"{ROOT}/data/combo_layer_v1_20260922.json", "w"), ensure_ascii=False, indent=1, default=str)
print("\nsaved data/combo_layer_v1_20260922.json")
