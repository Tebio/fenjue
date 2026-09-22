"""日内深V信号·8年日K终审（2026-09-22，10:30 测量的正式化）。

信号：当日最低 ≤ 昨收×(1-X)（盘中深砸）且 收盘 > 昨收×(1-Y)（收复，Y<X）→ 长下影深V。
入场=次日开盘（生产口径），出场 T+1/3/5/10 收盘，费 0.15%，含退市股宇宙。
网格 X∈{7,8.5,9.5}% × Y∈{2,5,7}% + 对照（同深砸未收复）+ 位置分层 + 逐年 + regime
+ 与大长腿_低位（_biglower，已 DEAD 的形态近亲）的重叠检查——必须证明这不是死人复活。
预登记活格：n≥300，T+1 t≥3，双段（19-22/23-26）同号为正，vs 未收复对照差>2pp，与大长腿重叠<50%。
"""
import collections
import json
import math
import statistics as st
import sys

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

ROOT = "/opt/data/fenjue"
FEE = 0.0015

stocks = lp.load_universe()
lp.build_xsection(stocks)
regime = lp.load_regime()
print("universe", len(stocks), flush=True)

events = []
for code, d in stocks.items():
    if code[:2] not in ("60", "00"):
        continue
    n = d["n"]
    for i in range(60, n - 11):
        if d["c"][i - 1] <= 0 or lp._epx(d, i) <= 0:
            continue
        low_pct = d["l"][i] / d["c"][i - 1] - 1
        if low_pct > -0.07:
            continue
        close_pct = d["c"][i] / d["c"][i - 1] - 1
        ma = d["ma60"][i]
        # 一字跌停锁死（开=低≈跌停）剔除：买不进
        if d["l"][i] <= d["c"][i - 1] * 0.901 and d["o"][i] <= d["l"][i] * 1.005 and d["h"][i] <= d["l"][i] * 1.01:
            continue
        e = {"code": code, "i": i, "date": d["date"][i], "year": d["date"][i][:4],
             "seg": "2019-2022" if d["date"][i] < "2023" else "2023-2026",
             "regime": regime.get(d["date"][i], "?"),
             "low_pct": low_pct, "close_pct": close_pct,
             "pos": ("low" if ma and d["c"][i] <= ma else "high"),
             "biglower": bool(ma and d["c"][i] <= ma and lp.REGISTRY["大长腿_低位"](d, i)) if ma else False}
        entry = d["o"][i + 1]
        for h in (1, 3, 5, 10):
            j = i + h
            e[h] = (d["c"][j] / entry - 1 - FEE) if j < n else None
        events.append(e)
print(f"日内曾砸≥7% 事件 {len(events)}", flush=True)


def blk(rows, hs=(1, 3, 5, 10)):
    if len(rows) < 30:
        return {"n": len(rows)}
    out = {"n": len(rows)}
    for h in hs:
        xs = [r[h] for r in rows if r.get(h) is not None]
        if xs:
            m = st.mean(xs)
            sd = st.stdev(xs) if len(xs) > 1 else 0
            out[f"T+{h}"] = {"wr": round(sum(1 for x in xs if x > 0) / len(xs), 3),
                             "mean": round(m * 100, 2),
                             "t": round(m / (sd / math.sqrt(len(xs))), 1) if sd else None}
    return out


results = {}
print("\n═══ 8 年日K网格（次日开盘入场）═══")
for X in (0.07, 0.085, 0.095):
    deep = [e for e in events if e["low_pct"] <= -X]
    for Y in (0.02, 0.05, 0.07):
        rec = [e for e in deep if e["close_pct"] > -Y]
        nrec = [e for e in deep if e["close_pct"] <= -Y]
        b1, b2 = blk(rec), blk(nrec)
        key = f"X={X}·Y={Y}"
        # 双段
        s1 = blk([e for e in rec if e["seg"] == "2019-2022"])
        s2 = blk([e for e in rec if e["seg"] == "2023-2026"])
        results[key] = {"收复": b1, "未收复": b2, "收复_19-22": s1, "收复_23-26": s2}
        t1a, t1b = b1.get("T+1", {}), b2.get("T+1", {})
        print(f"  {key}: 收复 n={b1['n']} T+1 {t1a.get('wr', 0) * 100:.0f}%/{t1a.get('mean', 0):+.2f}%(t{t1a.get('t')}) "
              f"T+5 {b1.get('T+5', {}).get('wr', 0) * 100:.0f}%/{b1.get('T+5', {}).get('mean', 0):+.2f}% | "
              f"未收复 {t1b.get('wr', 0) * 100:.0f}%/{t1b.get('mean', 0):+.2f}% | "
              f"双段 {s1.get('T+1', {}).get('mean', 0):+.2f}/{s2.get('T+1', {}).get('mean', 0):+.2f}")

# 最强格细分
best = [e for e in events if e["low_pct"] <= -0.085 and e["close_pct"] > -0.05]
print(f"\n═══ X=8.5% Y=5%（n={len(best)}）═══")
for pos in ("low", "high"):
    print(f"  MA60{pos}: {blk([e for e in best if e['pos'] == pos])}")
yb = collections.defaultdict(list)
for e in best:
    yb[e["year"]].append(e)
print("  逐年T+1:", {y: f"{blk(v).get('T+1', {}).get('wr', 0) * 100:.0f}%/{blk(v).get('T+1', {}).get('mean', 0):+.2f}%(n{len(v)})"
                 for y, v in sorted(yb.items())})
rb = collections.defaultdict(list)
for e in best:
    rb[e["regime"]].append(e)
print("  regimeT+1:", {g: f"{blk(v).get('T+1', {}).get('wr', 0) * 100:.0f}%/{blk(v).get('T+1', {}).get('mean', 0):+.2f}%(n{len(v)})"
                   for g, v in sorted(rb.items())})
# 与大长腿重叠
both = [e for e in best if e["biglower"]]
only_v = [e for e in best if not e["biglower"]]
print(f"  与大长腿_低位重叠: {len(both)}/{len(best)} ({len(both) / len(best) * 100:.0f}%)")
print(f"  重叠部分: {blk(both)}")
print(f"  纯V部分: {blk(only_v)}")

json.dump(results, open(f"{ROOT}/data/deep_v_8y_20260922.json", "w"), ensure_ascii=False, indent=1)
print("\nsaved data/deep_v_8y_20260922.json")
