"""细分发现的双段复验（2026-09-22 夜班）：只验两个候选改造格。

A. T1-MEGA 选票排序：vr≥2 vs vr<2（梯队维度实测是平的，挑战 #135 的梯队优先）
B. 深档DEEP 深度锐化：≤-35% vs -35~-25%
每格：2019-2022 / 2023-2026 双段 + 逐年，n/胜率/均值/t。
"""
import collections, json, math, statistics as st, sys
sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

ROOT = "/opt/data/fenjue"
FEE = 0.003
stocks = lp.load_universe()
lp.build_xsection(stocks)
regime = lp.load_regime()
idx = json.loads(open(f"{ROOT}/data/index_sh000001.json").read())
cal = [k["date"] for k in idx]
for d in stocks.values():
    d.setdefault("_didx", {x: j for j, x in enumerate(d["date"])})

DET_GAP = lp.REGISTRY["组合_缺口低开_低位阳线_避周一"]
DET_DEEP = lp.REGISTRY["组合_跌停低_深跌"]
mmap = json.loads(open(f"{ROOT}/data/industry_map.json").read())
code2ind = {str(k).zfill(6): v["industry"] for k, v in mmap.items() if isinstance(v, dict) and v.get("industry")}

gap_days, deep_days = collections.defaultdict(list), collections.defaultdict(list)
for code, d in stocks.items():
    n = d["n"]
    c, o, h, v, ma = d["c"], d["o"], d["h"], d["v"], d["ma60"]
    for i in range(lp.START, n - 6):
        if lp._epx(d, i) <= 0:
            continue
        dt = d["date"][i]
        vols = [v[x] for x in range(max(1, i - 5), i)]
        vr = v[i] / (sum(vols) / len(vols)) if vols and sum(vols) > 0 else 1
        try:
            if DET_GAP(d, i):
                gap_days[dt].append({"code": code, "i": i, "vr": vr})
        except Exception:
            pass
        try:
            if DET_DEEP(d, i) and ma[i]:
                deep_days[dt].append({"code": code, "i": i, "depth": c[i] / ma[i] - 1})
        except Exception:
            pass

# 梯队按日补
for dt, rows in gap_days.items():
    boards = collections.Counter()
    for code2, d2 in stocks.items():
        j = d2["_didx"].get(dt)
        if j and j >= 1 and d2["c"][j] / d2["c"][j - 1] - 1 >= 0.098:
            boards[code2ind.get(code2, "")] += 1
    for r in rows:
        r["ladder"] = boards.get(code2ind.get(r["code"], ""), 0)


def blk(rows):
    if len(rows) < 10:
        return f"n={len(rows)}"
    xs = [r["ret"] for r in rows]
    m = st.mean(xs)
    sd = st.stdev(xs) if len(xs) > 1 else 0
    return f"n={len(xs)} {sum(1 for x in xs if x > 0) / len(xs) * 100:.0f}%/{m * 100:+.2f}% t={m / (sd / math.sqrt(len(xs))):.1f}" if sd else "?"


# A: T1-MEGA 生产选票，按 vr 分组
mega = []
for dt in cal:
    rows = gap_days.get(dt, [])
    if len(rows) >= 20 and regime.get(dt) == "妖股期":
        for r in sorted(rows, key=lambda x: (-(x["ladder"] >= 3), -x["vr"]))[:10]:
            d = stocks[r["code"]]
            i = r["i"]
            if i + 4 < d["n"] and d["o"][i + 1] > 0:
                mega.append({**r, "date": dt, "ret": d["c"][i + 4] / d["o"][i + 1] - 1 - FEE})
print(f"═══ A. T1-MEGA 选票按量比（n={len(mega)}）═══")
for grp, fn in (("vr≥2", lambda r: r["vr"] >= 2), ("vr 1-2", lambda r: 1 <= r["vr"] < 2), ("vr<1", lambda r: r["vr"] < 1),
                ("梯队≥3", lambda r: r["ladder"] >= 3), ("梯队<3", lambda r: r["ladder"] < 3)):
    sel = [r for r in mega if fn(r)]
    s1 = [r for r in sel if r["date"] < "2023"]
    s2 = [r for r in sel if r["date"] >= "2023"]
    yr = {y: blk([r for r in sel if r["date"].startswith(y)]) for y in ("2019", "2020", "2021", "2022", "2023", "2024", "2025", "2026")}
    yr = {k: v for k, v in yr.items() if not v.startswith("n=0")}
    print(f"  {grp:<8} 全: {blk(sel)}")
    print(f"           19-22: {blk(s1)} | 23-26: {blk(s2)}")
    print(f"           逐年: {yr}")

# B: 深档DEEP 按深度
deep_ev = []
for dt in cal:
    rows = deep_days.get(dt, [])
    if len(rows) >= 5:
        for r in sorted(rows, key=lambda x: x["depth"])[:5]:
            d = stocks[r["code"]]
            i = r["i"]
            if i + 6 < d["n"] and d["o"][i + 1] > 0:
                deep_ev.append({**r, "date": dt, "ret": d["c"][i + 6] / d["o"][i + 1] - 1 - FEE})
print(f"\n═══ B. 深档DEEP 选票按深度（n={len(deep_ev)}）═══")
for grp, fn in (("≤-35%", lambda r: r["depth"] <= -0.35), ("-35~-25%", lambda r: -0.35 < r["depth"] <= -0.25)):
    sel = [r for r in deep_ev if fn(r)]
    s1 = [r for r in sel if r["date"] < "2023"]
    s2 = [r for r in sel if r["date"] >= "2023"]
    yr = {y: blk([r for r in sel if r["date"].startswith(y)]) for y in ("2019", "2020", "2021", "2022", "2023", "2024", "2025", "2026")}
    yr = {k: v for k, v in yr.items() if not v.startswith("n=0")}
    print(f"  {grp:<10} 全: {blk(sel)}")
    print(f"             19-22: {blk(s1)} | 23-26: {blk(s2)}")
    print(f"             逐年: {yr}")
