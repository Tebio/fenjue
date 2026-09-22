"""10:30 深砸×收盘收复 V 型信号（2026-09-22，从「为什么不在10:30买」的测量副产物立项）。

发现：深档测量里 10:30≤-9.5% 但收盘未坐实的「假阳性」T+1 95.7%/+9.4%（n=23，簇门语境）。
本研究：全宇宙无簇门，两年 m60 窗，参数网格：
  深砸档 X ∈ {7%, 8.5%, 9.5%}（10:30 bar 收盘 vs 昨收）
  收复档 Y ∈ {收盘 > -2%, > -5%, > -7%}（收复=收盘相对 10:30 价回升）
入场=10:30 bar 收盘（可成交，一字锁死剔除），对照组：
  a) 同深砸但收盘未收复（继续走弱）——区分「收复」是否真因子
  b) 位置匹配随机（同股 MA60 下随机日）
出场 T+1/3/5/10 收盘，费 0.15%。预登记活格：n≥100 且 T+1 t≥3 且 对照 a 差 >2pp。
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
W0 = "2024-08-30"

stocks = lp.load_universe()
for d in stocks.values():
    d["_didx"] = {x: j for j, x in enumerate(d["date"])}
print("universe", len(stocks), flush=True)

events = []
for code, d in stocks.items():
    if code[:2] not in ("60", "00"):
        continue
    try:
        ks = json.load(open(f"{ROOT}/data/m60_cache/{code}.json"))
    except Exception:
        continue
    by = {}
    for b in ks:
        by.setdefault(b["day"][:10], {})[b["day"][11:16]] = b
    n = d["n"]
    for i in range(60, n - 11):
        dt = d["date"][i]
        if dt < W0 or d["c"][i - 1] <= 0:
            continue
        b1030 = by.get(dt, {}).get("10:30")
        b15 = by.get(dt, {}).get("15:00")
        if not b1030:
            continue
        p = float(b1030["close"])
        if p <= 0:
            continue
        pct1030 = p / d["c"][i - 1] - 1
        if pct1030 > -0.07:
            continue
        # 一字锁死剔除（10:30 收≈跌停且 bar 高≈收）
        if float(b1030["high"]) <= p * 1.001 and pct1030 <= -0.098:
            continue
        close_pct = d["c"][i] / d["c"][i - 1] - 1
        recover = d["c"][i] / p - 1  # 收盘相对 10:30 价的回升幅度
        ma = d["ma60"][i]
        rec = {"code": code, "i": i, "date": dt, "pct1030": pct1030, "close_pct": close_pct,
               "recover": recover, "pos": ("low" if ma and d["c"][i] <= ma else "high"),
               "entry": p}
        for h in (1, 3, 5, 10):
            j = i + h
            rec[h] = (d["c"][j] / p - 1 - FEE) if j < n else None
        events.append(rec)
print(f"10:30 深砸≥7% 事件 {len(events)}", flush=True)


def blk(rows, hs=(1, 3, 5, 10)):
    if len(rows) < 10:
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


# 网格：深砸档 × 收复档
print("\n═══ 网格：10:30 深砸 X% × 收盘收复（收盘跌幅 > -Y%）═══")
grid = {}
for X in (0.07, 0.085, 0.095):
    deep = [e for e in events if e["pct1030"] <= -X]
    for Y in (0.02, 0.05, 0.07):
        rec = [e for e in deep if e["close_pct"] > -Y]      # 收复组
        not_rec = [e for e in deep if e["close_pct"] <= -Y]  # 未收复组（对照a）
        b1, b2 = blk(rec), blk(not_rec)
        grid[f"X={X}·Y={Y}"] = {"收复": b1, "未收复": b2}
        t1a = b1.get("T+1", {})
        t1b = b2.get("T+1", {})
        diff = (t1a.get("mean", 0) - t1b.get("mean", 0)) if t1a and t1b else 0
        print(f"  X={X * 100:.1f}% Y={Y * 100:.0f}%: 收复 n={b1['n']} T+1 {t1a.get('wr', 0) * 100:.0f}%/{t1a.get('mean', 0):+.2f}%(t{t1a.get('t')}) T+5 {b1.get('T+5', {}).get('wr', 0) * 100:.0f}%/{b1.get('T+5', {}).get('mean', 0):+.2f}% | "
              f"未收复 n={b2['n']} T+1 {t1b.get('wr', 0) * 100:.0f}%/{t1b.get('mean', 0):+.2f}% | 收复-未收复 {diff:+.2f}pp")

# 位置分层（最强格）
best = [e for e in events if e["pct1030"] <= -0.085 and e["close_pct"] > -0.05]
print(f"\n═══ 最强格（X=8.5% Y=5%）位置分层 ═══")
for pos in ("low", "high"):
    b = blk([e for e in best if e["pos"] == pos])
    print(f"  MA60{pos}: {b}")

json.dump({"grid": grid, "n_events": len(events)}, open(f"{ROOT}/data/v_recovery_1030_20260922.json", "w"),
          ensure_ascii=False, indent=1)
print("\nsaved data/v_recovery_1030_20260922.json")
