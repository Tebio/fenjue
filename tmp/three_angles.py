"""三角度测试（2026-09-25 深夜，用户「换个角度想问题」）。

①土壤门：生产批次按信号日指数位置分（指数 vs 其 MA20）——假恐慌（指数在 MA20 上）批次是不是亏的
②修复基因：个股历史深跌件后的平均修复率（该票过去 ≤-35% 事件的 T+10 均值）作选股排序因子
③板块出清×个股深度：深跌件中优先选所属板块当日跌>3% 的（板块级出清+个股级深度）
口径：8 年，簇≥5 深跌≤-35% 前5，次日开盘入，费 0.15%，含退市股。
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
idx_data = json.load(open(f"{ROOT}/data/index_sh000001.json"))
idx_map = {k["date"]: float(k["close"]) for k in idx_data}
idx_dates = sorted(idx_map)
idx_ma20 = {}
for k, dt in enumerate(idx_dates):
    if k >= 19:
        idx_ma20[dt] = sum(idx_map[idx_dates[k - 19 + j]] for j in range(20)) / 20

mmap = json.load(open(f"{ROOT}/data/industry_map.json"))
code2ind = {str(k).zfill(6): v["industry"] for k, v in mmap.items() if isinstance(v, dict) and v.get("industry")}

cluster = collections.Counter()
events = []
for code, d in stocks.items():
    if code[:2] not in ("60", "00"):
        continue
    n = d["n"]
    for i in range(60, n - 21):
        if d["c"][i - 1] <= 0:
            continue
        ma = d["ma60"][i]
        if not ma:
            continue
        pct = d["c"][i] / d["c"][i - 1] - 1
        if pct <= -0.095 and d["c"][i] <= ma * 0.75:
            cluster[d["date"][i]] += 1
            if d["c"][i] <= ma * 0.65 and d["o"][i + 1] > 0:
                events.append({"code": code, "date": d["date"][i], "i": i,
                               "depth": d["c"][i] / ma - 1, "pct": pct,
                               "ind": code2ind.get(code, "")})
prod = {d for d, k in cluster.items() if k >= 5}
events = [e for e in events if e["date"] in prod]

# 板块日收益
ind_day = collections.defaultdict(lambda: collections.defaultdict(list))
for code, d in stocks.items():
    ind = code2ind.get(code, "")
    if not ind:
        continue
    for i in range(1, d["n"]):
        if d["c"][i - 1] > 0 and d["date"][i] in prod:
            ind_day[d["date"][i]][ind].append(d["c"][i] / d["c"][i - 1] - 1)
ind_mean = {dt: {k: st.mean(v) for k, v in inds.items()} for dt, inds in ind_day.items()}

# ② 修复基因：每个事件计算「该票此前深跌件的 T+10 修复率均值」
hist = collections.defaultdict(list)  # code -> [past t10 recovery]
by_day = collections.defaultdict(list)
for e in sorted(events, key=lambda x: x["date"]):
    d = stocks[e["code"]]
    i = e["i"]
    e["t10"] = d["c"][i + 10] / d["o"][i + 1] - 1 - FEE
    e["gene"] = st.mean(hist[e["code"]]) if len(hist[e["code"]]) >= 2 else None
    e["ind_ret"] = ind_mean.get(e["date"], {}).get(e["ind"], 0)
    by_day[e["date"]].append(e)
    hist[e["code"]].append(e["t10"])


def batch_stats(days, lb):
    if len(days) < 10:
        print(f"  {lb}: 批数{len(days)} 不足")
        return
    bs = [st.mean(e["t10"] for e in p) for p in days]
    nav = 1.0
    for x in bs:
        nav *= 1 + x
    print(f"  {lb:<26} 批数{len(bs):>3} 批胜率{sum(1 for x in bs if x > 0) / len(bs) * 100:3.0f}% "
          f"批均{st.mean(bs) * 100:+5.2f}% 最差批{min(bs) * 100:+6.1f}% 复利{nav:.2f}x")


print("═══ ① 土壤门：信号日指数位置 ═══")
for lb, cond in (("真恐慌(指数≤MA20)", lambda dt: idx_map.get(dt, 0) <= idx_ma20.get(dt, 0)),
                 ("假恐慌(指数>MA20)", lambda dt: idx_map.get(dt, 0) > idx_ma20.get(dt, 0))):
    days = []
    for dt, evs in by_day.items():
        if not cond(dt):
            continue
        p = sorted([e for e in evs if e["depth"] <= -0.35], key=lambda x: x["depth"])[:5]
        if p:
            days.append(p)
    batch_stats(days, lb)
# 分年交叉验证假恐慌
for y in ("2024", "2025", "2026"):
    days = [sorted([e for e in evs if e["depth"] <= -0.35], key=lambda x: x["depth"])[:5]
            for dt, evs in by_day.items()
            if dt[:4] == y and idx_map.get(dt, 0) > idx_ma20.get(dt, 0)]
    days = [p for p in days if p]
    batch_stats(days, f"假恐慌 {y}")

print("\n═══ ② 修复基因选股（同生产日，基因≥2 样本优先） ═══")
for lb, key in (("深度前5(基准)", lambda evs: sorted(evs, key=lambda x: x["depth"])[:5]),
                ("基因优先后深度", lambda evs: (lambda g, n: (g + n)[:5])(
                    sorted([e for e in evs if e["gene"] is not None], key=lambda x: -(x["gene"] or 0)),
                    sorted([e for e in evs if e["gene"] is None], key=lambda x: x["depth"])))):
    days = []
    for dt, evs in by_day.items():
        pool = sorted([e for e in evs if e["depth"] <= -0.35], key=lambda x: x["depth"])
        if pool:
            days.append(key(pool))
    batch_stats(days, lb)

print("\n═══ ③ 板块出清×个股深度双滤 ═══")
for lb, cond in (("板块当日跌>3%的深跌件", lambda e: e["ind_ret"] <= -0.03),
                 ("板块跌≤3%的深跌件", lambda e: e["ind_ret"] > -0.03)):
    xs = [e for evs in by_day.values() for e in evs if e["depth"] <= -0.35 and cond(e)]
    if len(xs) >= 20:
        wr = sum(1 for e in xs if e["t10"] > 0) / len(xs)
        print(f"  {lb}: 事件 n={len(xs)} {wr * 100:.1f}%/{st.mean([e['t10'] for e in xs]) * 100:+.2f}%")
# 组合：板块出清优先排序
days = []
for dt, evs in by_day.items():
    pool = [e for e in evs if e["depth"] <= -0.35]
    if not pool:
        continue
    deep_ind = sorted([e for e in pool if e["ind_ret"] <= -0.03], key=lambda x: x["depth"])
    rest = sorted([e for e in pool if e["ind_ret"] > -0.03], key=lambda x: x["depth"])
    days.append((deep_ind + rest)[:5])
batch_stats(days, "板块出清优先前5")
batch_stats([sorted([e for e in evs if e["depth"] <= -0.35], key=lambda x: x["depth"])[:5]
             for evs in by_day.values() if any(e["depth"] <= -0.35 for e in evs)], "深度前5(基准)")
