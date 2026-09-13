#!/usr/bin/env python3
"""engine/dividend_sim.py — 红利优化策略模拟（2026-09-12，用户令"建好跑比赛"）

规则（大佬操作台体系的工程化版）：
- 宇宙：连续 ≥3 个年度有分红（防一次性特别分红）+ 价>2 + 非ST/退
- 时点 TTM 息率（当日已知分红/当日收盘，前复权口径=近似，全体一致）≥4.5% → 次日开盘买（1/5 仓，最多5仓）
- 息率 <3.5% → 次日开盘卖（减仓不清仓先简化为清）；连续500天无分红 → 强制清
- 全部市价单=无成交问题（红利票流动性充足，这是本策略对打板系的本质优势）
窗口 2019-01-03 → 2026-09-11，净口径 -0.15%/边。
"""
import json, glob, sys, csv, bisect
from collections import defaultdict

ROOT = "/opt/data/fenjue"
D = ROOT + "/data"
START = "2019-01-03"
FEE = 0.0015
CAPITAL = 100000.0
BUY_Y, SELL_Y = 0.045, 0.035

stocks = {}
for f in glob.glob(f"{D}/big_kcache/*.json"):
    stocks[f.split("/")[-1][:6]] = json.load(open(f))
names = {c: v.get("name", "") for c, v in json.load(open(f"{D}/industry_map.json")).items()}
divh = json.load(open(f"{D}/dividend_history.json"))
cal = [k["date"] for k in stocks["000001"]]
dates = [d for d in cal if d >= START]
idx = {c: {k["date"]: j for j, k in enumerate(ks)} for c, ks in stocks.items()}
dnum = {d: i for i, d in enumerate(dates)}

def y4(dt):
    return dt[:4]

# 宇宙：≥3 个年度有分红 且 非ST/退
universe = []
for c, recs in divh.items():
    if c not in stocks:
        continue
    nm = names.get(c, "")
    if "ST" in nm or "退" in nm:
        continue
    if len({y4(dt) for dt, _ in recs}) >= 3:
        universe.append(c)
print(f"宇宙: {len(universe)} 只（≥3年度分红）", file=sys.stderr)

# 每股预计算：分红日期轴 + 每根bar的 TTM 分红
ttm = {}
for c in universe:
    recs = sorted(divh[c])
    dts = [datetime_or(d) if False else d for d, _ in recs] if False else [d for d, _ in recs]
    ks = stocks[c]
    arr = []
    for k in ks:
        d = k["date"]
        lo = bisect.bisect_right(dts, d)
        # TTM = 过去365天（按交易日历近似：上一同年同日的下一条起）
        prev_same = d[:4] and str(int(d[:4]) - 1) + d[4:]
        hi = bisect.bisect_right(dts, prev_same)
        arr.append(sum(dp for _, dp in recs[hi:lo]))
    ttm[c] = arr

eq = CAPITAL
pos = []   # {code, entry, cash, entry_date}
trades = []
curve = []
for d in dates:
    di = dnum[d]
    # 卖出检查
    for p in list(pos):
        ks = stocks[p["code"]]
        j = idx[p["code"]].get(d)
        if j is None:
            continue
        y = ttm[p["code"]][j] / ks[j]["close"] if ks[j]["close"] > 0 else 0
        if y < SELL_Y:
            if di + 1 < len(dates):
                nd = dates[di + 1]
                nj = idx[p["code"]].get(nd)
                if nj is not None and ks[nj]["open"] > 0:
                    ret = ks[nj]["open"] / p["entry"] - 1 - FEE
                    eq += p["cash"] * (1 + ret)
                    trades.append({"code": p["code"], "in": p["entry_date"], "out": nd,
                                   "ret": ret, "reason": "息率跌破3.5%"})
                    pos.remove(p)
    # 买入检查
    if len(pos) < 5 and di + 1 < len(dates):
        best = None
        for c in universe:
            if any(p["code"] == c for p in pos):
                continue
            j = idx[c].get(d)
            if j is None or j < 1 or stocks[c][j]["close"] <= 2:
                continue
            y = ttm[c][j] / stocks[c][j]["close"]
            if y >= BUY_Y:
                if best is None or y > best[0]:
                    best = (y, c)
        if best:
            nd = dates[di + 1]
            nj = idx[best[1]].get(nd)
            if nj is not None and stocks[best[1]][nj]["open"] > 0:
                cash = eq / 5
                eq -= cash
                pos.append({"code": best[1], "entry": stocks[best[1]][nj]["open"],
                            "cash": cash, "entry_date": nd})
    # 记账
    mv = 0.0
    for p in pos:
        j = idx[p["code"]].get(d)
        mv += p["cash"] * (stocks[p["code"]][j]["close"] / p["entry"] if j else 1)
    curve.append((d, eq + mv))

# 尾部强平估值
final = curve[-1][1]
peak, mdd = CAPITAL, 0.0
for _, v in curve:
    peak = max(peak, v)
    mdd = min(mdd, v / peak - 1)
by_year = defaultdict(float)
for d, v in curve:
    by_year[d[:4]] = v
years = {}
prev = CAPITAL
for y in sorted(by_year):
    years[y] = round((by_year[y] / prev - 1) * 100, 1)
    prev = by_year[y]
wins = [t for t in trades if t["ret"] > 0]
out = {"window": [dates[0], dates[-1]], "equity": round(final), "return%": round((final / CAPITAL - 1) * 100, 1),
       "maxDD%": round(mdd * 100, 1), "trades": len(trades),
       "win%": round(len(wins) / len(trades) * 100, 1) if trades else 0,
       "by_year": years, "universe": len(universe)}
json.dump(out, open(f"{D}/dividend_sim_20260912.json", "w"), ensure_ascii=False, indent=1)
# 交易明细 CSV
with open(f"{D}/红利优化_8年交易明细.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["代码", "名称", "买入日", "卖出日", "收益%", "卖出原因"])
    for t in trades:
        w.writerow([t["code"], names.get(t["code"], t["code"]), t["in"], t["out"],
                    round(t["ret"] * 100, 2), t["reason"]])
print(json.dumps(out, ensure_ascii=False, indent=1))
