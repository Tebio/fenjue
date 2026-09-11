#!/usr/bin/env python3
"""engine/holding_research.py — 持仓处置决策的 8 年大样本实证（2026-09-11 立项）

回答用户痛点：「大跌要不要跑 / 大涨要不要跑 / 假突破后怎么走 / 回本要不要 T」
数据：big_kcache 前复权日K（3191 只全主板，2019-05 ~ 2026-09-04）。
纪律（过 backtest-pitfalls 清单）：
  - 信号日 t 收盘确认 → 最早 t+1 开盘成交（无未来函数）
  - 净口径：所有收益减 0.15% 双边费
  - 随机对照组：同数量随机 (票,日) 对，同 horizons
  - 大盘环境代理：全主板等权日收益（自洽，免外部指数口径）
  - 窗口重叠非独立样本：报方向与量级，不报精确概率
"""
import json, glob, random, statistics as st
from pathlib import Path

KC = Path("/opt/data/fenjue/data/big_kcache")
FEE = 0.0015
OUT = Path("/opt/data/fenjue/data/holding_research_20260911.json")

random.seed(42)
stocks = {}
for fp in glob.glob(str(KC / "*.json")):
    ks = json.loads(open(fp).read())
    if len(ks) >= 300:
        stocks[Path(fp).stem] = ks
print(f"universe: {len(stocks)} stocks")

# 全主板等权日收益（大盘环境代理）
day_sum, day_cnt = {}, {}
for ks in stocks.values():
    for i in range(1, len(ks)):
        r = ks[i]["close"] / ks[i - 1]["close"] - 1
        day_sum[ks[i]["date"]] = day_sum.get(ks[i]["date"], 0) + r
        day_cnt[ks[i]["date"]] = day_cnt.get(ks[i]["date"], 0) + 1
mkt = {d: day_sum[d] / day_cnt[d] for d in day_sum if day_cnt[d] > 1500}


