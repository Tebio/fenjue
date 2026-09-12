#!/usr/bin/env python3
"""engine/sim_audit.py — 模拟盘独立审计（G10，2026-09-12 凌晨）

不信任 sim_tournament 的内部账目，从 kcache 原始行情独立复算：
A. 随机抽样逐笔对账（entry/exit 价格重取，收益重算）
B. 反转账户按信号日跌幅分档——应复现 S3 恐慌剂量曲线（+0.03/+0.17/+0.42/+1.10）
C. 月度收益拆分——查是否全靠 2024-09 政策底一波
D. 滑点压力：入场加价 0.3%/0.5% 后权益还剩多少
E. 赔率结构：平均赢/平均亏/最大单笔
"""
import json, random, glob
from collections import defaultdict

ROOT = "/opt/data/fenjue"
FEE = 0.0015
stocks = {}
for f in glob.glob(f"{ROOT}/data/big_kcache/*.json"):
    stocks[f.split("/")[-1][:6]] = json.load(open(f))
cal = [k["date"] for k in stocks["000001"]]
prev_date = {cal[i]: cal[i - 1] for i in range(1, len(cal))}
idx = {c: {k["date"]: j for j, k in enumerate(ks)} for c, ks in stocks.items()}

trades = [json.loads(l) for l in open(f"{ROOT}/data/sim_trades_20260912.jsonl")]
rev = [t for t in trades if t["s"] == "reversal"]
scalp = [t for t in trades if t["s"] == "scalp_overnight"]
out = {"rev_n": len(rev), "scalp_n": len(scalp)}

# ── A. 抽样独立复算 ──
random.seed(42)
bad = 0
for t in random.sample(rev, min(60, len(rev))):
    ks = stocks[t["code"]]
    ji, jo = idx[t["code"]].get(t["in"]), idx[t["code"]].get(t["out"])
    if ji is None or jo is None:
        continue
    entry, exit_ = ks[ji]["open"], ks[jo]["close"]
    expect = exit_ / entry - 1 - FEE
    if abs(expect - t["ret"]) > 1e-4:
        bad += 1
        if bad <= 3:
            print("MISMATCH", t, "复算:", round(expect, 6))
    # 信号逻辑校验：入场日前一交易日应跌≥3%
    sig_d = prev_date.get(t["in"])
    js = idx[t["code"]].get(sig_d)
    chg = ks[js]["close"] / ks[js - 1]["close"] - 1
    if chg > -0.03:
        bad += 1
        print("SIGNAL-VIOLATION", t["code"], t["in"], "信号日跌幅:", round(chg * 100, 2))
out["A_sample60_mismatch"] = bad

# ── B. 跌幅分档（对账 S3 剂量曲线）──
tiers = defaultdict(list)
for t in rev:
    ks = stocks[t["code"]]
    sig_d = prev_date.get(t["in"])
    js = idx[t["code"]].get(sig_d)
    if js is None or js < 1:
        continue
    chg = (ks[js]["close"] / ks[js - 1]["close"] - 1) * 100
    tier = ("-3~-5" if chg > -5 else "-5~-7" if chg > -7 else "-7~-9.5" if chg > -9.5 else "≤-9.5")
    tiers[tier].append(t["ret"] * 100)
out["B_tiers"] = {k: {"n": len(v), "avg%": round(sum(v) / len(v), 2),
                      "win%": round(sum(1 for x in v if x > 0) / len(v) * 100, 1)}
                  for k, v in sorted(tiers.items())}

# ── C. 月度拆分 + 2024-09 占比 ──
monthly = defaultdict(float)
for t in rev:
    monthly[t["out"][:7]] += t["ret"] / 3
tot = sum(monthly.values())
sep24 = monthly.get("2024-09", 0) + monthly.get("2024-10", 0)
out["C_monthly_top5"] = sorted(((m, round(v * 100, 1)) for m, v in monthly.items()),
                               key=lambda x: -x[1])[:5]
out["C_monthly_bottom5"] = sorted(((m, round(v * 100, 1)) for m, v in monthly.items()),
                                  key=lambda x: x[1])[:5]
out["C_sep24_share%"] = round(sep24 / tot * 100, 1) if tot else 0

# ── D. 滑点压力（反转账户，入场加价）──
for slip in (0.003, 0.005):
    rets = [t["ret"] - slip for t in rev]  # 近似：入场贵 slip → 收益减 slip
    by_day = defaultdict(float)
    for t, r in zip(rev, rets):
        by_day[t["out"]] += r / 3
    eq = 1.0
    for d in cal:
        if d in by_day:
            eq *= 1 + by_day[d]
    out[f"D_slip{slip}_equity"] = round(eq, 2)

# ── E. 赔率结构 ──
wins = [t["ret"] for t in rev if t["ret"] > 0]
loss = [t["ret"] for t in rev if t["ret"] <= 0]
out["E_avg_win%"] = round(sum(wins) / len(wins) * 100, 2)
out["E_avg_loss%"] = round(sum(loss) / len(loss) * 100, 2)
out["E_payoff_ratio"] = round((sum(wins) / len(wins)) / abs(sum(loss) / len(loss)), 2)
out["E_max_win%"] = round(max(wins) * 100, 1)
out["E_max_loss%"] = round(min(loss) * 100, 1)

# scalp 抽样对账（隔夜缺口口径：信号日收盘买→次日开盘卖）
bad2 = 0
for t in random.sample(scalp, min(30, len(scalp))):
    ks = stocks[t["code"]]
    ji, jo = idx[t["code"]].get(t["in"]), idx[t["code"]].get(t["out"])
    if ji is None or jo is None:
        continue
    expect = ks[jo]["open"] / ks[ji]["close"] - 1 - FEE
    if abs(expect - t["ret"]) > 1e-4:
        bad2 += 1
        print("SCALP-MISMATCH", t, "复算:", round(expect, 6))
out["scalp_sample30_mismatch"] = bad2

json.dump(out, open(f"{ROOT}/data/sim_audit_20260912.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False, indent=1))
