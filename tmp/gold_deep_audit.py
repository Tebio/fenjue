"""金股深挖三件套（2026-09-27 傍晚，用户令「修bug+查未来函数+深挖」）。

A. 未来函数审计核心：入场时点敏感性——券商金股名单在月内陆续发布（多在 1-10 日），
   月初入场=用了还没发布的名单（前视）。入场推迟到月内第 3/6/10/15 个交易日，edge 衰减曲线=前视含量。
B. 月内多券商同推剂量：缓存里同一票重复条目=多家券商同推（1 家/2-3 家/≥4 家）。
C. 持有期结构：T+10/20/40/60。
口径：超额 vs 沪深300 同期，费 0.15%，2020-01~2022-10 缓存段。
"""
import bisect
import collections
import glob
import json
import os
import statistics as st
import sys

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

ROOT = "/opt/data/fenjue"
FEE = 0.0015
stocks = lp.load_universe()
idx = json.load(open(f"{ROOT}/data/index_sh000001.json"))
idays = [r["date"] for r in idx]
iclose = {r["date"]: r["close"] for r in idx}

# 月内同推家数：缓存条目按 code 计数
picks_multi = {}   # mo -> {code: n_brokers}
for fp in sorted(glob.glob(f"{ROOT}/data/gold_stock_cache/*.json")):
    mo = os.path.basename(fp)[:-5]
    rows = json.load(open(fp))
    if rows:
        cnt = collections.Counter(r["code"] for r in rows)
        picks_multi[mo] = cnt
months = sorted(picks_multi)
print(f"月份 {len(months)}，含同推家数信息", flush=True)

def excess(code, day, h):
    d = stocks.get(code)
    if not d:
        return None
    i = bisect.bisect_left(d["date"], day)
    if i >= d["n"] or d["date"][i] != day or d["o"][i] <= 0 or i + h + 1 >= d["n"]:
        return None
    t = d["c"][i + h] / d["o"][i] - 1 - FEE
    i0 = bisect.bisect_left(idays, day)
    if i0 + h >= len(idays):
        return None
    ir = iclose[idays[i0 + h]] / iclose[idays[i0]] - 1
    return t - ir

# A. 入场时点：月内第 k 个交易日入场
print("\n═══ A. 未来函数审计：入场时点衰减（新鲜金股，T+20 超额） ═══", flush=True)
seen_year = collections.defaultdict(set)
timing_cells = collections.defaultdict(list)
for mo in months:
    mdays = [d for d in idays if d.startswith(mo)]
    if not mdays:
        continue
    fresh = [c for c in sorted(picks_multi[mo]) if c not in seen_year[mo[:4]]]
    for c in picks_multi[mo]:
        seen_year[mo[:4]].add(c)
    for k in (1, 3, 6, 10, 15):
        if k > len(mdays):
            continue
        for code in fresh:
            ex = excess(code, mdays[k - 1], 20)
            if ex is not None:
                timing_cells[k].append(ex)
for k in (1, 3, 6, 10, 15):
    xs = timing_cells[k]
    wr = sum(1 for x in xs if x > 0) / len(xs)
    print(f"  月内第{k:>2}交易日入: n={len(xs):>4} 超额 {wr * 100:.0f}%/{st.mean(xs) * 100:+.2f}pp")

# B. 同推家数剂量（月内第 6 交易日入场，防前视口径）
print("\n═══ B. 月内同推家数剂量（第6交易日入，T+20 超额） ═══", flush=True)
dose = collections.defaultdict(list)
for mo in months:
    mdays = [d for d in idays if d.startswith(mo)]
    if len(mdays) < 6:
        continue
    d6 = mdays[5]
    for code, nb in picks_multi[mo].items():
        ex = excess(code, d6, 20)
        if ex is None:
            continue
        b = "独家(1家)" if nb == 1 else ("2-3家" if nb <= 3 else "≥4家抱团")
        dose[b].append(ex)
for b in ("独家(1家)", "2-3家", "≥4家抱团"):
    xs = dose[b]
    if not xs:
        continue
    wr = sum(1 for x in xs if x > 0) / len(xs)
    print(f"  {b:<10} n={len(xs):>4} 超额 {wr * 100:.0f}%/{st.mean(xs) * 100:+.2f}pp")

# C. 持有期（新鲜金股，第6交易日入）
print("\n═══ C. 持有期结构（新鲜金股，第6交易日入，超额） ═══", flush=True)
seen_year = collections.defaultdict(set)
hold_cells = collections.defaultdict(list)
for mo in months:
    mdays = [d for d in idays if d.startswith(mo)]
    if len(mdays) < 6:
        continue
    d6 = mdays[5]
    fresh = [c for c in sorted(picks_multi[mo]) if c not in seen_year[mo[:4]]]
    for c in picks_multi[mo]:
        seen_year[mo[:4]].add(c)
    for code in fresh:
        for h in (10, 20, 40, 60):
            ex = excess(code, d6, h)
            if ex is not None:
                hold_cells[h].append(ex)
for h in (10, 20, 40, 60):
    xs = hold_cells[h]
    wr = sum(1 for x in xs if x > 0) / len(xs)
    print(f"  T+{h:<3}: n={len(xs):>4} {wr * 100:.0f}%/{st.mean(xs) * 100:+.2f}pp")
