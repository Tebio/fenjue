"""深档×低价CB 混腿组合回测（2026-09-25，BACKLOG#23，用户「继续」）。

生产日=深档簇≥5（2023-01 起，CB 数据起点限制）。腿A=深跌件(≤-35%)深度前5（生产口径）；
腿B=当日收盘≤105 的转债等权（最多5只，取价最低者）。
出场：T+5 与 T+20 双口径。配比：100/0、70/30、50/50（A/B）。
评估：批均收益、批胜率、批最大回撤、序列复利净值（批间空仓）。
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
cb_k = json.load(open(f"{ROOT}/data/cb_klines.json"))
cb_idx = {c: {r["date"]: k for k, r in enumerate(rows)} for c, rows in cb_k.items()}

# ① 全市场深档簇（2023 起）
cluster = collections.Counter()
events = []
for code, d in stocks.items():
    if code[:2] not in ("60", "00"):
        continue
    n = d["n"]
    for i in range(60, n - 21):
        dt = d["date"][i]
        if dt < "2023-01-01" or d["c"][i - 1] <= 0:
            continue
        ma = d["ma60"][i]
        if not ma:
            continue
        pct = d["c"][i] / d["c"][i - 1] - 1
        if pct <= -0.095 and d["c"][i] <= ma * 0.75:
            cluster[dt] += 1
            if d["c"][i] <= ma * 0.65 and d["o"][i + 1] > 0:
                events.append({"date": dt, "code": code, "depth": d["c"][i] / ma - 1,
                               "t5": d["c"][i + 5] / d["o"][i + 1] - 1 - FEE,
                               "t20": d["c"][i + 20] / d["o"][i + 1] - 1 - FEE})

prod_days = sorted(d for d, k in cluster.items() if k >= 5)
print(f"生产日（2023起）{len(prod_days)} 天", flush=True)

by_day_stock = collections.defaultdict(list)
for e in events:
    if e["date"] in set(prod_days):
        by_day_stock[e["date"]].append(e)


def cb_picks(dt, max_n=5):
    cands = []
    for code, rows in cb_k.items():
        k = cb_idx[code].get(dt)
        if k is None:
            continue
        px = rows[k]["close"]
        if 80 < px <= 105 and k + 21 < len(rows) and rows[k + 1]["open"] > 0:
            cands.append((px, code, k))
    cands.sort()
    out = []
    for px, code, k in cands[:max_n]:
        rows = cb_k[code]
        out.append({"code": code,
                    "t5": rows[k + 5]["close"] / rows[k + 1]["open"] - 1 - FEE,
                    "t20": rows[k + 20]["close"] / rows[k + 1]["open"] - 1 - FEE})
    return out


for h in ("t5", "t20"):
    print(f"\n═══ 出场 {h.upper()} ═══")
    for w_a, lb in ((1.0, "100%股票深档"), (0.7, "70/30 混腿"), (0.5, "50/50 混腿")):
        batch_rets, batch_mdd = [], []
        cb_days = 0
        for dt in prod_days:
            sa = sorted(by_day_stock.get(dt, []), key=lambda x: x["depth"])[:5]
            if not sa:
                continue
            cb = cb_picks(dt)
            if cb:
                cb_days += 1
            ra = st.mean(e[h] for e in sa)
            rb = st.mean(e[h] for e in cb) if cb else ra  # 无CB时该腿并入股票
            batch_rets.append(w_a * ra + (1 - w_a) * rb)
            batch_mdd.append(min(ra, rb) if cb else ra)
        n = len(batch_rets)
        wins = sum(1 for x in batch_rets if x > 0)
        nav = 1.0
        for x in batch_rets:
            nav *= 1 + x
        print(f"  {lb:<12} 批数{n:>3} 批均{st.mean(batch_rets) * 100:+5.2f}% 批胜率{wins / n * 100:3.0f}% "
              f"最差批{min(batch_rets) * 100:+6.1f}% 复利{((nav - 1) * 100):+7.1f}% （有CB腿的批次 {cb_days}）")
