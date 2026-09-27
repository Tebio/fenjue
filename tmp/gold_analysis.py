"""金股分析（纯离线，2026-09-27 上午）：吃 33 个月缓存（2020-01~2022-10），不碰配额。

A. 金股回测：月度名单→次交易日开盘买，T+20/T+60，超额 vs 沪深300；新鲜金股（年内首次入选）vs 抱团金股。
B. 金股×坟场赢家交叉：2020-01~2022-10 区间内坟场事件（三连阴/次新超跌/巨量三连阴），
   当月金股名单覆盖的票 vs 未覆盖的票，胜率/收益对比——回答「赢家是不是金股效应」。
"""
import bisect
import glob
import json
import os
import statistics as st
import sys
from collections import defaultdict

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

ROOT = "/opt/data/fenjue"
FEE = 0.0015
stocks = lp.load_universe()

picks = {}
for fp in sorted(glob.glob(f"{ROOT}/data/gold_stock_cache/*.json")):
    mo = os.path.basename(fp)[:-5]
    rows = json.load(open(fp))
    if rows:
        picks[mo] = {r["code"]: r.get("name", "") for r in rows}
months = sorted(picks)
print(f"有效月份 {len(months)}: {months[0]} → {months[-1]}，总入选 {sum(len(v) for v in picks.values())} 条", flush=True)

# 指数对照
idx = json.load(open(f"{ROOT}/data/index_sh000001.json"))
idx_dates = [r["date"] for r in idx]
idx_close = {r["date"]: r["close"] for r in idx}

def idx_ret(d0, d1):
    if d0 in idx_close and d1 in idx_close and idx_close[d0] > 0:
        return idx_close[d1] / idx_close[d0] - 1
    return None

# A. 金股回测：每月名单→该月首个交易日后的次日开盘买
all_days = sorted(set().union(*[set(d["date"]) for d in stocks.values()]))
recs = []
seen_year = defaultdict(set)  # year -> codes already picked
for mo in months:
    y = mo[:4]
    month_days = [d for d in all_days if d.startswith(mo)]
    if not month_days:
        continue
    d0 = month_days[0]
    for code in picks[mo]:
        fresh = code not in seen_year[y]
        seen_year[y].add(code)
        d = stocks.get(code)
        if not d:
            continue
        i = bisect.bisect_left(d["date"], d0)
        if i >= d["n"] or i + 21 >= d["n"] or d["o"][i] <= 0:
            continue
        sig_day = d["date"][i]  # 当月第一个有行情的交易日
        entry = d["o"][i]
        t20 = d["c"][i + 20] / entry - 1 - FEE
        t60 = d["c"][i + 60] / entry - 1 - FEE if i + 61 < d["n"] else None
        # 超额 vs 指数（同期）
        i0 = bisect.bisect_left(idx_dates, sig_day)
        if i0 < len(idx_dates) and i0 + 20 < len(idx_dates):
            ir = idx_close[idx_dates[i0 + 20]] / idx_close[idx_dates[i0]] - 1
            ex20 = t20 - ir
        else:
            ex20 = None
        recs.append({"mo": mo, "code": code, "fresh": fresh, "t20": t20, "t60": t60, "ex20": ex20})

print(f"金股事件 {len(recs)}")
def blk(rows, lb):
    rows = [r for r in rows if r["ex20"] is not None]
    if len(rows) < 30:
        print(f"  {lb}: n={len(rows)} 不足"); return
    xs = [r["t20"] for r in rows]; xe = [r["ex20"] for r in rows]
    print(f"  {lb:<16} n={len(rows):>5} | T20 {sum(1 for x in xs if x>0)/len(xs)*100:.0f}%/{st.mean(xs)*100:+.2f}% | 超额 {sum(1 for x in xe if x>0)/len(xe)*100:.0f}%/{st.mean(xe)*100:+.2f}pp")
blk(recs, "全部金股")
blk([r for r in recs if r["fresh"]], "新鲜金股(年内首入)")
blk([r for r in recs if not r["fresh"]], "抱团金股(重复入选)")
# 分年
for y in ("2020", "2021", "2022"):
    blk([r for r in recs if r["mo"].startswith(y)], f"{y}年")

# B. 金股×坟场赢家交叉
ev = json.load(open(f"{ROOT}/data/graveyard_autopsy_20260926.json"))
print("\n═══ 金股覆盖×坟场策略（2020-01~2022-10 区间） ═══")
mo_set = set(months)
for key, lb in (("three_down", "三连阴"), ("vol3down", "巨量三连阴"), ("newstock_dip", "次新超跌"), ("lightning", "高位避雷针")):
    cov, unc = [], []
    for r in ev[key]:
        mo = r["date"][:7]
        if mo not in mo_set:
            continue
        (cov if r["code"] in picks[mo] else unc).append(r["t20"])
    if len(cov) < 30:
        print(f"  {lb}: 金股覆盖 n={len(cov)} 不足"); continue
    for xs, tag in ((cov, "当月金股"), (unc, "非金股")):
        print(f"  {lb:<8} {tag}: n={len(xs):>6} T20 {sum(1 for x in xs if x>0)/len(xs)*100:.0f}%/{st.mean(xs)*100:+.2f}%")
json.dump(recs, open(f"{ROOT}/data/gold_backtest_partial_20260927.json", "w"), ensure_ascii=False)
print("\nsaved")
