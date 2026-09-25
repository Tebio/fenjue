"""深档 v2 三维优化（2026-09-25，用户「看看还能怎么调整优化」）。

A 参数敏感性：簇门{3,5,8}×深跌门{-30,-35,-40}%×持仓{T+3,5,10}×票数{3,5,8}——高原还是悬崖
B 出场变体：固定T+5 vs 收>MA5出场(10日上限) vs 先到先出
C 干净度排序：簇日内 深度前5(生产) vs 干净度优先(干净=板块同跌idio>-3%且前20日≤+15%)前5
口径：2023起（与CB线对齐），次日开盘入，费0.15%，含退市股。
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

# 板块日收益（idio 用）
mmap = json.load(open(f"{ROOT}/data/industry_map.json"))
code2ind = {str(k).zfill(6): v["industry"] for k, v in mmap.items() if isinstance(v, dict) and v.get("industry")}

# ① 全事件（2023起，深档件 -25% 起全记，后续按门过滤）
ind_day = collections.defaultdict(lambda: collections.defaultdict(list))
daily = {}
for code, d in stocks.items():
    if code[:2] not in ("60", "00"):
        continue
    ind = code2ind.get(code, "")
    n = d["n"]
    for i in range(60, n - 21):
        dt = d["date"][i]
        if dt < "2023-01-01" or d["c"][i - 1] <= 0:
            continue
        pct = d["c"][i] / d["c"][i - 1] - 1
        if ind:
            ind_day[dt][ind].append(pct)
        ma = d["ma60"][i]
        if ma and pct <= -0.095 and d["c"][i] <= ma * 0.75 and d["o"][i + 1] > 0:
            prior20 = d["c"][i] / d["c"][i - 20] - 1 if d["c"][i - 20] > 0 else 0
            daily.setdefault(dt, []).append({
                "code": code, "i": i, "pct": pct, "ind": ind,
                "depth": d["c"][i] / ma - 1, "prior20": prior20, "ma": ma})
ind_mean = {dt: {k: st.mean(v) for k, v in inds.items()} for dt, inds in ind_day.items()}

for dt, evs in daily.items():
    for e in evs:
        d = stocks[e["code"]]
        i = e["i"]
        e["idio"] = e["pct"] - ind_mean.get(dt, {}).get(e["ind"], 0)
        e["clean"] = e["idio"] > -0.03 and e["prior20"] <= 0.15
        entry = d["o"][i + 1]
        for h in (3, 5, 10, 20):
            e[f"t{h}"] = d["c"][i + h] / entry - 1 - FEE
        # Connors 出场（收>MA5，10 日上限）
        for j in range(i + 1, min(i + 11, d["n"])):
            ma5 = st.mean(d["c"][j - 4:j + 1])
            if d["c"][j] > ma5 or j == min(i + 10, d["n"] - 1):
                e["connors"] = d["c"][j] / entry - 1 - FEE
                break
        else:
            e["connors"] = None

print(f"事件天数 {len(daily)}，总深档件 {sum(len(v) for v in daily.values())}", flush=True)


def batch_stats(picks_by_day, h):
    rets = [st.mean(p[h] for p in picks) for picks in picks_by_day if picks and all(h in p for p in picks)]
    if len(rets) < 10:
        return None
    nav = 1.0
    for x in rets:
        nav *= 1 + x
    return (len(rets), sum(1 for x in rets if x > 0) / len(rets), st.mean(rets), min(rets), nav)


# A 参数敏感性
print("\n═══ A 参数敏感性（批均/批胜率/最差批，按簇门×深跌门×持仓×票数） ═══")
for cg in (3, 5, 8):
    for dg in (-0.30, -0.35, -0.40):
        for h in (3, 5, 10):
            row = []
            for topn in (3, 5, 8):
                days = []
                for dt, evs in daily.items():
                    if len(evs) < cg:
                        continue
                    picks = sorted([e for e in evs if e["depth"] <= dg], key=lambda x: x["depth"])[:topn]
                    if picks:
                        days.append(picks)
                r = batch_stats(days, f"t{h}")
                row.append(f"n{r[0]} {r[1]*100:.0f}%/{r[2]*100:+.1f}% 最差{r[3]*100:+.0f}%" if r else "—")
            print(f"  簇≥{cg} 深跌≤{dg * 100:.0f}% T+{h}: " + " | ".join(row))

# B 出场变体（生产参数：簇≥5 深跌≤-35% 前5）
print("\n═══ B 出场变体（生产参数） ═══")
prod_days = {dt: sorted([e for e in evs if e["depth"] <= -0.35], key=lambda x: x["depth"])[:5]
             for dt, evs in daily.items() if len(evs) >= 5}
prod_days = {dt: p for dt, p in prod_days.items() if p}
for h, lb in (("t5", "固定T+5(生产)"), ("connors", "收>MA5(10日限)"), ("t10", "固定T+10"), ("t20", "固定T+20")):
    r = batch_stats(list(prod_days.values()), h)
    if r:
        print(f"  {lb:<14} 批数{r[0]} 批胜率{r[1] * 100:.0f}% 批均{r[2] * 100:+.2f}% 最差批{r[3] * 100:+.1f}% 复利{r[4]:.2f}x")

# C 干净度排序
print("\n═══ C 干净度排序（同生产日） ═══")
for lb, key in (("深度前5(生产)", lambda evs: sorted(evs, key=lambda x: x["depth"])[:5]),
                ("干净优先前5", lambda evs: (lambda cl, dt: (cl + dt)[:5])(sorted([e for e in evs if e["clean"]], key=lambda x: x["depth"]), sorted([e for e in evs if not e["clean"]], key=lambda x: x["depth"])))):
    days = []
    for dt, evs in daily.items():
        if len(evs) < 5:
            continue
        pool = sorted([e for e in evs if e["depth"] <= -0.35], key=lambda x: x["depth"])
        if not pool:
            continue
        days.append(key(pool))
    for h in ("t5", "t20"):
        r = batch_stats(days, h)
        if r:
            print(f"  {lb} {h.upper()}: 批数{r[0]} 批胜率{r[1] * 100:.0f}% 批均{r[2] * 100:+.2f}% 最差批{r[3] * 100:+.1f}%")
