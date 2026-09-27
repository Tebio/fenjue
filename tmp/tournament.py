"""策略锦标赛（2026-09-27，用户点名「跑比赛」）：同一 5 万本金、同一仓位规则、各线独立对打。

统一规则：每条线独立 5 万；事件触发 → 次交易日入场（批/事件的均值收益直接作用于仓位）；
单仓 1 万（5 仓上限），现金不足排队跳过；费已含在各线的收益口径里。
赛道：
  深档（T+10，65批）/ 摇篮（T+20，522件）/ X3（T+5或-12%止损，41批）/ 金股组合（T+20，限2020-01~2022-10段）
  / 转债低价线（≤105 买，T+120）
对照：沪深300 同期买入持有。
"""
import bisect
import collections
import json
import statistics as st
import sys

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

ROOT = "/opt/data/fenjue"
stocks = lp.load_universe()
idx = json.load(open(f"{ROOT}/data/index_sh000001.json"))
idays = [r["date"] for r in idx]
iclose = {r["date"]: r["close"] for r in idx}

def next_day(d):
    i = bisect.bisect_right(idays, d)
    return idays[i] if i < len(idays) else None

def sim(events, horizon, name, start="2019-07-01", end="2026-09-24"):
    """events: [(date, ret)]，ret=该事件持有 horizon 天的净收益。单仓1万×5槽。"""
    cash, positions, curve, taken, skipped = 50000.0, [], [], 0, 0
    ev_by_day = collections.defaultdict(list)
    for dt, r in events:
        if start <= dt <= end:
            ev_by_day[dt].append(r)
    for day in idays:
        if day < start or day > end:
            continue
        # 到期平仓
        for p in [p for p in positions if p["exit"] <= day]:
            cash += p["amt"] * (1 + p["ret"])
            positions.remove(p)
        # 今日事件入场（次日开盘近似=今日入场记账，horizon 后平仓）
        for r in ev_by_day.get(day, []):
            if len(positions) >= 5 or cash < 10000:
                skipped += 1
                continue
            ex = next_day(day + "0")  # dummy
            # 出场日=入场日后 horizon 个交易日
            i = bisect.bisect_left(idays, day)
            exit_day = idays[min(i + horizon, len(idays) - 1)]
            positions.append({"amt": 10000.0, "ret": r, "exit": exit_day})
            cash -= 10000.0
            taken += 1
        mv = cash + sum(p["amt"] for p in positions)
        curve.append((day, mv))
    # 尾盘强平
    final = cash + sum(p["amt"] * (1 + p["ret"]) for p in positions)
    peak, mdd = 50000.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    ret = final / 50000 - 1
    i0 = bisect.bisect_left(idays, start)
    i1 = bisect.bisect_left(idays, end)
    idx_ret = iclose[idays[i1]] / iclose[idays[i0]] - 1
    yrs = (i1 - i0) / 244
    print(f"  {name:<14} 终值 {final:>9,.0f}（{ret * 100:+.0f}%）| 年化 {(1 + ret) ** (1 / yrs) - 1:+.1%} | 回撤 {mdd * 100:.0f}% | 成交 {taken} 跳仓 {skipped} | 同期300 {idx_ret * 100:+.0f}%")
    return curve

# 深档批
deep = [(b["date"], b["r10"]) for b in json.load(open(f"{ROOT}/data/deep_batches_full_20260927.json"))]
# 摇篮
cradle = [(e["date"], e["t20"]) for e in json.load(open(f"{ROOT}/data/cradle_horizon_20260927.json"))]
# X3
x3 = [(b["date"], b["r"]) for b in json.load(open(f"{ROOT}/data/x3_batches_margin_20260927.json"))]
# 转债低价线：≤105 首穿事件（cb_klines）
cb_events = []
cb = json.load(open(f"{ROOT}/data/cb_klines.json"))
for code, ks in (cb.items() if isinstance(cb, dict) else []):
    for i in range(1, len(ks) - 120):
        c0, c1 = ks[i - 1].get("close"), ks[i].get("close")
        if c0 and c1 and c0 > 105 >= c1 and c1 > 80:  # 首穿105（剔违约深渊债）
            r = ks[i + 120]["close"] / c1 - 1 - 0.0015
            cb_events.append((ks[i]["date"], r))
print(f"转债低价事件 {len(cb_events)}")

print("\n═══ 锦标赛 · 全史段（2019-07→2026-09，金股除外） ═══")
sim(deep, 10, "深档低位v2")
sim(cradle, 20, "妖股摇篮")
sim(x3, 5, "X3恐慌狙击")
sim(cb_events, 120, "转债低价线")

print("\n═══ 锦标赛 · 金股可比段（2020-01→2022-10） ═══")
# 金股事件重建（新鲜金股，月度）
import glob, os
from collections import defaultdict
picks = {}
for fp in sorted(glob.glob(f"{ROOT}/data/gold_stock_cache/*.json")):
    mo = os.path.basename(fp)[:-5]
    rows = json.load(open(fp))
    if rows:
        picks[mo] = sorted({r["code"] for r in rows})
seen = defaultdict(set)
gold_events = []
for mo in sorted(picks):
    month_days = [d for d in idays if d.startswith(mo)]
    if not month_days:
        continue
    d0 = month_days[0]
    for code in picks[mo]:
        if code in seen[mo[:4]]:
            continue
        seen[mo[:4]].add(code)
        d = stocks.get(code)
        if not d:
            continue
        i = bisect.bisect_left(d["date"], d0)
        if i < d["n"] and i + 21 < d["n"] and d["o"][i] > 0:
            gold_events.append((d["date"][i], d["c"][i + 20] / d["o"][i] - 1 - 0.0015))
sim(gold_events, 20, "金股组合", start="2020-01-01", end="2022-10-31")
sim(deep, 10, "深档低位v2", start="2020-01-01", end="2022-10-31")
sim(cradle, 20, "妖股摇篮", start="2020-01-01", end="2022-10-31")
sim(x3, 5, "X3恐慌狙击", start="2020-01-01", end="2022-10-31")
sim(cb_events, 120, "转债低价线", start="2020-01-01", end="2022-10-31")
