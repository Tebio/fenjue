"""金股三挖（2026-09-27 傍晚）：剔除效应 / 环境门交叉 / 回踩入场。

A. 剔除效应：上月在名单、本月不在 → 本月 T+20 表现（被券商抛弃的票会不会补跌）
B. 金股×杠杆门：去杠杆/中段/加杠杆期的金股超额
C. 金股回踩入场：名单内票在月内跌≥5% 的交易日买入 vs 第6日无条件买入
口径：T+20 超额 vs 300，费 0.15%，缓存段 2020-01~2022-10。
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

picks = {}
for fp in sorted(glob.glob(f"{ROOT}/data/gold_stock_cache/*.json")):
    mo = os.path.basename(fp)[:-5]
    rows = json.load(open(fp))
    if rows:
        picks[mo] = {r["code"] for r in rows}
months = sorted(picks)

margin = json.load(open(f"{ROOT}/data/margin_history.json"))
mrec = {str(r.get("date"))[:10]: float(r.get("rzye") or r.get("RZYE") or 0) for r in margin} if isinstance(margin, list) else margin
mdays = sorted(mrec)
def margin_gate(day):
    i = bisect.bisect_left(mdays, day)
    if i < 20 or i >= len(mdays):
        return None
    base = mrec[mdays[i - 20]]
    if base <= 0:
        return None
    chg = mrec[mdays[i]] / base - 1
    return "去杠杆" if chg < -0.03 else ("加杠杆" if chg > 0.073 else "中段")

def excess_at(code, day, h=20):
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
    return t - (iclose[idays[i0 + h]] / iclose[idays[i0]] - 1)

# A. 剔除效应
print("═══ A. 剔除效应（上月在榜本月出榜 → 本月 T+20 超额） ═══", flush=True)
dropped, stayed = [], []
for k in range(1, len(months)):
    prev, cur = picks[months[k - 1]], picks[months[k]]
    mdays_ = [d for d in idays if d.startswith(months[k])]
    if not mdays_:
        continue
    d6 = mdays_[5] if len(mdays_) >= 6 else mdays_[-1]
    for code in prev:
        ex = excess_at(code, d6)
        if ex is None:
            continue
        (stayed if code in cur else dropped).append(ex)
for lb, xs in (("被剔除", dropped), ("留榜", stayed)):
    wr = sum(1 for x in xs if x > 0) / len(xs)
    print(f"  {lb}: n={len(xs):>4} 超额 {wr * 100:.0f}%/{st.mean(xs) * 100:+.2f}pp")

# B. 金股×杠杆门（第6日入，全部金股）
print("\n═══ B. 金股 × 杠杆门 ═══", flush=True)
cells = collections.defaultdict(list)
for mo in months:
    mdays_ = [d for d in idays if d.startswith(mo)]
    if len(mdays_) < 6:
        continue
    d6 = mdays_[5]
    g = margin_gate(d6)
    if not g:
        continue
    for code in picks[mo]:
        ex = excess_at(code, d6)
        if ex is not None:
            cells[g].append(ex)
for g in ("去杠杆", "中段", "加杠杆"):
    xs = cells.get(g, [])
    if not xs:
        continue
    wr = sum(1 for x in xs if x > 0) / len(xs)
    print(f"  {g}: n={len(xs):>4} 超额 {wr * 100:.0f}%/{st.mean(xs) * 100:+.2f}pp")

# C. 回踩入场：名单内票月内任一日跌≥3%（相对第6日入场价）时买 vs 第6日直接买
print("\n═══ C. 金股回踩入场（名单内票第6日后跌≥3%时买） ═══", flush=True)
dip_buy, flat_buy = [], []
for mo in months:
    mdays_ = [d for d in idays if d.startswith(mo)]
    if len(mdays_) < 6:
        continue
    d6 = mdays_[5]
    for code in picks[mo]:
        d = stocks.get(code)
        if not d:
            continue
        i6 = bisect.bisect_left(d["date"], d6)
        if i6 >= d["n"] or d["date"][i6] != d6 or d["o"][i6] <= 0:
            continue
        ex_flat = excess_at(code, d6)
        if ex_flat is not None:
            flat_buy.append(ex_flat)
        # 找月内（第6日后10日内）回踩≥3%的日子
        base = d["c"][i6]
        for j in range(i6 + 1, min(i6 + 11, d["n"] - 21)):
            if d["c"][j] / base - 1 <= -0.03 and d["o"][j] > 0:
                ex = excess_at(code, d["date"][j])
                if ex is not None:
                    dip_buy.append(ex)
                break
for lb, xs in (("回踩≥3%买", dip_buy), ("第6日直接买", flat_buy)):
    if not xs:
        continue
    wr = sum(1 for x in xs if x > 0) / len(xs)
    print(f"  {lb:<12}: n={len(xs):>4} 超额 {wr * 100:.0f}%/{st.mean(xs) * 100:+.2f}pp")
