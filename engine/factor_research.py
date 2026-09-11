#!/usr/bin/env python3
"""engine/factor_research.py — 补充因子实证（2026-09-11 第二轮）

测联赛没覆盖的因子：换手率、MAX彩票、低价股、日历效应（星期/月份）。
口径：月度调仓因子=月末按时点值分组（最低/最高 20%），次一交易日开盘买，
持有至下月调仓开盘卖，净 -0.3% 双边；日历=全宇宙等权日收益按星期/月分组。
换手率从 cap_hist 反推：turn = volume×close_raw/cap（cap_hist 口径自带）。
"""
import json, glob, statistics as st
from pathlib import Path
from collections import defaultdict

KC = Path("/opt/data/fenjue/data/big_kcache")
CAP = Path("/opt/data/fenjue/data/cap_hist")
FEE = 0.003
OUT = Path("/opt/data/fenjue/data/factor_research_20260911.json")

caps = {Path(fp).stem: {r[0]: (r[1], r[2]) for r in json.loads(open(fp).read())}
        for fp in glob.glob(str(CAP / "*.json"))}
kcache = {}
for fp in glob.glob(str(KC / "*.json")):
    code = Path(fp).stem
    if code in caps:
        ks = json.loads(open(fp).read())
        kcache[code] = ks
print("stocks:", len(kcache))

all_dates = sorted({d for c in caps.values() for d in c})
month_end = {}
for d in all_dates:
    month_end[d[:7]] = d
me_dates = sorted(month_end.values())
day_after = {all_dates[i]: all_dates[i + 1] for i in range(len(all_dates) - 1)}

periods = []
for i in range(len(me_dates) - 1):
    e0 = day_after.get(me_dates[i])
    e1 = day_after.get(me_dates[i + 1])
    if e0 and e1:
        periods.append((me_dates[i], e0, e1))

# kcache 索引化
kmap = {c: {k["date"]: k for k in v} for c, v in kcache.items()}
# 20 日历史窗口用 kcache 原始序列
kseq = {c: v for c, v in kcache.items()}


def max20(code, d):
    """截至 d(不含) 过去20个交易日最大日涨幅"""
    seq = kseq[code]
    idx = next((j for j, k in enumerate(seq) if k["date"] == d), None)
    if idx is None or idx < 21:
        return None
    wins = seq[idx - 20:idx]
    m = -9
    for j in range(1, len(wins)):
        m = max(m, wins[j]["close"] / wins[j - 1]["close"] - 1)
    return m


def turn20(code, d):
    """截至 d(含) 近20日平均换手率%（volume×close_raw/cap 反推）"""
    seq = kseq[code]
    idx = next((j for j, k in enumerate(seq) if k["date"] == d), None)
    if idx is None or idx < 20:
        return None
    ts = []
    for k in seq[idx - 19:idx + 1]:
        dd = k["date"]
        if dd in caps[code] and caps[code][dd][1] > 0:
            close_raw = caps[code][dd][0]
            ts.append(k["volume"] * close_raw / caps[code][dd][1] / 1e6)
    return st.mean(ts) if len(ts) >= 15 else None


factor_rows = defaultdict(list)  # (factor, bucket) -> [(month, ret, uni)]
uni_month = {}
for me, e0, e1 in periods:
    entries = []
    for code in caps:
        if me not in caps[code]:
            continue
        close_raw, cap = caps[code][me]
        if not cap or cap <= 0 or not close_raw or close_raw < 2:
            continue
        km = kmap[code]
        if e0 not in km or e1 not in km:
            continue
        o0, o1 = km[e0]["open"], km[e1]["open"]
        if o0 <= 0 or o1 <= 0:
            continue
        r = o1 / o0 - 1 - FEE
        entries.append((code, r, close_raw))
    if len(entries) < 200:
        continue
    uni = st.mean([e[1] for e in entries])
    uni_month[me[:7]] = uni
    # 低价股
    by_price = sorted(entries, key=lambda x: x[2])
    n20 = max(30, len(entries) // 5)
    factor_rows[("低价股", "最低20%")].append(st.mean([e[1] for e in by_price[:n20]]) - uni)
    factor_rows[("低价股", "其余")].append(st.mean([e[1] for e in by_price[n20:]]) - uni)
    # 换手率 / MAX（计算贵，只对有数据的票）
    fvals = []
    for code, r, _ in entries:
        t20 = turn20(code, me)
        m20 = max20(code, me)
        if t20 is not None and m20 is not None:
            fvals.append((code, r, t20, m20))
    if len(fvals) < 200:
        continue
    n20 = max(30, len(fvals) // 5)
    by_t = sorted(fvals, key=lambda x: x[2])
    factor_rows[("换手率", "最低20%")].append(st.mean([e[1] for e in by_t[:n20]]) - uni)
    factor_rows[("换手率", "最高20%")].append(st.mean([e[1] for e in by_t[-n20:]]) - uni)
    by_m = sorted(fvals, key=lambda x: x[3])
    factor_rows[("MAX彩票", "最低20%")].append(st.mean([e[1] for e in by_m[:n20]]) - uni)
    factor_rows[("MAX彩票", "最高20%")].append(st.mean([e[1] for e in by_m[-n20:]]) - uni)

R = {"因子月度超额(相对全宇宙等权)": {}}
for (f, b), vals in sorted(factor_rows.items()):
    if len(vals) >= 24:
        cum = 1.0
        for v in vals:
            cum *= 1 + v
        R["因子月度超额(相对全宇宙等权)"][f"{f}-{b}"] = {
            "months": len(vals), "月均超额%": round(st.mean(vals) * 100, 2),
            "月胜率%": round(sum(1 for v in vals if v > 0) / len(vals) * 100, 1),
            "累计超额%": round((cum - 1) * 100, 1)}

# 日历效应（全宇宙等权日收益）
day_sum, day_cnt = defaultdict(float), defaultdict(int)
for code, seq in kseq.items():
    for i in range(1, len(seq)):
        if seq[i]["date"] in caps[code]:
            r = seq[i]["close"] / seq[i - 1]["close"] - 1
            day_sum[seq[i]["date"]] += r
            day_cnt[seq[i]["date"]] += 1
import datetime as dt
wd = defaultdict(list)
mo = defaultdict(list)
for d, s in day_sum.items():
    if day_cnt[d] > 1500:
        dd = dt.date.fromisoformat(d)
        wd[dd.weekday()].append(s / day_cnt[d])
        mo[dd.month].append(s / day_cnt[d])
R["日历效应-星期"] = {f"周{'一二三四五'[k]}": {"n": len(v), "日均%": round(st.mean(v) * 100, 3),
                       "胜率%": round(sum(1 for x in v if x > 0) / len(v) * 100, 1)}
                     for k, v in sorted(wd.items())}
R["日历效应-月份"] = {f"{k}月": {"n": len(v), "日均%": round(st.mean(v) * 100, 3),
                      "胜率%": round(sum(1 for x in v if x > 0) / len(v) * 100, 1)}
                    for k, v in sorted(mo.items())}

OUT.write_text(json.dumps(R, ensure_ascii=False, indent=1))
print(json.dumps(R["因子月度超额(相对全宇宙等权)"], ensure_ascii=False, indent=1))
print(json.dumps(R["日历效应-星期"], ensure_ascii=False))
print("saved", OUT)
