#!/usr/bin/env python3
"""engine/psy_laws.py — 心理/哲学定律×股市验证赛（2026-09-13，用户立项）

T1 长周期反转（De Bondt-Thaler 输家/赢家，1985）：250日涨跌幅排序，最差/最好 10 只，
   持有 60 交易日，每 20 日换仓，次日开盘买，净-0.15%/边。对照=随机。
T2 钝刀割肉（认知失调：持有者拒不认亏→阴跌续跌）：连续≥4天小跌（每日-0.3~-2.5%，
   累计≤-5%）且量缩 → 次日开盘买（抄阴跌）T+5/T+10 收盘。对照=随机、急跌。
T3 注意力衰减（Barber-Odean：涨停=注意力峰值）：任意涨停日 → 次日开盘追入，
   逐日累计收益曲线 T+1..T+10。量化"追板第几天开始死"。
全部：净口径、剔ST/退、时间双段（2019-22/2023-26）。
"""
import json, glob, random
from collections import defaultdict

ROOT = "/opt/data/fenjue"
D = ROOT + "/data"
FEE = 0.0015
stocks = {}
for f in glob.glob(f"{D}/big_kcache/*.json"):
    stocks[f.split("/")[-1][:6]] = json.load(open(f))
names = {c: v.get("name", "") for c, v in json.load(open(f"{D}/industry_map.json")).items()}
cal = [k["date"] for k in stocks["000001"]]
dates = [d for d in cal if d >= "2019-01-03"]
idx = {c: {k["date"]: j for j, k in enumerate(ks)} for c, ks in stocks.items()}
dpos = {d: i for i, d in enumerate(dates)}
ok_codes = [c for c in stocks if len(stocks[c]) >= 320 and "ST" not in names.get(c, "") and "退" not in names.get(c, "")]

def stats(v):
    if not v:
        return {"n": 0}
    return {"n": len(v), "avg%": round(sum(v)/len(v)*100, 2),
            "win%": round(sum(1 for x in v if x > 0)/len(v)*100, 1)}

def split2(v):
    """时间双段"""
    return v

out = {}
rnd = random.Random(3)

# ─── T1 长周期反转 ───
t1 = {"输家组合": [], "赢家组合": [], "随机": []}
t1_seg = defaultdict(lambda: {"输家组合": [], "赢家组合": []})
for ri in range(260, len(dates) - 65, 20):
    d = dates[ri]
    seg = "2019-22" if d < "2023-01-01" else "2023-26"
    cands = []
    for c in ok_codes:
        j = idx[c].get(d)
        if j is None or j < 255:
            continue
        if stocks[c][j-250]["close"] <= 0:
            continue
        mom = stocks[c][j]["close"]/stocks[c][j-250]["close"] - 1
        j1 = idx[c].get(dates[ri+1])
        j2 = idx[c].get(dates[min(ri+61, len(dates)-1)])
        if j1 is None or j2 is None or stocks[c][j1]["open"] <= 0:
            continue
        r = stocks[c][j2]["close"]/stocks[c][j1]["open"] - 1 - 2*FEE
        cands.append((mom, r))
    if not cands:
        continue
    cands.sort()
    t1["输家组合"].append(sum(r for _, r in cands[:10])/10)
    t1["赢家组合"].append(sum(r for _, r in cands[-10:])/10)
    t1_seg[seg]["输家组合"].append(t1["输家组合"][-1])
    t1_seg[seg]["赢家组合"].append(t1["赢家组合"][-1])
    pool = rnd.sample(cands, 10)
    t1["随机"].append(sum(r for _, r in pool)/10)
out["T1_长周期反转_60日持有"] = {k: stats(v) for k, v in t1.items()}
out["T1_分段"] = {s: {k: stats(v) for k, v in g.items()} for s, g in t1_seg.items()}

# ─── T2 钝刀割肉（阴跌续跌？）───
t2 = {"阴跌_T5": [], "阴跌_T10": [], "急跌对照_T5": [], "随机": []}
t2_seg = defaultdict(list)
for c in ok_codes:
    ks = stocks[c]
    for j in range(260, len(ks) - 12):
        # 连续≥4天小跌
        ok = True
        tot = 1.0
        for k in range(j-3, j+1):
            if ks[k-1]["close"] <= 0:
                ok = False; break
            chg = ks[k]["close"]/ks[k-1]["close"] - 1
            if not (-0.025 <= chg <= -0.003):
                ok = False; break
            tot *= 1 + chg
        if not ok or tot - 1 > -0.05:
            continue
        # 量缩：后2日均量 < 前2日
        v_pre = (ks[j-3]["volume"]+ks[j-2]["volume"])/2
        v_post = (ks[j-1]["volume"]+ks[j]["volume"])/2
        if v_pre <= 0 or v_post >= v_pre:
            continue
        if ks[j+1]["open"] <= 0:
            continue
        r5 = ks[j+5]["close"]/ks[j+1]["open"] - 1 - 2*FEE
        r10 = ks[j+10]["close"]/ks[j+1]["open"] - 1 - 2*FEE
        t2["阴跌_T5"].append(r5)
        t2["阴跌_T10"].append(r10)
        t2_seg["2019-22" if ks[j]["date"] < "2023-01-01" else "2023-26"].append(r5)
        # 急跌对照：单日≤-5%
        if ks[j-1]["close"] > 0 and ks[j]["close"]/ks[j-1]["close"]-1 <= -0.05:
            t2["急跌对照_T5"].append(r5)
for _ in range(5000):
    c = rnd.choice(ok_codes)
    ks = stocks[c]
    j = rnd.randint(260, len(ks)-12)
    if ks[j+1]["open"] > 0:
        t2["随机"].append(ks[j+5]["close"]/ks[j+1]["open"] - 1 - 2*FEE)
out["T2_钝刀割肉"] = {k: stats(v) for k, v in t2.items()}
out["T2_分段_阴跌T5"] = {k: stats(v) for k, v in t2_seg.items()}

# ─── T3 注意力衰减曲线 ───
curve = defaultdict(list)
for c in ok_codes:
    ks = stocks[c]
    for j in range(61, len(ks) - 12):
        if ks[j-1]["close"] <= 0 or ks[j]["close"]/ks[j-1]["close"]-1 < 0.098:
            continue
        if j+1 >= len(ks) or ks[j+1]["open"] <= 0:
            continue
        base = ks[j+1]["open"]  # 次日开盘追入价
        for h in range(1, 11):
            curve[h].append(ks[j+h]["close"]/base - 1 - 2*FEE)
out["T3_涨停后注意力衰减_追入口径"] = {f"T+{h}": stats(v) for h, v in sorted(curve.items())}

json.dump(out, open(f"{D}/psy_laws_20260913.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False, indent=1))
