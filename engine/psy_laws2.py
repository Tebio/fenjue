#!/usr/bin/env python3
"""engine/psy_laws2.py — 心理定律赛第二夜（2026-09-13，用户：没人研究过的都试试）

Z1 蔡格尼克效应（未完成事件更难忘）：当日触板未封（high≥涨停价×0.995 但收未板）
   → "未完成的涨停"次日是否修复？次日开盘买，T+1/T+5。
Z2 曝光效应（Zajonc 单纯曝光）：60日内第 N 次涨停的表现——名字越熟越有人接？
   分组：60日内首见 / 第2次 / 第3+次，收盘→T+1。
Z3 峰终定律（Kahneman：记忆=峰值+结尾）：20日内有涨停（峰）+ 最近3天小阴小阳（平终）
   → 被记住的赢家回调后有人接？次日开盘买 T+5。
Z4 板块回锅肉（可得性偏差）：板块冷却≥10天后再次爆发（≥3涨停）的首板票 vs
   板块热中续爆的首板票。散户对"回过锅的题材"有现成记忆。
Z5 初生牛犊（无套牢盘）：上市不足250交易日的首板 vs 老票首板。
全部：净-0.15%、剔ST/退、随机对照、时间双段。
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
ind_map = json.load(open(f"{D}/industry_map.json"))
ok_codes = [c for c in stocks if len(stocks[c]) >= 320 and "ST" not in names.get(c, "") and "退" not in names.get(c, "")]

def stats(v):
    if not v:
        return {"n": 0}
    return {"n": len(v), "avg%": round(sum(v)/len(v)*100, 2),
            "win%": round(sum(1 for x in v if x > 0)/len(v)*100, 1)}

def limit_px(pc):
    return round(pc * 1.1, 2)

def board(ks, j):
    return ks[j-1]["close"] > 0 and ks[j]["close"]/ks[j-1]["close"]-1 >= 0.098

out = {}
rnd = random.Random(5)

# ─── Z1 蔡格尼克：触板未封 ───
z1, z1_seg = defaultdict(list), defaultdict(list)
for c in ok_codes:
    ks = stocks[c]
    for j in range(61, len(ks)-6):
        pc = ks[j-1]["close"]
        if pc <= 0:
            continue
        lp = limit_px(pc)
        touched = ks[j]["high"] >= lp * 0.995
        closed_board = ks[j]["close"]/pc - 1 >= 0.098
        if touched and not closed_board and ks[j]["close"]/pc - 1 > 0.03:  # 摸过板没收板，且没崩（>+3%）
            if ks[j+1]["open"] > 0:
                z1["T+1"].append(ks[j+1]["close"]/ks[j+1]["open"] - 1 - 2*FEE)
                z1["T+5"].append(ks[j+5]["close"]/ks[j+1]["open"] - 1 - 2*FEE)
                z1_seg["2019-22" if ks[j]["date"] < "2023" else "2023-26"].append(z1["T+1"][-1])
pool = []
for _ in range(5000):
    c = rnd.choice(ok_codes); ks = stocks[c]
    j = rnd.randint(61, len(ks)-6)
    if ks[j+1]["open"] > 0:
        pool.append(ks[j+1]["close"]/ks[j+1]["open"] - 1 - 2*FEE)
out["Z1_蔡格尼克_触板未封"] = {**{k: stats(v) for k, v in z1.items()}, "随机": stats(pool),
                                "分段T1": {k: stats(v) for k, v in z1_seg.items()}}

# ─── Z2 曝光效应：第N次涨停 ───
z2 = defaultdict(list)
for c in ok_codes:
    ks = stocks[c]
    boards60 = 0
    for j in range(61, len(ks)-2):
        if board(ks, j):
            key = "60日首见" if boards60 == 0 else ("第2次" if boards60 == 1 else "第3次+")
            if ks[j+1]["open"] > 0:
                z2[key].append(ks[j+1]["close"]/ks[j]["close"] - 1 - FEE)  # 收盘上车口径
        # 滚动60日窗口维护
        if j >= 121 and board(ks, j-60):
            boards60 -= 1
        if board(ks, j):
            boards60 += 1
out["Z2_曝光效应_第N次涨停_T1"] = {k: stats(v) for k, v in z2.items()}

# ─── Z3 峰终定律 ───
z3, z3_seg = [], defaultdict(list)
for c in ok_codes:
    ks = stocks[c]
    for j in range(61, len(ks)-6):
        if ks[j+1]["open"] <= 0:
            continue
        peak = any(board(ks, k) for k in range(j-20, j-2))   # 峰：20日内有板（3天前以前）
        calm_end = all(ks[k-1]["close"] > 0 and abs(ks[k]["close"]/ks[k-1]["close"]-1) < 0.02
                       for k in range(j-2, j+1))              # 终：最近3天平静
        today_not_board = not board(ks, j)
        if peak and calm_end and today_not_board:
            r = ks[j+5]["close"]/ks[j+1]["open"] - 1 - 2*FEE
            z3.append(r)
            z3_seg["2019-22" if ks[j]["date"] < "2023" else "2023-26"].append(r)
pool3 = []
for _ in range(5000):
    c = rnd.choice(ok_codes); ks = stocks[c]
    j = rnd.randint(61, len(ks)-6)
    if ks[j+1]["open"] > 0:
        pool3.append(ks[j+5]["close"]/ks[j+1]["open"] - 1 - 2*FEE)
out["Z3_峰终定律_T5"] = {"峰终组": stats(z3), "随机": stats(pool3),
                          "分段": {k: stats(v) for k, v in z3_seg.items()}}

# ─── Z4 板块回锅肉 ───
# 行业日历：每日各行业涨停数
ind_day = defaultdict(lambda: defaultdict(int))
for c in ok_codes:
    ks = stocks[c]
    industry = ind_map.get(c, {}).get("industry") or "?"
    for j in range(61, len(ks)):
        if board(ks, j):
            ind_day[ks[j]["date"]][industry] += 1
z4 = defaultdict(list)
for c in ok_codes:
    ks = stocks[c]
    industry = ind_map.get(c, {}).get("industry") or "?"
    for j in range(61, len(ks)-2):
        if not board(ks, j) or ks[j+1]["open"] <= 0:
            continue
        d = ks[j]["date"]
        if ind_day[d].get(industry, 0) < 3:
            continue  # 梯队成型才算板块爆发
        hot_recently = any(ind_day[ks[k]["date"]].get(industry, 0) >= 3 for k in range(j-10, j))
        r = ks[j+1]["close"]/ks[j]["close"] - 1 - FEE
        z4["热中续爆" if hot_recently else "冷却后回锅"].append(r)
out["Z4_板块回锅肉_T1"] = {k: stats(v) for k, v in z4.items()}

# ─── Z5 初生牛犊：次新首板 ───
z5 = defaultdict(list)
for c in ok_codes:
    ks = stocks[c]
    for j in range(61, len(ks)-2):
        if board(ks, j) and ks[j+1]["open"] > 0:
            first60 = all(not board(ks, k) for k in range(max(1, j-60), j))
            if first60:
                z5["次新(<250交易日)" if j < 250 else "老票"].append(ks[j+1]["close"]/ks[j]["close"] - 1 - FEE)
out["Z5_初生牛犊_首板T1"] = {k: stats(v) for k, v in z5.items()}

json.dump(out, open(f"{D}/psy_laws2_20260913.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False, indent=1))
