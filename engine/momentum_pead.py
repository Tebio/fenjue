#!/usr/bin/env python3
"""engine/momentum_pead.py — 动量双测（2026-09-13，用户：动量效应选票+未测过的高胜率组合）

Study A 价格动量变体赛（8年，每20交易日换仓，top10等权，次日开盘买，净-0.15%/边）：
  M1 20日动量 / M2 20日动量剔期间涨停（干净趋势）/ M3 60日动量 /
  M4 20日动量+MA60上+缩量（安静趋势）/ M5 20日反转（最差10只）/ RND 随机对照
Study B 业绩动量 PEAD（博主类比的真身——业绩惯性）：
  大幅预增（预增且下限≥50%）/扭亏 公告→次日开盘买，T+5/20/60 收盘卖；
  对照=预减/首亏（负面）+随机股票日；加分层：一年内首次预增 vs 连续预增（≥2次/400天）。
T+1 合规（次日开盘买）。无未来函数（NOTICE_DATE 当日盘后可知）。
"""
import json, glob, random, datetime
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

def stats(v):
    if not v:
        return {"n": 0}
    return {"n": len(v), "avg%": round(sum(v) / len(v) * 100, 2),
            "win%": round(sum(1 for x in v if x > 0) / len(v) * 100, 1)}

# ─── Study A：价格动量 ───
out = {"A_price_momentum": {}}
rebal_days = [i for i in range(60, len(dates) - 22, 20)]
rnd = random.Random(11)
all_rets = {k: [] for k in ("M1", "M2", "M3", "M4", "M5", "RND")}
for ri in rebal_days:
    d = dates[ri]
    cands = []
    for c, ks in stocks.items():
        j = idx[c].get(d)
        if j is None or j < 65 or j + 1 >= len(ks):
            continue
        pc60, pc20 = ks[j - 60]["close"], ks[j - 20]["close"]
        if pc60 <= 0 or pc20 <= 0 or ks[j]["close"] <= 2:
            continue
        nm = names.get(c, "")
        if "ST" in nm or "退" in nm:
            continue
        mom20 = ks[j]["close"] / pc20 - 1
        mom60 = ks[j]["close"] / pc60 - 1
        had_board = any(ks[k - 1]["close"] > 0 and ks[k]["close"] / ks[k - 1]["close"] - 1 >= 0.098
                        for k in range(j - 20, j + 1))
        m60 = sum(ks[k]["close"] for k in range(j - 59, j + 1)) / 60
        vol5 = sum(ks[k]["volume"] for k in range(j - 5, j)) / 5
        vol20 = sum(ks[k]["volume"] for k in range(j - 20, j)) / 20
        # 入场：次日开盘；出场：20交易日后收盘
        j1 = idx[c].get(dates[ri + 1])
        j2 = idx[c].get(dates[min(ri + 21, len(dates) - 1)])
        if j1 is None or j2 is None or ks[j1]["open"] <= 0:
            continue
        ret = ks[j2]["close"] / ks[j1]["open"] - 1 - 2 * FEE
        cands.append({"c": c, "mom20": mom20, "mom60": mom60, "had_board": had_board,
                      "above": ks[j]["close"] > m60, "quiet": vol5 < vol20, "ret": ret})
    if not cands:
        continue
    by20 = sorted(cands, key=lambda x: -x["mom20"])
    by60 = sorted(cands, key=lambda x: -x["mom60"])
    all_rets["M1"].append(sum(x["ret"] for x in by20[:10]) / 10)
    clean = [x for x in by20 if not x["had_board"]]
    all_rets["M2"].append(sum(x["ret"] for x in clean[:10]) / max(1, len(clean[:10])))
    all_rets["M3"].append(sum(x["ret"] for x in by60[:10]) / 10)
    quiet = [x for x in by20 if x["above"] and x["quiet"]]
    all_rets["M4"].append(sum(x["ret"] for x in quiet[:10]) / max(1, len(quiet[:10])))
    all_rets["M5"].append(sum(x["ret"] for x in by20[-10:]) / 10)
    pool = rnd.sample(cands, min(10, len(cands)))
    all_rets["RND"].append(sum(x["ret"] for x in pool) / len(pool))
