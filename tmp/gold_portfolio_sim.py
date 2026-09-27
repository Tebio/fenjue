"""金股组合 5 万模拟（2026-09-27 午后）：月度调仓实战形态。

规则（全机械）：每月首个交易日开盘，等权买入当月「新鲜金股」（年内首次入选），
持有 20 个交易日后开盘卖出（到期强制），费 0.15% 双边（买+卖各一）。
资金 5 万，单票上限 = 总额/5（最多 5 票，超出按代码序截断），现金闲置。
对照：同期沪深300 买入持有。
"""
import bisect
import glob
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

ROOT = "/opt/data/fenjue"
FEE = 0.0015
CAPITAL = 50000.0
MAX_POS = 5
stocks = lp.load_universe()

picks = {}
for fp in sorted(glob.glob(f"{ROOT}/data/gold_stock_cache/*.json")):
    mo = os.path.basename(fp)[:-5]
    rows = json.load(open(fp))
    if rows:
        picks[mo] = sorted({r["code"] for r in rows})
months = sorted(picks)

idx = json.load(open(f"{ROOT}/data/index_sh000001.json"))
idx_dates = [r["date"] for r in idx]
idx_close = {r["date"]: r["close"] for r in idx}

all_days = sorted(idx_dates)
seen_year = defaultdict(set)
cash = CAPITAL
positions = []  # {code, shares, sell_idx}
curve = []
trades = []
idx_start = None

for day in all_days:
    mo = day[:7]
    if not ("2020-01" <= mo <= "2022-10"):
        continue
    if idx_start is None:
        idx_start = idx_close[day]
    # 1. 到期卖出（开盘卖）
    for p in [p for p in positions if p["sell_day"] == day]:
        d = stocks[p["code"]]
        i = bisect.bisect_left(d["date"], day)
        px = d["o"][i] if i < d["n"] and d["date"][i] == day and d["o"][i] > 0 else None
        if px is None:  # 停牌顺延一天
            p["sell_day"] = all_days[all_days.index(day) + 1]
            continue
        proceeds = p["shares"] * px * (1 - FEE)
        cash += proceeds
        trades.append({"code": p["code"], "buy": p["buy_day"], "sell": day,
                       "ret": px / p["buy_px"] - 1 - 2 * FEE})
        positions.remove(p)
    # 2. 月初买入（当月名单首日）
    if mo in picks and (not curve or curve[-1][0][:7] != mo):
        fresh = [c for c in picks[mo] if c not in seen_year[mo[:4]]]
        for c in picks[mo]:
            seen_year[mo[:4]].add(c)
        for code in fresh[:MAX_POS]:
            if len(positions) >= MAX_POS:
                break
            d = stocks.get(code)
            if not d:
                continue
            i = bisect.bisect_left(d["date"], day)
            if i >= d["n"] or d["date"][i] != day or d["o"][i] <= 0:
                continue
            alloc = min(cash / max(1, MAX_POS - len(positions)), cash)
            if alloc < 1000:
                continue
            shares = int(alloc * (1 - FEE) / d["o"][i] / 100) * 100
            if shares <= 0:
                continue
            cash -= shares * d["o"][i] * (1 + FEE)
            sell_i = min(i + 20, d["n"] - 1)
            positions.append({"code": code, "shares": shares, "buy_px": d["o"][i],
                              "buy_day": day, "sell_day": d["date"][sell_i]})
    # 3. 记净值（收盘）
    mv = cash
    for p in positions:
        d = stocks[p["code"]]
        i = bisect.bisect_left(d["date"], day)
        if i < d["n"] and d["date"][i] == day:
            mv += p["shares"] * d["c"][i]
    curve.append((day, mv))

final = curve[-1][1]
ret = final / CAPITAL - 1
idx_ret = idx_close[curve[-1][0]] / idx_start - 1
wins = [t for t in trades if t["ret"] > 0]
import statistics as st
print(f"═══ 金股组合 5 万模拟（2020-01 → 2022-10，{len(trades)} 笔） ═══")
print(f"终值 {final:,.0f}（{ret * 100:+.1f}%） vs 沪深300 {idx_ret * 100:+.1f}% → 超额 {(ret - idx_ret) * 100:+.1f}pp")
print(f"交易胜率 {len(wins) / max(len(trades), 1) * 100:.0f}%（{len(wins)}/{len(trades)}），均笔 {st.mean(t['ret'] for t in trades) * 100:+.2f}%")
# 回撤
peak, mdd = CAPITAL, 0
for _, v in curve:
    peak = max(peak, v)
    mdd = min(mdd, v / peak - 1)
print(f"最大回撤 {mdd * 100:.1f}%")
# 分年
for y in ("2020", "2021", "2022"):
    ys = [v for d, v in curve if d.startswith(y)]
    if len(ys) > 2:
        print(f"  {y}: {ys[-1] / ys[0] - 1:+.1%}")
print("月度净值尾部:", [(d, round(v)) for d, v in curve[-3:]])
