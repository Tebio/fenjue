#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""engine/dividend_aftertax_study.py — 红利税三档建模研究（TAX-02，AGENTS #287）

只出研究结论，不改生产锚线。四段：
A. 税后锚线重算：4.5%/4.0%/3.0% 毛口径锚 → 三档税后的实收息率与等效价格带
B. 股息锚线典型持有期分布（红利分层 8 年 117 笔台账）vs 税级
C. 实际税额与拖累：逐笔用 dividend_history + big_kcache_unadj 买入价算
   红利税（卖出时持有期定档，costs.dividend_tax_rate），对照 #T6 的 0.15~0.36pp 估算
D. 「持有满 1 年免税」作策略规则的 edge 量化（上界节省 vs 延长持有的代价）

输出：data/dividend_aftertax_20261016.json + stdout 报告（誊进 docs/research/dividend-aftertax.md）
"""
import csv
import glob
import json
import os
import statistics as st
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from costs import dividend_tax_rate  # TAX-01 唯一真源

ROOT = "/opt/data/fenjue"
D = ROOT + "/data"
OUT = {}

# ── A. 税后锚线重算 ────────────────────────────────────────────────────
ANCHORS = {"买入线": 0.045, "卖出线": 0.040, "清仓线": 0.030}
TIERS = [("<1月 20%", 0.20), ("1月-1年 10%", 0.10), ("≥1年 免", 0.0)]
partA = {}
for name, g in ANCHORS.items():
    partA[name] = {"毛息率锚": g}
    for label, t in TIERS:
        partA[name][label] = {
            "税后实收息率": round(g * (1 - t) * 100, 3),          # 现价带下实际到手
            "保持税后同等息的等效毛门槛": round(g / (1 - t) * 100, 3),  # 锚若改税后口径
            "价格带系数": round(1 - t, 3),                        # 买入价带下移比例
        }
OUT["A_税后锚线重算"] = partA

# 工作例：红利宇宙里取真实 DPS 算元/股价格带
dcache = json.load(open(f"{D}/dividend_cache.json"))
names = {c: v.get("name", "") for c, v in json.load(open(f"{D}/industry_map.json")).items()}
examples = []
for code in ("601398", "601288", "600036", "601988", "601166"):
    if code in dcache:
        dps = dcache[code]["dps"]
        ex = {"code": code, "name": names.get(code, ""), "dps_ttm": dps}
        for label, t in TIERS:
            ex[f"买入线价_{label}"] = round(dps * (1 - t) / 0.045, 2)
        ex["买入线价_毛口径"] = round(dps / 0.045, 2)
        examples.append(ex)
OUT["A_工作例"] = examples

# ── B/C. 持有期分布 + 逐笔税额 ─────────────────────────────────────────
trades = list(csv.DictReader(open(f"{D}/红利分层_8年交易明细.csv", encoding="utf-8-sig")))
divh = json.load(open(f"{D}/dividend_history.json"))
unadj = {}
for f in glob.glob(f"{D}/big_kcache_unadj/*.json"):
    unadj[os.path.basename(f)[:6]] = json.load(open(f))

def dt(s):
    return datetime.strptime(s, "%Y-%m-%d").date()

def buy_price(code, dstr):
    ks = unadj.get(code)
    if not ks:
        return None
    for k in ks:  # 台账买入日=成交日，用当日开盘价（分层模拟器 T+1 开盘买）
        if k["date"] >= dstr:
            return k.get("open") or k.get("close")
    return None

rows = []
for r in trades:
    code, b, s = r["代码"], r["买入日"], r["卖出日"]
    held = (dt(s) - dt(b)).days
    rate = dividend_tax_rate(b, s)
    dps_in = sum(d for dstr, d in divh.get(code, []) if b < dstr <= s)
    px = buy_price(code, b)
    tax_ps = rate * dps_in                     # 每股红利税（元）
    drag_pp = tax_ps / px * 100 if px else None  # 占买入价 pp
    rows.append({
        "code": code, "name": r["名称"], "layer": r["层"], "buy": b, "sell": s,
        "held_days": held, "tax_rate": rate, "dps_in_hold": round(dps_in, 4),
        "buy_px_unadj": px, "tax_per_share": round(tax_ps, 4),
        "drag_pp": round(drag_pp, 3) if drag_pp is not None else None,
        "ret_pct": float(r["收益%"]), "sell_why": r["卖出原因"],
    })

n = len(rows)
# 冷启动冲刷：窗口首日买入「已连续 500 交易日无分红」的票被立即强平，
# 持有 1-3 天、与息率锚逻辑无关，单列不计入「典型持有期」
flush = [r for r in rows if r["sell_why"] == "连续500交易日无分红" and r["held_days"] <= 10]
real = [r for r in rows if r not in flush]

def bucket_of(rs):
    return {
        "<1月(20%)": {"笔数": len([r for r in rs if r["tax_rate"] == 0.20])},
        "1月-1年(10%)": {"笔数": len([r for r in rs if r["tax_rate"] == 0.10])},
        "≥1年(免)": {"笔数": len([r for r in rs if r["tax_rate"] == 0.0])},
    }

def held_stat(rs):
    if not rs:
        return {}
    h = sorted(r["held_days"] for r in rs)
    return {"中位": h[len(h) // 2], "P25": h[len(h) // 4], "P75": h[3 * len(h) // 4],
            "min": h[0], "max": h[-1]}

partB = {
    "总笔数": n,
    "冷启动冲刷笔数": len(flush),
    "冲刷说明": "2019-01 窗口开局买入后立即触发「连续500交易日无分红」强平，"
              "持有 1-3 天、从未收分红、与锚线策略逻辑无关 → 单列",
    "全台账_持有天数": held_stat(rows),
    "真持仓_持有天数": held_stat(real),
    "真持仓_税级分布": bucket_of(real),
    "真持仓_按卖出原因": {w: {"笔数": len([r for r in real if r["sell_why"] == w]),
                          "持有天中位": held_stat([r for r in real if r["sell_why"] == w]).get("中位")}
                       for w in sorted({r["sell_why"] for r in real})},
}
OUT["B_持有期分布"] = partB

priced = [r for r in rows if r["drag_pp"] is not None]
taxed = [r for r in priced if r["tax_per_share"] > 0]
partC = {
    "可定价笔数": len(priced),
    "持有期内收到分红的笔数": len(taxed),
    "收分红笔的税级分布": {k: len([r for r in taxed if r["tax_rate"] == t])
                      for k, t in [("<1月20%", 0.20), ("1月-1年10%", 0.10), ("≥1年免", 0.0)]},
    "逐笔拖累pp": {
        "全体均值": round(st.mean(r["drag_pp"] for r in priced), 3),
        "全体中位": round(st.median(r["drag_pp"] for r in priced), 3),
        "仅收分红笔均值": round(st.mean(r["drag_pp"] for r in taxed), 3) if taxed else 0,
        "最大": round(max(r["drag_pp"] for r in priced), 3),
    },
    "按卖出原因": {},
    "总分红vs总税_每股口径": {
        "ΣDPS(每股)": round(sum(r["dps_in_hold"] for r in priced), 3),
        "Σ税(每股)": round(sum(r["tax_per_share"] for r in priced), 3),
    },
    "口径限制": "已平仓台账下界口径——分层模拟器长期持仓的期末在途仓位不在 CSV 里，"
              "而真正吃分红的恰是长持核心仓；组合级年拖累以 #T6 曲线口径 0.15~0.36pp 为准",
    "对照_T6估算": "#T6 估 0.15~0.36pp/年拖累（除权日 81% 集中 5-7 月，持有<1 年 10%）",
}
for w in sorted({r["sell_why"] for r in priced}):
    sub = [r for r in priced if r["sell_why"] == w]
    partC["按卖出原因"][w] = {"笔数": len(sub),
                          "拖累pp均值": round(st.mean(r["drag_pp"] for r in sub), 3)}
OUT["C_实际税额拖累"] = partC

# ── D. 满1年免税规则 edge 量化 ─────────────────────────────────────────
real_priced = [r for r in real if r["drag_pp"] is not None]
save_all = st.mean(r["drag_pp"] for r in priced)
save_real = st.mean(r["drag_pp"] for r in real_priced) if real_priced else 0
short = [r for r in real_priced if r["held_days"] < 365]
ext = sorted(365 - r["held_days"] for r in short)
partD = {
    "上界节省_pp每笔_全台账": round(save_all, 3),
    "上界节省_pp每笔_真持仓": round(save_real, 3),
    "含义": "若全部交易持有满 1 年（税率 0），每笔平均多留的税后收益上界；"
           "实际规则只能救回「原本不满 1 年」的那部分",
    "真持仓不满1年笔": {"笔数": len(short),
                  "占真持仓%": round(len(short) / len(real_priced) * 100, 1) if real_priced else 0,
                  "需延长天数中位": ext[len(ext) // 2] if ext else 0,
                  "这些笔的拖累pp均值": round(st.mean(r["drag_pp"] for r in short), 3) if short else 0},
    "OOS口径注": "dividend_anchor_oos 的事件窗=T+120 交易日≈5.7 个月 → 全部落在 10% 档；"
               "4.5% 毛锚在该 horizon 的税后实收=4.05%，净边际 +1.1pp 税后≈+0.99pp 级",
}
OUT["D_满1年免税edge"] = partD

OUT["_meta"] = {"date": "2026-10-16", "script": "engine/dividend_aftertax_study.py",
              "台账": "data/红利分层_8年交易明细.csv（117 笔，核心/卫星 8 年模拟）",
              "税": "costs.dividend_tax_rate（卖出时持有期定档，日历月含边界）",
              "价": "big_kcache_unadj 买入日开盘价（不复权）",
              "限制": "台账为模拟口径非实盘；分层模拟器 2019-01 起；"
                     "分红日记账=除权日，到账时滞忽略（与源模拟器一致）"}

json.dump(OUT, open(f"{D}/dividend_aftertax_20261016.json", "w"), ensure_ascii=False, indent=1)

print("═══ A. 税后锚线重算 ═══")
for name, row in partA.items():
    print(f"{name} 毛{row['毛息率锚']*100:.1f}% → " + " | ".join(
        f"{label}: 实收{v['税后实收息率']}% (等效毛门槛 {v['保持税后同等息的等效毛门槛']}%, 价带×{v['价格带系数']})"
        for label, v in row.items() if label != "毛息率锚"))
print("工作例（买入线价, 元）:")
for ex in examples:
    print(f"  {ex['code']} {ex['name']} DPS={ex['dps_ttm']}: 毛{ex['买入线价_毛口径']} → " +
          " / ".join(f"{k.split('_')[1]}{v}" for k, v in ex.items() if k.startswith("买入线价_") and "毛" not in k))
print("\n═══ B. 持有期分布 vs 税级 ═══")
print(f"全台账 {partB['总笔数']} 笔（含冷启动冲刷 {partB['冷启动冲刷笔数']} 笔：{partB['冲刷说明'][:30]}…）")
print(f"全台账持有天: {partB['全台账_持有天数']}")
print(f"真持仓持有天: {partB['真持仓_持有天数']}")
print(f"真持仓税级分布: {json.dumps(partB['真持仓_税级分布'], ensure_ascii=False)}")
print(f"真持仓按卖出原因: {json.dumps(partB['真持仓_按卖出原因'], ensure_ascii=False)}")
print("\n═══ C. 实际税额拖累 ═══")
print(json.dumps(partC, ensure_ascii=False, indent=1))
print("\n═══ D. 满1年免税 edge ═══")
print(json.dumps(partD, ensure_ascii=False, indent=1))
print(f"\nSAVED data/dividend_aftertax_20261016.json")
