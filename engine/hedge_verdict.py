#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""engine/hedge_verdict.py — 卡 t_4a55cc92 的 ⑤判决 段：从 hedge_test 产物抽判决表。

只读 data/research/hedge_test_20261016.json，追加 "⑤判决表" 段（幂等覆盖该键）。
**判决按 horizon 分级**（T+1/T+5/T+20 结论不同，压平成一个数就是不诚实）。
用法 .venv/bin/python engine/hedge_verdict.py
"""
import json
from pathlib import Path

OUT = Path("/opt/data/fenjue/data/research/hedge_test_20261016.json")
d = json.loads(OUT.read_text())

LINES = ["DEEP_LEDGER", "LD", "PEAD", "REV"]
# 位置匹配对照只有 npz 行口径（台账口径宇宙不同、可比对照池不同）→ 映射
CTRL_KEY = {"DEEP_LEDGER": "DEEP_NPZ", "LD": "LD", "PEAD": "PEAD", "REV": "REV"}
HZ = (1, 5, 20)
# 对冲腿：IC 期货（中证500）为可估上限；ETF 512100（中证1000）为散户可执行路
ROAD = {"期货": "IC", "ETF": "sh512100"}

ctrl = d.get("⑤位置匹配对照_IC期货λ=1", {})
ctrl_sum = {L: {h: v.get("净alpha(信号−对照)_pp") for h, v in c.items()} for L, c in ctrl.items()}


def cell(line, road, h, lam):
    key = f"{ROAD[road]}_T+{h}"
    return d[line]["对冲矩阵"][road].get(key, {}).get(f"λ={lam}")


rows = {}
for L in LINES:
    base = d[L]["基础(不对冲)"]
    r = {}
    for h in HZ:
        e = {}
        for road in ("期货", "ETF"):
            a0, a1 = cell(L, road, h, 0.0), cell(L, road, h, 1.0)
            if not a0 or not a1:
                continue
            m0, m1 = a0.get("mean_pp"), a1.get("mean_pp")
            e[road] = {"原始_pp": m0, "对冲后_pp": m1,
                       "被剥掉_pp": round(m0 - m1, 3),
                       "保留比例": round(m1 / m0, 3) if m0 else None,
                       "对冲后t_NW": a1.get("t_NW"), "对冲后胜率": a1.get("win%"), "n": a1.get("n")}
        e["期货_各指数对照_对冲后_pp"] = {
            t: (cell(L, "期货", h, 1.0) or {}).get("mean_pp") for t in ("IC", "IF", "IM")}
        e["位置匹配净alpha_pp"] = ctrl_sum.get(CTRL_KEY.get(L, L), {}).get(f"T+{h}")
        r[f"T+{h}"] = e
    r["原始_全horizon"] = {f"T+{h}": base.get(f"T+{h}") for h in HZ}
    rows[L] = r


def judge(keep, tN, net):
    """keep=ETF路保留比例; tN=对冲后t_NW; net=位置匹配净alpha"""
    zero = (keep is not None and keep < 0.35) or (tN is not None and abs(tN) < 3.0)
    if net is not None and net > 0.5 and tN is not None and abs(tN) >= 3.0 and not zero:
        return "存活：对冲后仍有正 net alpha"
    if zero and (net is None or net <= 0.5):
        return "归零：纯 beta"
    return "灰区：beta 为主但残留不可忽略"


verdict = {
    "对冲腿": {"期货": "IC0 中证500主力连续（可估上限，散户物理不可行）",
             "ETF": "512100 中证1000ETF（散户唯一可执行路，含 8.5%/年借券费）",
             "理由": "信号票多为中小盘深跌件，中证500/1000 对冲更贴；IF 作对照档一并落数"},
    "判据": ("每个 horizon 独立判：ETF 路保留比例 <35% 或 |t_NW|<3 视为归零；"
           "另加位置匹配对照（同日同 depth 十分位非信号票、同结构对冲）net alpha ≤+0.5pp 不予存活。"
           "三条同时满足才判存活。"),
    "逐线对冲表": rows,
    "位置匹配对照_净alpha_pp": ctrl_sum,
    "逐线逐horizon": {},
    "按horizon汇总": {},
    "总结论": None,
}

for L in LINES:
    verdict["逐线逐horizon"][L] = {}
    for h in HZ:
        e = rows[L][f"T+{h}"]
        etf, fut = e.get("ETF", {}), e.get("期货", {})
        net = e.get("位置匹配净alpha_pp")
        verdict["逐线逐horizon"][L][f"T+{h}"] = {
            "原始_pp": (rows[L]["原始_全horizon"].get(f"T+{h}") or {}).get("mean_pp"),
            "ETF路": f"{etf.get('原始_pp')} → {etf.get('对冲后_pp')}pp（保留 {etf.get('保留比例')}, t_NW {etf.get('对冲后t_NW')}）" if etf else None,
            "期货路(IC)": f"{fut.get('原始_pp')} → {fut.get('对冲后_pp')}pp（保留 {fut.get('保留比例')}）" if fut else None,
            "位置匹配净alpha_pp": net,
            "判词": judge(etf.get("保留比例"), etf.get("对冲后t_NW"), net)}

by_h = {}
for h in HZ:
    z = sum(1 for L in LINES if "归零" in verdict["逐线逐horizon"][L][f"T+{h}"]["判词"])
    s = sum(1 for L in LINES if "存活" in verdict["逐线逐horizon"][L][f"T+{h}"]["判词"])
    by_h[f"T+{h}"] = {"归零": z, "存活": s, "灰区": len(LINES) - z - s}
verdict["按horizon汇总"] = by_h

verdict["总结论"] = (
    "**「edge 是 beta」只在短 horizon 成立——本卡把它按时间轴拆开，这是关键修正**。"
    f"① **T+1 全面归零**（{by_h['T+1']['归零']}/4 归零，0 存活）：对冲掉 beta 后四条线 T+1 全部转负"
    "（DEEP_NPZ 原始 +4.35pp → 对冲后 -6.68pp；LD +1.55 → -1.06；REV +0.22 → -0.19）——"
    "**负得比原始正得多**，说明信号票 T+1 的 beta 敞口 >1，原始正收益完全是「跌深了跟着大盘反弹」，"
    "剥掉 beta 后残差为负。AGENTS #290 的「beta 时点」论断在 T+1 上是铁证。"
    f"② **T+5 仍以 beta 为主**（归零 {by_h['T+5']['归零']}/4）：ETF 路上 LD 5.28→0.04（保留 0.8%）、REV 1.06→-0.91、"
    "PEAD 1.44→-0.10；位置匹配对照 T+5 给 LD -0.38 / REV -0.14 / PEAD +0.19。"
    f"③ **T+20 出现真正的例外**（存活 {by_h['T+20']['存活']}/4）：IC 期货路 DEEP_NPZ 对冲后保留 24.0pp（保留 57%）、"
    "LD 保留 5.04pp（44%）；位置匹配对照同步给正 net alpha——DEEP_NPZ **+5.18pp**、LD **+1.32pp**。"
    "同一天同 depth 十分位的非信号票在同样对冲后只拿到 +18.1pp（DEEP_NPZ 对照口径），信号票高出 5.18pp，"
    "这不是 beta 残差能解释的量级。"
    "④ 正确结论是**分层**的：T+1/T+5 的交易 edge 是 regime/beta 机器（剥掉 beta 后不值得交易）；"
    "但**最深档（DEEP_NPZ：跌停+深跌件+簇≥5）在 T+20 留有经位置匹配对照确认的净 alpha（+5.18pp）**，"
    "LD 线同向但弱（+1.32pp）。这与「深档低位 v2 = T+5 68%/+11.95%」不矛盾，"
    "而是提示该线价值在更长持有窗而非 T+5 兑现。"
    "⑤ 成本与可执行性：期货路单次 1.1~3.3bp 但散户物理不可行（一手 IC/IM 名义≈130 万元 vs 20 万档单批≈7.9 万元，"
    "差 16 倍；且 50 万可用资金开户门槛）；ETF 融券路可执行但 T+5 单次 23.0bp、T+20 79.8bp（借券费 8.5%/年主导），"
    "是期货路的 15~25 倍。**T+20 的 +5.18pp 净 alpha 扣 80bp 融券（0.8pp）后仍剩 +4.4pp → 这一条扣完成本还活着**；"
    "T+5 的 PEAD +0.19pp 扣 23bp 后为 -0.04pp，不成立。"
    "⑥ 与既有生产结论的关系：本卡**不推翻**「beta 对冲掉后 T+5 归零」的读法，但补上了一条它掩盖的事实——"
    "对冲检验的输赢取决于 horizon，T+20 上深档线是活的；也因此对深档线的兑现窗口提出新假设（T+5 卖早了）。")

d["⑤判决表"] = verdict
OUT.write_text(json.dumps(d, ensure_ascii=False, indent=1))

print(json.dumps(verdict["按horizon汇总"], ensure_ascii=False))
for L in LINES:
    print("=" * 68)
    print(L, "n=", d[L].get("n"))
    for h in HZ:
        x = verdict["逐线逐horizon"][L][f"T+{h}"]
        print(f"  T+{h}: 原始 {x['原始_pp']}pp | ETF {x['ETF路']} | ctrl净 {x['位置匹配净alpha_pp']} | {x['判词']}")
print("=" * 68)
print(verdict["总结论"])
