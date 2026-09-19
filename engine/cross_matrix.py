#!/usr/bin/env python3
"""cross_matrix.py — 存活组件系统化全交叉 + 消融（2026-09-19 用户批评「交叉没测完」立项）。

设计（BRAIN 式漏斗）：
  Stage 1 便宜筛：底座=跌停×MA60下。单次遍历全宇宙，底座事件上算组件位向量，
    所有 C(10,2) 配对一次成型。每对四档消融：base / base+A / base+B / base+A+B。
    指标：n / T+5 胜率/均值/赔率 / 位置匹配对照边际（同票同 MA60 下随机日等量采样）。
    幸存线：n≥200 且 A+B 边际>0 且 A+B 优于两单件（真交互而非单边驱动）。
  Stage 2 硬闸门：幸存对自动走 law_pipeline.submit_gate 全六闸+G7。
组件（全部存活/有实证者；死信号与物理互斥者不进组件库）：
  缩量、三连阴、250日输家、超跌20、避雷针低位、TD9买入、剔亏ST、缺口低开、触板未封、反转族
"""
import json
import random
import sys
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import law_pipeline as lp

ROOT = Path(__file__).resolve().parent.parent
FEE = 0.0015
T5, T20 = 5, 20

COMP = {   # 组件名 -> lp 检测函数（(d,i)->bool）
    "缩量": lambda d, i: lp._volratio(d, i) < 0.8,
    "三连阴": lp._three_down,
    "输家250": lp._loser250,
    "超跌20": lp._oversold20_60d,
    "避雷针低": lp._bigupper,
    "TD9买入": lp._td9buy,
    "剔亏ST": lp._fund_healthy,
    "缺口低开": lp._gap_down,
    "触板未封": lp._touch_not_seal,
    "反转族": lp._reversal,
}
NAMES = list(COMP)


def fwd(d, i, h):
    ei = i + 1
    if ei >= d["n"] or ei + h >= d["n"] or d["o"][ei] <= 0:
        return None
    if d["o"][ei] <= d["c"][i] * 0.905:
        return None
    return d["c"][ei + h] / d["o"][ei] - 1 - FEE


def stat(rs):
    rs = [r for r in rs if r is not None]
    if not rs:
        return None
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    odds = (sum(wins) / len(wins)) / abs(sum(losses) / len(losses)) if wins and losses else None
    return {"n": len(rs), "win%": round(100 * len(wins) / len(rs), 1),
            "mean%": round(100 * sum(rs) / len(rs), 2), "赔率": round(odds, 2) if odds else None}