for k, v in all_rets.items():
    out["A_price_momentum"][k] = stats(v)

# ─── Study B：PEAD 业绩动量 ───
events = json.load(open(f"{D}/pead_events.json"))
cut = datetime.date(2019, 1, 3)
by_code = defaultdict(list)
for e in events:
    c = e["SECURITY_CODE"]
    nd = (e.get("NOTICE_DATE") or "")[:10]
    if nd >= "2019-01-03" and c in stocks:
        by_code[c].append(e)

def first_trade_on_or_after(c, d):
    ks = stocks[c]
    j = idx[c].get(d)
    if j is not None:
        return j
    # 公告日晚于最后交易日则跳过
    return None

def pead_ret(c, notice_d, horizon):
    ks = stocks[c]
    j0 = first_trade_on_or_after(c, notice_d)
    if j0 is None or j0 + horizon >= len(ks):
        return None
    # 公告当日盘后已知 → 次一交易日开盘买
    j1 = j0 + 1
    if j1 >= len(ks) or ks[j1]["open"] <= 0:
        return None
    return ks[j0 + horizon]["close"] / ks[j1]["open"] - 1 - 2 * FEE

pead = {"大幅预增": [], "扭亏": [], "预减首亏对照": [], "首次预增": [], "连续预增": []}
for c, evs in by_code.items():
    evs.sort(key=lambda e: e["NOTICE_DATE"])
    prev_good = []
    for e in evs:
        nd = e["NOTICE_DATE"][:10]
        ft = e.get("FORECASTTYPE", "")
        lo = e.get("INCREASEL")
        big_up = ft == "预增" and isinstance(lo, (int, float)) and lo >= 50
        turn = ft == "扭亏"
        bad = ft in ("预减", "首亏")
        for h, key in ((20, None),):
            r = pead_ret(c, nd, 20)
            if r is None:
                continue
            if big_up:
                pead["大幅预增"].append(r)
                nd_date = datetime.date.fromisoformat(nd)
                recent_good = [p for p in prev_good if (nd_date - p).days <= 400]
                (pead["连续预增"] if recent_good else pead["首次预增"]).append(r)
            elif turn:
                pead["扭亏"].append(r)
            elif bad:
                pead["预减首亏对照"].append(r)
        if big_up or turn:
            prev_good.append(datetime.date.fromisoformat(nd))

out["B_pead_T20"] = {k: stats(v) for k, v in pead.items()}
# 随机对照（同持有期20天；短序列剔除——B-D3 同类坑）
pool = []
long_enough = [c for c in stocks if len(stocks[c]) >= 90]
for _ in range(3000):
    c = rnd.choice(long_enough)
    ks = stocks[c]
    j = rnd.randint(61, len(ks) - 25)
    if ks[j + 1]["open"] > 0 and ks[j]["close"] > 0:
        pool.append(ks[j + 20]["close"] / ks[j + 1]["open"] - 1 - 2 * FEE)
out["B_pead_T20"]["随机对照"] = stats(pool)
# 分年衰减检查
by_year = defaultdict(list)
for c, evs in by_code.items():
    for e in evs:
        if e.get("FORECASTTYPE") == "预增" and isinstance(e.get("INCREASEL"), (int, float)) and e["INCREASEL"] >= 50:
            r = pead_ret(c, e["NOTICE_DATE"][:10], 20)
            if r is not None:
                by_year[e["NOTICE_DATE"][:4]].append(r)
out["B_pead_by_year"] = {y: stats(v) for y, v in sorted(by_year.items())}

json.dump(out, open(f"{D}/momentum_pead_20260913.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False, indent=1))
