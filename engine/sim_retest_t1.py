#!/usr/bin/env python3
"""engine/sim_retest_t1.py — T+1 合规重测 + 引擎对账 + 连板跌停风险（2026-09-12 用户三连问）

R2 引擎对账（同窗口 2024-08-26→2026-09-11，开盘买→次日尾盘卖，净-0.15%，剔 ST/退）：
  A. 全量 ≤-3% 信号 —— 对照框架值 +0.139%（8年48.9万笔）/晚段+0.00%
  B. 全量 ≤-9.5% 跌停接 —— 对照框架 T+1 腿 +0.26%
  C. 每日最深3只（模拟盘选法）—— 看筛选效应
R3 连板跌停风险（德明利情形）：入场日再跌停的概率/该子集收益/最大连亏/最惨单笔
Q2 答料：日收益分布（不是每天+1.9%）
"""
import json, glob
from collections import defaultdict

ROOT = "/opt/data/fenjue"
FEE = 0.0015
START = "2024-08-26"
stocks = {}
for f in glob.glob(f"{ROOT}/data/big_kcache/*.json"):
    stocks[f.split("/")[-1][:6]] = json.load(open(f))
names = {c: v.get("name", "") for c, v in json.load(open(f"{ROOT}/data/industry_map.json")).items()}
cal = [k["date"] for k in stocks["000001"]]
dates = [d for d in cal if d >= START]
dpos = {d: i for i, d in enumerate(dates)}
idx = {c: {k["date"]: j for j, k in enumerate(ks)} for c, ks in stocks.items()}

def eligible(c):
    nm = names.get(c, "")
    return "ST" not in nm and "退" not in nm

armA, armB, armC = [], [], []
relimit_trades = []  # 入场日再跌停的
for d in dates[:-2]:
    di = dpos[d]
    day_sigs = []
    for c, ks in stocks.items():
        if not eligible(c):
            continue
        j = idx[c].get(d)
        if j is None or j < 1 or ks[j - 1]["close"] <= 0:
            continue
        chg = ks[j]["close"] / ks[j - 1]["close"] - 1
        if chg > -0.03:
            continue
        # 入场日=di+1 开盘，退出=di+2 收盘（T+1 合规）
        d1, d2 = dates[di + 1], dates[di + 2]
        j1, j2 = idx[c].get(d1), idx[c].get(d2)
        if j1 is None or j2 is None:
            continue
        e1, e2 = ks[j1], ks[j2]
        if e1["open"] <= 0 or e2["close"] <= 0:
            continue
        if (e1["open"] / ks[j]["close"] - 1) <= -0.095 and (e1["high"] - e1["low"]) / e1["close"] < 0.01:
            continue  # 一字跌停买不进
        ret = e2["close"] / e1["open"] - 1 - FEE
        armA.append(ret)
        if chg <= -0.095:
            armB.append(ret)
        day_sigs.append((chg, c, ret, e1["close"] / ks[j]["close"] - 1 <= -0.095))
    day_sigs.sort()
    for chg, c, ret, again in day_sigs[:3]:
        armC.append(ret)
        if again:
            relimit_trades.append((d, c, ret))

def stats(v):
    return {"n": len(v), "avg%": round(sum(v) / len(v) * 100, 3) if v else None,
            "win%": round(sum(1 for x in v if x > 0) / len(v) * 100, 1) if v else None}

out = {"R2_对账": {
    "A_全量跌3%(期望≈+0.139/晚段≈0)": stats(armA),
    "B_全量跌停接(期望≈+0.26)": stats(armB),
    "C_每日最深3只": stats(armC)},
    "R3_连板跌停": {
        "入场日再跌停笔数": len(relimit_trades),
        "占C臂比例%": round(len(relimit_trades) / len(armC) * 100, 1) if armC else None,
        "该子集均笔%": round(sum(t[2] for t in relimit_trades) / len(relimit_trades) * 100, 2) if relimit_trades else None,
        "最惨5笔": sorted([(d, names.get(c, c), round(r * 100, 1)) for d, c, r in relimit_trades], key=lambda x: x[2])[:5],
    }}
json.dump(out, open(f"{ROOT}/data/sim_retest_t1_20260912.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False, indent=1))
