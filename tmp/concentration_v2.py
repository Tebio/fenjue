"""Q2 集中度修正版（2026-09-22）：只看生产成簇日（深档件≥5），三种分仓对比。

A 平分（5×20%）B 集中（50/30/20）C 梭哈第1深。
按批口径：批收益=Σ(w_i × t5_i)，批间等权累计。同时给 2026 年段（与 5 万模拟对齐）。
"""
import collections
import json
import statistics as st
import sys

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

ROOT = "/opt/data/fenjue"
FEE = 0.0015

stocks = lp.load_universe()
cluster = collections.Counter()
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
        if pct <= -0.095 and d["c"][i] <= ma * 0.75:
            cluster[d["date"][i]] += 1
            if d["c"][i] <= ma * 0.65 and d["o"][i + 1] > 0:
                events.append({"date": d["date"][i], "code": code, "depth": d["c"][i] / ma - 1,
                               "t5": d["c"][i + 5] / d["o"][i + 1] - 1 - FEE})

prod_days = {d for d, k in cluster.items() if k >= 5}
by_day = collections.defaultdict(list)
for e in events:
    if e["date"] in prod_days:
        by_day[e["date"]].append(e)
print(f"成簇日 {len(by_day)} 天，事件 {sum(len(v) for v in by_day.values())}")

# 干净度特征：idio（个股跌幅-板块均跌幅）+ prior20（前20日涨幅）
mmap = json.loads(open(f"{ROOT}/data/industry_map.json").read())
code2ind = {str(k).zfill(6): v["industry"] for k, v in mmap.items() if isinstance(v, dict) and v.get("industry")}
ind_day = collections.defaultdict(lambda: collections.defaultdict(list))
for code, d in stocks.items():
    ind = code2ind.get(code, "")
    if not ind:
        continue
    n = d["n"]
    for i in range(1, n):
        if d["c"][i - 1] <= 0 or cluster.get(d["date"][i], 0) < 5:
            continue
        ind_day[d["date"][i]][ind].append(d["c"][i] / d["c"][i - 1] - 1)
ind_mean = {dt: {k: st.mean(v) for k, v in inds.items()} for dt, inds in ind_day.items()}
for e in events:
    d = stocks[e["code"]]
    i = d["date"].index(e["date"])
    ind = code2ind.get(e["code"], "")
    e["idio"] = (d["c"][i] / d["c"][i - 1] - 1) - ind_mean.get(e["date"], {}).get(ind, 0)
    e["prior20"] = d["c"][i - 1] / d["c"][i - 21] - 1 if i >= 21 and d["c"][i - 21] > 0 else 0
    e["clean"] = e["idio"] > -0.03 and e["prior20"] <= 0.15

MODES = {"A平分5×20%": [0.2, 0.2, 0.2, 0.2, 0.2],
         "B集中50/30/20": [0.5, 0.3, 0.2],
         "C梭哈第1深": [1.0]}
for scope, dayfilter in (("全史", lambda d: True), ("2026", lambda d: d >= "2026-01-01")):
    print(f"\n═══ {scope} ═══")
    for mode, ws in MODES.items():
        for clean_only in (False, True):
            batch_rets = []
            for dt, evs in by_day.items():
                if not dayfilter(dt):
                    continue
                evs = sorted(evs, key=lambda x: x["depth"])[:5]
                if clean_only:
                    evs = [e for e in evs if e["clean"]]
                    if not evs:
                        continue  # 无干净票=当日空仓
                r = sum(w * e["t5"] for w, e in zip(ws, evs))
                batch_rets.append(r)
            if not batch_rets:
                continue
            n = len(batch_rets)
            wins = sum(1 for x in batch_rets if x > 0)
            tag = "只买干净" if clean_only else "全部票  "
            print(f"  {mode:<14}{tag} 批数{n:>3} 累计{sum(batch_rets) * 100:+7.1f}% 批均{st.mean(batch_rets) * 100:+5.2f}% "
                  f"批胜率{wins / n * 100:.0f}% 最差批{min(batch_rets) * 100:+.1f}%")
