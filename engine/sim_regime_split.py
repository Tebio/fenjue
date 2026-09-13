#!/usr/bin/env python3
"""engine/sim_regime_split.py — 打法×年份×周期交叉表 + 周期切换组合（2026-09-12，用户三问）

Q2 分年稳定性：每臂按出场年拆 均笔/胜率/n
Q3 分周期：每臂按 regime 拆（出场日贴标签，regime_timeline_hcap）
Q4 周期切换组合：样本内演示（每期选该期实测最优臂）——标注过拟合风险，待影子前向
"""
import json, sys, random
from collections import defaultdict

ROOT = "/opt/data/fenjue"
TRADES_F = sys.argv[1] if len(sys.argv) > 1 else f"{ROOT}/data/sim_trades_20260912.jsonl"
OUT_F = sys.argv[2] if len(sys.argv) > 2 else f"{ROOT}/data/sim_regime_split_20260912.json"
WIN_START = "2019-01-03" if "8y" in TRADES_F else "2024-08-26"
trades = [json.loads(l) for l in open(TRADES_F)]
timeline = {r["date"]: r["regime"] for r in json.load(open(f"{ROOT}/data/regime_timeline_hcap.json"))}
cal = [k["date"] for k in json.load(open(f"{ROOT}/data/big_kcache/000001.json"))]
window = [d for d in cal if d >= WIN_START]

arms = sorted({t["s"] for t in trades})

def stats(v):
    return {"n": len(v), "avg%": round(sum(v) / len(v) * 100, 2) if v else None,
            "win%": round(sum(1 for x in v if x > 0) / len(v) * 100, 1) if v else None}

# Q2 分年
by_year = {a: defaultdict(list) for a in arms}
# Q3 分周期
by_regime = {a: defaultdict(list) for a in arms}
for t in trades:
    by_year[t["s"]][t["out"][:4]].append(t["ret"])
    reg = timeline.get(t["out"], "?")
    by_regime[t["s"]][reg].append(t["ret"])

out = {"by_year": {a: {y: stats(v) for y, v in sorted(by_year[a].items())} for a in arms},
       "by_regime": {a: {r: stats(v) for r, v in by_regime[a].items()} for a in arms}}

# Q4 切换组合（样本内）：每 regime 选该期均笔最高的臂（剔除 reversal 死臂）
REGIME_BEST = {}
for r in ("恐慌期", "妖股期", "主线期", "平淡期"):
    best, best_avg = None, -9e9
    for a in arms:
        if a == "reversal":
            continue
        v = by_regime[a].get(r, [])
        if len(v) >= 10:
            m = sum(v) / len(v)
            if m > best_avg:
                best, best_avg = a, m
    REGIME_BEST[r] = (best, round(best_avg * 100, 2))
out["regime_best_arm_样本内"] = REGIME_BEST

# 切换组合权益：每日只用当日期最优臂的交易（槽位3）
by_day = defaultdict(lambda: defaultdict(list))
for t in trades:
    by_day[t["in"]][t["s"]].append(t["ret"])
eq, peak, mdd = 1.0, 1.0, 0.0
ndays = 0
for d in window:
    reg = timeline.get(d)
    arm = REGIME_BEST.get(reg, (None,))[0]
    rets = by_day.get(d, {}).get(arm, [])
    if rets:
        ndays += 1
        eq *= 1 + sum(rets) / 3
    peak = max(peak, eq)
    mdd = min(mdd, eq / peak - 1)
out["switched_portfolio"] = {"equity": round(eq, 2), "return%": round((eq - 1) * 100, 1),
                             "maxDD%": round(mdd * 100, 1), "active_days": ndays,
                             "note": "样本内选择=过拟合演示，真实切换逻辑须由8年研究结论驱动+影子前向验证"}

json.dump(out, open(OUT_F, "w"), ensure_ascii=False, indent=1)

# 中签压测（close-entry 臂）：30%/50% 排队中签后的权益
def fill_stress(arm, keep, seed=42):
    rnd = random.Random(seed)
    by_d = defaultdict(list)
    for t in trades:
        if t["s"] == arm and rnd.random() < keep:
            by_d[t["in"]].append(t["ret"])
    eq = 1.0
    for d in window:
        r = by_d.get(d, [])
        if r:
            eq *= 1 + sum(r) / 3
    return round(eq, 2)

for arm in ("short_optimized", "scalp_overnight", "panic_off"):
    if any(t["s"] == arm for t in trades):
        print(f"fill压测 {arm}: 100%→{fill_stress(arm, 1.0)}x 50%→{fill_stress(arm, 0.5)}x 30%→{fill_stress(arm, 0.3)}x")
print(json.dumps(out["regime_best_arm_样本内"], ensure_ascii=False))
print(json.dumps(out["switched_portfolio"], ensure_ascii=False))
print("\n=== 分年（主力臂）===")
for a in ("short_optimized", "scalp_overnight", "short_t1"):
    print(a, json.dumps(out["by_year"][a], ensure_ascii=False))
print("\n=== 分周期（主力臂）===")
for a in ("short_optimized", "scalp_overnight", "short_t1", "reversal"):
    print(a, json.dumps(out["by_regime"][a], ensure_ascii=False))