def main():
    stocks = lp.load_universe()
    lp.build_xsection(stocks)

    # 单遍收集：底座事件的组件位向量 + 对照池（同票 MA60下 非底座日）
    events = []          # (code, i, bitmask)
    ctrl_pool = []       # (code, i) MA60下非底座日
    for code, d in stocks.items():
        c, ma, n = d["c"], d["ma60"], d["n"]
        for i in range(61, n - 22):
            if ma[i] is None or c[i] <= 0 or c[i - 1] <= 0:
                continue
            below = c[i] <= ma[i]
            if not below:
                continue
            is_base = c[i] / c[i - 1] - 1 <= -0.095 and d["o"][i + 1] > c[i] * 0.905
            if is_base:
                mask = 0
                for k, nm in enumerate(NAMES):
                    try:
                        if COMP[nm](d, i):
                            mask |= 1 << k
                    except Exception:
                        pass
                events.append((code, i, mask))
            else:
                ctrl_pool.append((code, i))
    print(f"底座事件 {len(events)}，对照池 {len(ctrl_pool)}", flush=True)

    def evalset(idxs):
        r5 = [fwd(stocks[c], i, T5) for c, i in idxs]
        r20 = [fwd(stocks[c], i, T20) for c, i in idxs]
        return stat(r5), stat(r20)

    rng = random.Random(2026)
    # 底座基线 + 对照边际基线
    base_all = [(c, i) for c, i, _ in events]
    base5, base20 = evalset(base_all)
    ctrl_s = rng.sample(ctrl_pool, min(len(base_all), len(ctrl_pool)))
    ctrl5, ctrl20 = evalset(ctrl_s)
    base_marg5 = round(base5["mean%"] - ctrl5["mean%"], 2)
    base_marg20 = round(base20["mean%"] - ctrl20["mean%"], 2)
    print(f"底座: T+5 {base5['win%']}%/{base5['mean%']}%（边际{base_marg5}） T+20 {base20['win%']}%/{base20['mean%']}%（边际{base_marg20}）", flush=True)

    out = {"底座": {"T+5": base5, "T+20": base20, "边际5": base_marg5, "边际20": base_marg20,
                    "对照T+5": ctrl5, "对照T+20": ctrl20}, "pairs": {}}

    singles = {}
    for k, nm in enumerate(NAMES):
        idxs = [(c, i) for c, i, m in events if m & (1 << k)]
        s5, s20 = evalset(idxs)
        singles[nm] = {"T+5": s5, "T+20": s20, "idxs_len": len(idxs)}
        print(f"  单件 {nm}: n={len(idxs)} T+5 {s5 and s5['win%']}%/{s5 and s5['mean%']}%", flush=True)
    out["singles"] = {k: {kk: vv for kk, vv in v.items() if kk != "idxs_len"} for k, v in singles.items()}

    survivors = []
    for a, b in combinations(range(len(NAMES)), 2):
        na, nb = NAMES[a], NAMES[b]
        idxs = [(c, i) for c, i, m in events if (m & (1 << a)) and (m & (1 << b))]
        if len(idxs) < 200:
            continue
        p5, p20 = evalset(idxs)
        # 对照：同位置随机日（从对照池按事件数采样）
        cs = rng.sample(ctrl_pool, min(len(idxs), len(ctrl_pool)))
        cc5, cc20 = evalset(cs)
        marg5 = round(p5["mean%"] - cc5["mean%"], 2)
        marg20 = round(p20["mean%"] - cc20["mean%"], 2)
        sa, sb = singles[na]["T+5"], singles[nb]["T+5"]
        beats_both = (sa is None or p5["mean%"] > sa["mean%"]) and (sb is None or p5["mean%"] > sb["mean%"])
        rec = {"n": len(idxs), "T+5": p5, "T+20": p20, "边际5": marg5, "边际20": marg20,
               "优于两单件": beats_both}
        out["pairs"][f"{na}×{nb}"] = rec
        flag = "✅" if (marg5 > 0 and beats_both) else ""
        print(f"  {na}×{nb}: n={len(idxs)} T+5 {p5['win%']}%/{p5['mean%']}% 边际{marg5}/{marg20} {flag}", flush=True)
        if marg5 > 0 and beats_both and p5["win%"] >= 55:
            survivors.append((na, nb))
    out["幸存待submit"] = survivors
    (ROOT / "data/cross_matrix_20260919.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("幸存对:", survivors, flush=True)
    print("saved stage1", flush=True)

    # Stage 2：幸存对注册临时检测器走 submit 全闸门
    if survivors:
        regime = lp.load_regime()
        stock_cap, qs = lp.load_cap_quintiles()
        for na, nb in survivors:
            name = f"交叉_跌停低_{na}_{nb}"
            lp.REGISTRY[name] = (lambda fa, fb: lambda d, i: (
                d["ma60"][i] is not None and d["c"][i] <= d["ma60"][i]
                and lp._limitdown(d, i) and fa(d, i) and fb(d, i)))(COMP[na], COMP[nb])
            passed, v = lp.submit_gate(name, lp.REGISTRY[name], stocks, regime, stock_cap, qs)
            print(f"SUBMIT {name}: {'PASS' if passed else 'REJECT'}", flush=True)
            print(json.dumps(v, ensure_ascii=False)[:400], flush=True)


if __name__ == "__main__":
    main()
