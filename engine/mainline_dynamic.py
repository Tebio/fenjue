#!/usr/bin/env python3
"""engine/mainline_dynamic.py — 主线进攻赛（2026-09-12，用户：主线期全仓打主线，纪律破了就走）

入场：frontrun V2（首板+板块梯队≥3+市值带）。出场四赛：
  S1 断板即跑（基线=现冠军）
  S2 主线持有：板块梯队≥2 且 收盘≥MA5 → 拿；否则次日开盘跑；封顶15天
  S3 主线宽容：板块梯队≥2 就拿（个股断板也拿），板块冷了且今日未板→次日跑；封顶15天
  S4 周期闸门+断板跑：只在主线期/妖股期开仓（regime timeline），出场同S1
--fill 走 m60 真实口径。信号缓存 data/frontrun_sigs_cache.json 复用。T+1 硬断言。
"""
import json, glob, sys, os
from collections import defaultdict

ROOT = "/opt/data/fenjue"
D = ROOT + "/data"
FILL = "--fill" in sys.argv
START = "2024-08-26" if FILL else "2019-01-03"
FEE = 0.0015
CAPITAL = 100000.0
sys.path.insert(0, ROOT + "/engine")
import claims_shadow as cs

stocks = cs.load_stocks()
ind = cs.industry_map()
cal = [k["date"] for k in stocks["000001"]]
dates = [d for d in cal if d >= START]
dpos = {d: i for i, d in enumerate(dates)}
idx = {c: {k["date"]: j for j, k in enumerate(ks)} for c, ks in stocks.items()}
timeline = {r["date"]: r["regime"] for r in json.load(open(f"{D}/regime_timeline_hcap.json"))}

def m60_fillable(code, d, close):
    try:
        bars = [r for r in json.load(open(f"{D}/m60_cache/{code}.json")) if r["day"].startswith(d)]
    except Exception:
        return False
    return bool(bars) and float(bars[-1]["low"]) < close * 0.995

# 每日行业梯队 + regime
ladder_by_date = {}
for d in dates:
    lad = defaultdict(int)
    for c, ks in stocks.items():
        j = idx[c].get(d)
        if j and j >= 1 and ks[j-1]["close"] > 0 and ks[j]["close"]/ks[j-1]["close"]-1 >= 0.098:
            lad[ind.get(c, {}).get("industry") or "?"] += 1
    ladder_by_date[d] = lad

# 信号（带缓存；缓存不带 fill 过滤，fill 在使用处再筛）
CACHE = f"{D}/frontrun_sigs_cache.json"
if os.path.exists(CACHE):
    all_sigs = [tuple(x) for x in json.load(open(CACHE))]
else:
    all_sigs = []
    full_dates = [d for d in cal if d >= "2019-01-03"]
    for d in full_dates[:-1]:
        lad = defaultdict(int)
        for c, ks in stocks.items():
            j = idx[c].get(d)
            if j and j >= 1 and ks[j-1]["close"] > 0 and ks[j]["close"]/ks[j-1]["close"]-1 >= 0.098:
                lad[ind.get(c, {}).get("industry") or "?"] += 1
        for c, ks in stocks.items():
            j = idx[c].get(d)
            if j is None or j < 65 or j+1 >= len(ks):
                continue
            if ks[j-1]["close"] <= 0 or ks[j]["close"]/ks[j-1]["close"]-1 < 0.098:
                continue
            if any(h[0] == "FRONTRUN_FIRSTBOARD_V2" for h in cs.detect(c, ks, j, lad)):
                all_sigs.append((d, c))
    json.dump(all_sigs, open(CACHE, "w"))
sigs = [(d, c) for d, c in all_sigs if d >= START]
if FILL:
    sigs = [(d, c) for d, c in sigs if m60_fillable(c, d, stocks[c][idx[c][d]]["close"])]
print(f"信号 {len(sigs)}（{'真实fill' if FILL else '纸面'}）", file=sys.stderr)

