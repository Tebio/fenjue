"""指标普查 v2（内存安全两遍法）：第一遍只收集指标值定五分位边界，第二遍重算并按桶累加。
指标同 v1：量比5/今昨量比/放量倍数/成交额异动/换手率/RSI6/KDJ-K/MACD金死叉/MACD柱向/ATR%/MA5。
"""
import bisect
import collections
import glob as _g
import json
import statistics as st
import sys

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

ROOT = "/opt/data/fenjue"
FEE = 0.0015
stocks = lp.load_universe()

turn = {}
for fp in _g.glob(f"{ROOT}/data/cap_hist/*.json"):
    code = fp.rsplit("/", 1)[-1][:-5]
    try:
        turn[code] = {r[0]: r[1] for r in rows} if (rows := json.load(open(fp))) else {}
    except Exception:
        pass

def ema_series(c, n):
    k = 2 / (n + 1)
    out = [c[0]]
    for x in c[1:]:
        out.append(out[-1] + k * (x - out[-1]))
    return out

def indicators(d, i, tmap):
    """返回 {ind: value} 或 None"""
    c, o, h, l, v, amt = d["c"], d["o"], d["h"], d["l"], d["v"], d.get("amt") or [0] * d["n"]
    if c[i - 1] <= 0 or o[i] <= 0 or v[i] <= 0:
        return None
    out = {}
    v5 = [x for x in v[i - 5:i] if x > 0]
    v20 = [x for x in v[i - 20:i] if x > 0]
    if v5:
        out["量比5"] = v[i] / (sum(v5) / len(v5))
    if v[i - 1] > 0:
        out["今昨量比"] = v[i] / v[i - 1]
    if v20:
        out["放量倍数"] = v[i] / (sum(v20) / len(v20))
    a20 = [x for x in amt[i - 20:i] if x > 0]
    if a20 and amt[i] > 0:
        out["成交额异动"] = amt[i] / (sum(a20) / len(a20))
    tr = tmap.get(d["date"][i])
    if tr:
        out["换手率"] = tr
    g = sum(max(c[j] - c[j - 1], 0) for j in range(i - 5, i + 1))
    ll = sum(max(c[j - 1] - c[j], 0) for j in range(i - 5, i + 1))
    out["RSI6"] = 100 if ll == 0 else 100 - 100 / (1 + g / ll)
    k_ = 50.0
    for j in range(i - 8, i + 1):
        lo = min(l[max(0, j - 8):j + 1]); hi = max(h[max(0, j - 8):j + 1])
        rsv = (c[j] - lo) / (hi - lo) * 100 if hi > lo else 50
        k_ = k_ * 2 / 3 + rsv / 3
    out["KDJ-K"] = k_
    seg = c[max(0, i - 120):i + 1]
    e12, e26 = ema_series(seg, 12), ema_series(seg, 26)
    difs = [a - b for a, b in zip(e12[-16:], e26[-16:])]
    dif, dea = difs[-1], sum(difs[-9:]) / 9
    out["MACD金死叉"] = 1 if dif > dea else 0
    out["MACD柱向"] = 1 if (dif - dea) > (difs[-2] - sum(difs[-10:-1]) / 9) else 0
    trs = [max(h[j] - l[j], abs(h[j] - c[j - 1]), abs(l[j] - c[j - 1])) for j in range(i - 14, i)]
    out["ATR%"] = sum(trs) / 14 / c[i - 1]
    out["MA5"] = 1 if c[i] > sum(c[i - 5:i]) / 5 else 0
    return out

# ── 第一遍：收集指标值（抽样每 3 个 bar 取 1，边界估计足够） ──
vals = collections.defaultdict(list)
print("第一遍：指标值采样…", flush=True)
for code, d in stocks.items():
    if code[:2] not in ("60", "00") or d["n"] < 300:
        continue
    tmap = turn.get(code, {})
    for i in range(65, d["n"] - 21, 3):
        if d["date"][i] < "2019-07-01":
            continue
        ind = indicators(d, i, tmap)
        if ind:
            for k, x in ind.items():
                vals[k].append(x)
bounds = {}
for k, xs in vals.items():
    xs.sort()
    n = len(xs)
    bounds[k] = [xs[int(n * q)] for q in (0.2, 0.4, 0.6, 0.8)]
    print(f"  {k}: n={n} 边界 {[round(b, 2) for b in bounds[k]]}", flush=True)
del vals

# ── 第二遍：按边界入桶累加 ──
agg = collections.defaultdict(lambda: collections.defaultdict(lambda: [0, 0.0, 0.0, 0, 0]))  # ind -> bucket -> [n, t5sum, t20sum, w5, w20]
print("第二遍：全量入桶…", flush=True)
for code, d in stocks.items():
    if code[:2] not in ("60", "00") or d["n"] < 300:
        continue
    c, o = d["c"], d["o"]
    tmap = turn.get(code, {})
    for i in range(65, d["n"] - 21):
        if d["date"][i] < "2019-07-01" or o[i] <= 0:
            continue
        ind = indicators(d, i, tmap)
        if not ind:
            continue
        # 2026-09-27 修正：指标用 i 日收盘数据 → 入场必须是次日开盘 o[i+1]（v1 用 o[i] 同开=前视）
        if o[i + 1] <= 0:
            continue
        t5 = c[i + 5] / o[i + 1] - 1 - FEE
        t20 = c[i + 20] / o[i + 1] - 1 - FEE
        for k, x in ind.items():
            if k in ("MACD金死叉", "MACD柱向", "MA5"):
                b = "强" if x == 1 else "弱"
            else:
                bs = bounds[k]
                b = "Q1" if x <= bs[0] else "Q2" if x <= bs[1] else "Q3" if x <= bs[2] else "Q4" if x <= bs[3] else "Q5"
            a = agg[k][b]
            a[0] += 1; a[1] += t5; a[2] += t20; a[3] += t5 > 0; a[4] += t20 > 0

print("\n═══ 指标普查（全市场全量入桶，今开入，费0.15%） ═══")
report = {}
for k in ("量比5", "今昨量比", "放量倍数", "成交额异动", "换手率", "RSI6", "KDJ-K", "MACD金死叉", "MACD柱向", "ATR%", "MA5"):
    if k not in agg:
        continue
    print(f"\n── {k} ──")
    report[k] = {}
    order = ("弱", "强") if k in ("MACD金死叉", "MACD柱向", "MA5") else ("Q1", "Q2", "Q3", "Q4", "Q5")
    for b in order:
        a = agg[k].get(b)
        if not a or not a[0]:
            continue
        n, s5, s20, w5, w20 = a
        rng = "" if b in ("弱", "强") else f"[{bounds[k][order.index(b) - 1] if order.index(b) > 0 else float('-inf'):.2f}~{(bounds[k] + [float('inf')])[order.index(b)]:.2f}]"
        print(f"  {b} {rng}: n={n} T5 {w5 / n * 100:.0f}%/{s5 / n * 100:+.2f}% | T20 {w20 / n * 100:.0f}%/{s20 / n * 100:+.2f}%")
        report[k][b] = {"n": n, "t5": round(s5 / n, 4), "t20": round(s20 / n, 4), "wr20": round(w20 / n, 3)}
json.dump({"bounds": {k: v for k, v in bounds.items()}, "cells": report},
          open(f"{ROOT}/data/indicator_census_20260927.json", "w"), ensure_ascii=False, indent=1)
print("\nsaved")