def stats(rets):
    if len(rets) < 30:
        return None
    rets = sorted(rets)
    n = len(rets)
    return {"n": n, "win%": round(sum(1 for r in rets if r > 0) / n * 100, 1),
            "mean%": round(st.mean(rets) * 100, 2), "med%": round(st.median(rets) * 100, 2),
            "p10%": round(rets[n // 10] * 100, 2), "p90%": round(rets[min(n - 1, n * 9 // 10)] * 100, 2)}


R = {}

# ── E1 大跌处置（-3%/-5%/-7% 三档）：次日开盘跑 vs 继续持有 ──
for th, tag in [(-0.03, "跌3%"), (-0.05, "跌5%"), (-0.07, "跌7%")]:
    run, hold3, hold5, hold10, hold20 = [], [], [], [], []
    for ks in stocks.values():
        for i in range(60, len(ks) - 21):
            chg = ks[i]["close"] / ks[i - 1]["close"] - 1
            if chg > th:
                continue
            c0 = ks[i]["close"]
            run.append(ks[i + 1]["open"] / c0 - 1 - FEE)
            hold3.append(ks[i + 3]["close"] / c0 - 1 - FEE)
            hold5.append(ks[i + 5]["close"] / c0 - 1 - FEE)
            hold10.append(ks[i + 10]["close"] / c0 - 1 - FEE)
            hold20.append(ks[i + 20]["close"] / c0 - 1 - FEE)
    R[f"E1_{tag}"] = {"次日开盘跑": stats(run), "持有3日": stats(hold3),
                      "持有5日": stats(hold5), "持有10日": stats(hold10), "持有20日": stats(hold20)}
    print("E1", tag, "n=", len(run))

# ── E1b 大跌×环境/结构切片 ──
def e1_slice(cond, tag):
    run, hold5 = [], []
    for ks in stocks.values():
        closes = [k["close"] for k in ks]
        vols = [k["volume"] for k in ks]
        for i in range(60, len(ks) - 6):
            chg = closes[i] / closes[i - 1] - 1
            if chg > -0.05:
                continue
            if ks[i]["date"] not in mkt:
                continue
            if not cond(ks, closes, vols, i):
                continue
            run.append(ks[i + 1]["open"] / closes[i] - 1 - FEE)
            hold5.append(closes[i + 5] / closes[i] - 1 - FEE)
    R[tag] = {"次日开盘跑": stats(run), "持有5日": stats(hold5)}
    print("E1b", tag, "n=", len(run))

e1_slice(lambda ks, c, v, i: mkt[ks[i]["date"]] > 0, "E1b_跌5%×大盘红")
e1_slice(lambda ks, c, v, i: mkt[ks[i]["date"]] <= -0.005, "E1b_跌5%×大盘跌>0.5%")
e1_slice(lambda ks, c, v, i: c[i] > sum(c[i - 60:i]) / 60, "E1b_跌5%×站上MA60")
e1_slice(lambda ks, c, v, i: c[i] <= sum(c[i - 60:i]) / 60, "E1b_跌5%×MA60下")
e1_slice(lambda ks, c, v, i: c[i] < min(c[i - 20:i]), "E1b_跌5%×破20日新低")
e1_slice(lambda ks, c, v, i: c[i] >= min(c[i - 20:i]), "E1b_跌5%×未破20日低")
e1_slice(lambda ks, c, v, i: v[i] > sum(v[i - 20:i]) / 20 * 2, "E1b_跌5%×倍量")
e1_slice(lambda ks, c, v, i: v[i] <= sum(v[i - 20:i]) / 20 * 2, "E1b_跌5%×非倍量")

# ── E2 大涨处置（+5% 未涨停 / 涨停分桶）──
for lo, hi, tag in [(0.05, 0.095, "涨5-9.5%"), (0.095, 99, "涨停(≥9.5%)")]:
    run, hold3, hold5 = [], [], []
    for ks in stocks.values():
        for i in range(60, len(ks) - 6):
            chg = ks[i]["close"] / ks[i - 1]["close"] - 1
            if not (lo <= chg < hi):
                continue
            c0 = ks[i]["close"]
            run.append(ks[i + 1]["open"] / c0 - 1 - FEE)
            hold3.append(ks[i + 3]["close"] / c0 - 1 - FEE)
            hold5.append(ks[i + 5]["close"] / c0 - 1 - FEE)
    R[f"E2_{tag}"] = {"次日开盘跑": stats(run), "持有3日": stats(hold3), "持有5日": stats(hold5)}
    print("E2", tag, "n=", len(run))

# ── E3 假突破 vs 真突破（60日新高口径）──
fake, real = [], []
for ks in stocks.values():
    closes = [k["close"] for k in ks]
    highs = [k["high"] for k in ks]
    for i in range(65, len(ks) - 6):
        hh, hc = max(highs[i - 60:i]), max(closes[i - 60:i])
        if highs[i] > hh and closes[i] < hc:      # 盘中破前高，收回线下=假突破
            fake.append(closes[i + 5] / closes[i] - 1 - FEE)
        elif closes[i] > hc:                       # 收盘站上=真突破
            real.append(closes[i + 5] / closes[i] - 1 - FEE)
R["E3_假突破_持有5日"] = stats(fake)
R["E3_真突破_持有5日"] = stats(real)
print("E3 fake/real n=", len(fake), len(real))

# ── E4 解套位（深跌≥15% 后回到 60 日前价格 ±3%）：回本跑不跑 ──
run, hold5, hold20 = [], [], []
for ks in stocks.values():
    closes = [k["close"] for k in ks]
    for i in range(80, len(ks) - 21):
        base = closes[i - 60]
        trough = min(closes[i - 59:i + 1])
        if trough / base - 1 > -0.15:                # 没深跌过
            continue
        if abs(closes[i] / base - 1) > 0.03:          # 还没回到成本区
            continue
        run.append(ks[i + 1]["open"] / closes[i] - 1 - FEE)
        hold5.append(closes[i + 5] / closes[i] - 1 - FEE)
        hold20.append(closes[i + 20] / closes[i] - 1 - FEE)
R["E4_解套位"] = {"次日开盘跑": stats(run), "持有5日": stats(hold5), "持有20日": stats(hold20)}
print("E4 n=", len(run))

# ── 随机对照（同 horizons）──
pool = []
keys = list(stocks.keys())
while len(pool) < 20000:
    ks = stocks[random.choice(keys)]
    i = random.randint(65, len(ks) - 22)
    pool.append((ks, i))
R["随机对照"] = {
    "次日开盘": stats([ks[i + 1]["open"] / ks[i]["close"] - 1 - FEE for ks, i in pool]),
    "持有5日": stats([ks[i + 5]["close"] / ks[i]["close"] - 1 - FEE for ks, i in pool]),
    "持有20日": stats([ks[i + 20]["close"] / ks[i]["close"] - 1 - FEE for ks, i in pool]),
}

OUT.write_text(json.dumps(R, ensure_ascii=False, indent=1))
print("saved", OUT)