def ma5(ks, j):
    return sum(ks[k]["close"] for k in range(j-4, j+1))/5 if j >= 4 else None

def play(rule):
    eq = CAPITAL
    open_pos, trades = [], []
    sig_by_d = defaultdict(list)
    for d, c in sigs:
        sig_by_d[d].append(c)
    for d in dates:
        di = dpos[d]
        for p in list(open_pos):
            ks = stocks[p["code"]]
            j = idx[p["code"]].get(d)
            if j is None or j < 1 or ks[j]["close"] <= 0:
                continue
            if p.get("sell_today"):
                px = ks[j]["open"] if ks[j]["open"] > 0 else ks[j]["close"]
                ret = px/p["entry"]-1-FEE
                eq += p["cash"]*(1+ret); trades.append((p["entry_date"], d, p["code"], ret, p.get("why","")))
                open_pos.remove(p); continue
            hold_days = di - p["entry_di"]
            if hold_days < 1:
                continue
            chg = ks[j]["close"]/ks[j-1]["close"]-1
            sealed = chg >= 0.098
            industry = ind.get(p["code"], {}).get("industry") or "?"
            lad_today = ladder_by_date[d].get(industry, 0)
            m5 = ma5(ks, j)
            if rule in ("S1", "S4"):
                if p.get("pending_open"):
                    p["sell_today"] = True
                elif sealed:
                    p["pending_open"] = True
                else:
                    px = ks[j]["close"]; ret = px/p["entry"]-1-FEE
                    eq += p["cash"]*(1+ret); trades.append((p["entry_date"], d, p["code"], ret, "断板尾盘")); open_pos.remove(p)
            elif rule == "S2":
                if lad_today >= 2 and m5 and ks[j]["close"] >= m5 and hold_days < 15:
                    pass
                else:
                    p["sell_today"] = True
                    p["why"] = "主线熄火" if lad_today < 2 else ("破MA5" if m5 and ks[j]["close"] < m5 else "封顶15天")
            elif rule == "S3":
                if lad_today >= 2 and hold_days < 15:
                    pass
                elif not sealed:
                    p["sell_today"] = True
                    p["why"] = "主线冷+未板" if lad_today < 2 else "封顶15天"
        if rule == "S4" and timeline.get(d) not in ("主线期", "妖股期"):
            continue
        for c in sig_by_d.get(d, []):
            if len(open_pos) >= 3:
                break
            ks = stocks[c]; j = idx[c][d]
            cash = eq/3
            eq -= cash
            open_pos.append({"code": c, "entry": ks[j]["close"], "cash": cash, "entry_date": d, "entry_di": di})
    for p in open_pos:
        ks = stocks[p["code"]]
        ret = ks[-1]["close"]/p["entry"]-1-FEE
        eq += p["cash"]*(1+ret); trades.append((p["entry_date"], dates[-1], p["code"], ret, "尾部强平"))
    for t in trades:
        assert dpos.get(t[1], -1) > dpos.get(t[0], 10**9), f"T+1违规 {t}"
    wins = [t for t in trades if t[3] > 0]
    return {"equity": round(eq), "return%": round((eq/CAPITAL-1)*100, 1), "trades": len(trades),
            "win%": round(len(wins)/len(trades)*100, 1) if trades else 0,
            "avg%": round(sum(t[3] for t in trades)/len(trades)*100, 2) if trades else 0}, trades

out, detail = {}, {}
for rule in ("S1", "S2", "S3", "S4"):
    out[rule], detail[rule] = play(rule)
    print(rule, out[rule], file=sys.stderr)
why = defaultdict(list)
for t in detail["S2"]:
    why[t[4]].append(t[3])
out["S2_why"] = {k: {"n": len(v), "avg%": round(sum(v)/len(v)*100, 2)} for k, v in why.items()}
suf = "_fill" if FILL else ""
json.dump(out, open(f"{D}/mainline_dynamic{suf}_20260912.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False, indent=1))
