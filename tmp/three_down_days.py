"""三连阴全量细分回测（2026-09-23 晚，用户 Q3+Q5，点名：会稽山601579/骏亚科技603386）。

信号=三连阴（连续3日收阴即收<昨收），信号日=第3日收盘，入场=第4日开盘，出=第4日收盘(T+1)/
第5日(T+2)/T+5 收盘，费 0.15%，含退市股，全主板 8 年。
细分维度：
  Q3 位置（MA60上下）、regime、前期20日涨幅（退潮 vs 非退潮）
  Q5 第三日量能特征：
    vol_exp = v3/mean(v1,v2)（第三日放量/缩量）
    bar_shrink = |pct3| vs |pct2|（第三日绿柱缩小=卖压减弱）
    绿柱变小+缩量 → 第4日红？第5日呢？看量能还是情绪？
点名票逐例列出。
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
regime = lp.load_regime()

events = []
for code, d in stocks.items():
    if code[:2] not in ("60", "00"):
        continue
    n = d["n"]
    for i in range(64, n - 6):
        c, v, o, dt = d["c"], d["v"], d["o"], d["date"]
        if c[i - 1] <= 0 or o[i + 1] <= 0:
            continue
        # 三连阴：i-2, i-1, i 三日收阴
        if not (c[i - 2] < c[i - 3] and c[i - 1] < c[i - 2] and c[i] < c[i - 1]):
            continue
        p1, p2, p3 = (c[i - 2] / c[i - 3] - 1, c[i - 1] / c[i - 2] - 1, c[i] / c[i - 1] - 1)
        vexp = v[i] / ((v[i - 2] + v[i - 1]) / 2) if (v[i - 2] + v[i - 1]) > 0 else 1.0
        shrink = abs(p3) < abs(p2)  # 第三日绿柱比第二日小
        entry = o[i + 1]
        ma = d["ma60"][i]
        ev = {"code": code, "date": dt[i], "vexp": vexp, "shrink": shrink, "p3": p3,
              "pos": "low" if ma and c[i] <= ma else "high",
              "prior20": c[i] / c[i - 20] - 1 if c[i - 20] > 0 else 0,
              "regime": regime.get(dt[i], "?"),
              "t1": c[i + 1] / entry - 1 - FEE,  # 第4日收盘
              "t2": c[i + 2] / entry - 1 - FEE,  # 第5日
              "t5": c[i + 5] / entry - 1 - FEE}
        events.append(ev)
print(f"三连阴事件 {len(events)}", flush=True)


def blk(rows, lb):
    if len(rows) < 30:
        return
    for h in ("t1", "t2", "t5"):
        xs = [r[h] for r in rows]
        wr = sum(1 for x in xs if x > 0) / len(xs)
        m = st.mean(xs)
        pay = st.mean([x for x in xs if x > 0]) / abs(st.mean([x for x in xs if x < 0])) if any(x < 0 for x in xs) and any(x > 0 for x in xs) else 0
        tag = {"t1": "T+1(第4日)", "t2": "T+2(第5日)", "t5": "T+5"}[h]
        print(f"  {lb:<26} {tag:<11} n={len(xs):>6} {wr * 100:5.1f}%/{m * 100:+5.2f}% 赔率{pay:.2f}")


print("\n═══ 全体基线 ═══")
blk(events, "全部三连阴")

print("\n═══ Q5a 第三日量能（相对前两日） ═══")
for lo, hi, lb in ((0, 0.8, "缩量(v<0.8x)"), (0.8, 1.2, "平量(0.8-1.2x)"), (1.2, 2.0, "放量(1.2-2x)"), (2.0, 99, "巨量(>2x)")):
    blk([r for r in events if lo <= r["vexp"] < hi], f"{lb}")

print("\n═══ Q5b 第三日绿柱大小 ═══")
blk([r for r in events if r["shrink"]], "绿柱变小(卖压减弱)")
blk([r for r in events if not r["shrink"]], "绿柱放大(还在杀)")

print("\n═══ Q5c 量能×绿柱 组合 ═══")
blk([r for r in events if r["shrink"] and r["vexp"] < 0.8], "绿柱变小+缩量")
blk([r for r in events if r["shrink"] and r["vexp"] >= 0.8], "绿柱变小+放量")
blk([r for r in events if not r["shrink"] and r["vexp"] >= 1.2], "绿柱放大+放量(还有得跌?)")
blk([r for r in events if not r["shrink"] and r["vexp"] < 0.8], "绿柱放大+缩量")

print("\n═══ Q3 位置 × regime ═══")
for pos in ("low", "high"):
    blk([r for r in events if r["pos"] == pos], f"位置={pos}")
for g in ("妖股期", "恐慌期", "平淡期", "主线期"):
    blk([r for r in events if r["regime"] == g], f"regime={g}")

print("\n═══ Q3 前期20日（退潮 vs 非退潮） ═══")
blk([r for r in events if r["prior20"] > 0.15], "前20日大涨>15%(退潮)")
blk([r for r in events if r["prior20"] < -0.05], "前20日已跌>5%(继续崩)")
blk([r for r in events if -0.05 <= r["prior20"] <= 0.15], "前20日平盘")

print("\n═══ 点名票逐例 ═══")
for code, nm in (("601579", "会稽山"), ("603386", "骏亚科技")):
    evs = [r for r in events if r["code"] == code]
    print(f"{nm}({code}) 共 {len(evs)} 次三连阴:")
    for r in evs[-8:]:
        print(f"  {r['date']} regime={r['regime']} 位置={r['pos']} vexp={r['vexp']:.2f} 绿柱变小={r['shrink']} "
              f"T+1 {r['t1'] * 100:+.1f}% T+2 {r['t2'] * 100:+.1f}% T+5 {r['t5'] * 100:+.1f}%")

json.dump(events, open(f"{ROOT}/data/three_down_days_20260923.json", "w"), ensure_ascii=False)
print("\nsaved data/three_down_days_20260923.json")
