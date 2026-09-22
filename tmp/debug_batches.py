import collections
import json
import statistics as st
import sys

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

stocks = lp.load_universe()
events = []
for code, d in stocks.items():
    if code[:2] not in ("60", "00"):
        continue
    n = d["n"]
    for i in range(60, n - 6):
        if d["c"][i - 1] <= 0:
            continue
        ma = d["ma60"][i]
        if not ma:
            continue
        pct = d["c"][i] / d["c"][i - 1] - 1
        if pct <= -0.095 and d["c"][i] <= ma * 0.65:
            t5 = d["c"][i + 5] / d["o"][i + 1] - 1 - 0.0015 if d["o"][i + 1] > 0 else None
            events.append({"date": d["date"][i], "t5": t5, "depth": d["c"][i] / ma - 1})

print("事件", len(events))
by_day = collections.defaultdict(list)
for e in events:
    if e["t5"] is not None:
        by_day[e["date"]].append(e)
print("批次", len(by_day))
bm = [st.mean(e["t5"] for e in evs) for evs in by_day.values()]
print("批均值: 均", round(st.mean(bm) * 100, 2), "最差", round(min(bm) * 100, 2), "最好", round(max(bm) * 100, 2))
print("批数分布:", collections.Counter(len(v) for v in by_day.values()))
