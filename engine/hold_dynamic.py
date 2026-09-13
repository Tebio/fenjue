#!/usr/bin/env python3
"""engine/hold_dynamic.py — 妖股动态持有赛（2026-09-12 深夜，用户：情绪逻辑没破多拿两天）

同一批入场（frontrun V2：首板+梯队≥3+市值带，T+1合规，信号日收盘打板口径），赛三种出场：
  A. fixed5   固定拿5天（swing 基线）
  B. board_overnight  涨停隔夜（现冠军规则）
  C. dynamic  动态持有（用户直觉工程化）：
     - 当日再封板 → 拿（情绪在）
     - 首阴+天量（量>3×5日均）→ 次日开盘跑（情绪崩）
     - 收盘破 MA5 → 次日开盘跑（形态破）
     - 梯队散（同行业当日涨停<2）且今日未板 → 次日开盘跑（逻辑破）
     - 封顶 10 天
量能/情绪/周期全入模。--fill 模式只算 m60 尾盘开缝可成交的（真实口径，2年窗）。
T+1 硬断言：卖出日>入场日。
"""
import json, glob, sys
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

def m60_fillable(code, d, close):
    try:
        bars = [r for r in json.load(open(f"{D}/m60_cache/{code}.json")) if r["day"].startswith(d)]
    except Exception:
        return False
    return bool(bars) and float(bars[-1]["low"]) < close * 0.995

# 每日行业梯队
ladder_by_date = {}
for d in dates:
    lad = defaultdict(int)
    for c, ks in stocks.items():
        j = idx[c].get(d)
        if j and j >= 1 and ks[j-1]["close"] > 0 and ks[j]["close"]/ks[j-1]["close"]-1 >= 0.098:
            lad[ind.get(c, {}).get("industry") or "?"] += 1
    ladder_by_date[d] = lad

# 信号日收集（frontrun V2）
sigs = []
for d in dates[:-1]:
    lad = ladder_by_date[d]
    for c, ks in stocks.items():
        j = idx[c].get(d)
        if j is None or j < 65 or j+1 >= len(ks):
            continue
        if ks[j-1]["close"] <= 0 or ks[j]["close"]/ks[j-1]["close"]-1 < 0.098:
            continue
        hits = cs.detect(c, ks, j, lad)
        if any(h[0] == "FRONTRUN_FIRSTBOARD_V2" for h in hits):
            if FILL and not m60_fillable(c, d, ks[j]["close"]):
                continue
            sigs.append((d, c))
print(f"信号 {len(sigs)} 个（{'真实fill' if FILL else '纸面'}）", file=sys.stderr)

def ma5(ks, j):
    return sum(ks[k]["close"] for k in range(j-4, j+1))/5 if j >= 4 else None

def play(rule):
    eq = CAPITAL
    open_pos = []
    trades = []
    sig_by_d = defaultdict(list)
    for d, c in sigs:
        sig_by_d[d].append(c)
    for d in dates:
        di = dpos[d]
        # 出场决策
        for p in list(open_pos):
            ks = stocks[p["code"]]
            j = idx[p["code"]].get(d)
            if j is None or j < 1 or ks[j]["close"] <= 0:
                continue
            if p.get("sell_today"):  # 昨日决策今日开盘卖
                px = ks[j]["open"] if ks[j]["open"] > 0 else ks[j]["close"]
                ret = px/p["entry"] - 1 - FEE
                eq += p["cash"]*(1+ret)
                trades.append((p["entry_date"], d, p["code"], ret, p.get("why","")))
                open_pos.remove(p)
                continue
            hold_days = di - p["entry_di"]
            if hold_days < 1:
                continue
            chg = ks[j]["close"]/ks[j-1]["close"] - 1
            sealed = chg >= 0.098
            m5 = ma5(ks, j)
            vol5 = sum(ks[k]["volume"] for k in range(j-5, j))/5 if j >= 5 else ks[j]["volume"]
            industry = ind.get(p["code"], {}).get("industry") or "?"
            lad_today = ladder_by_date[d].get(industry, 0)
            sell, why = False, ""
            if rule == "fixed5":
                if hold_days >= 5:
                    px = ks[j]["close"]; ret = px/p["entry"]-1-FEE
                    eq += p["cash"]*(1+ret); trades.append((p["entry_date"], d, p["code"], ret, "到期5天")); open_pos.remove(p)
            elif rule == "board_overnight":
                if p.get("pending_open"):
                    p["sell_today"] = True
                elif sealed:
                    p["pending_open"] = True
                else:
                    px = ks[j]["close"]; ret = px/p["entry"]-1-FEE
                    eq += p["cash"]*(1+ret); trades.append((p["entry_date"], d, p["code"], ret, "断板尾盘")); open_pos.remove(p)
            elif rule == "dynamic":
                if sealed:
                    pass  # 情绪在，拿
                elif chg < 0 and ks[j]["volume"] > 3*vol5:
                    sell, why = True, "首阴天量(情绪崩)"
                elif m5 and ks[j]["close"] < m5:
                    sell, why = True, "破MA5(形态破)"
                elif lad_today < 2 and not sealed:
                    sell, why = True, "梯队散(逻辑破)"
                elif hold_days >= 10:
                    sell, why = True, "封顶10天"
                if sell:
                    p["sell_today"] = True; p["why"] = why
        # 入场
        for c in sig_by_d.get(d, []):
            if len(open_pos) >= 3:
                break
            ks = stocks[c]
            j = idx[c][d]
            cash = eq/3
            eq -= cash
            open_pos.append({"code": c, "entry": ks[j]["close"], "cash": cash,
                             "entry_date": d, "entry_di": di})
    # 尾部强平
    for p in open_pos:
        ks = stocks[p["code"]]
        px = ks[-1]["close"]
        ret = px/p["entry"]-1-FEE
        eq += p["cash"]*(1+ret)
        trades.append((p["entry_date"], dates[-1], p["code"], ret, "尾部强平"))
    # T+1 硬断言
    for t in trades:
        assert dpos.get(t[1], -1) > dpos.get(t[0], 10**9), f"T+1违规 {t}"
    wins = [t for t in trades if t[3] > 0]
    return {"equity": round(eq), "return%": round((eq/CAPITAL-1)*100, 1), "trades": len(trades),
            "win%": round(len(wins)/len(trades)*100, 1) if trades else 0,
            "avg%": round(sum(t[3] for t in trades)/len(trades)*100, 2) if trades else 0}, trades

out = {}
all_trades = {}
for rule in ("fixed5", "board_overnight", "dynamic"):
    out[rule], all_trades[rule] = play(rule)
    print(rule, out[rule], file=sys.stderr)

# dynamic 出场原因分解
why_stats = defaultdict(list)
for t in all_trades["dynamic"]:
    why_stats[t[4]].append(t[3])
out["dynamic_why"] = {k: {"n": len(v), "avg%": round(sum(v)/len(v)*100, 2)} for k, v in why_stats.items()}
suf = "_fill" if FILL else ""
json.dump(out, open(f"{D}/hold_dynamic{suf}_20260912.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False, indent=1))
