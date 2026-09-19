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
HORIZONS = (1, 2, 3, 5, 10, 20)   # 2026-09-19 用户批评「又是T+5」→ 全 horizon

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


BASE_MODE = "limitdown"
if "--base" in sys.argv:
    BASE_MODE = sys.argv[sys.argv.index("--base") + 1]


def main():
    stocks = lp.load_universe()
    lp.build_xsection(stocks)

    # 单遍收集：底座事件的组件位向量 + 对照池（同票 MA60下 非底座日）
    if BASE_MODE == "gaplow":   # 底座=缺口低开时，组件剔除同名避免恒真
        COMP.pop("缺口低开", None)
        NAMES.remove("缺口低开")
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
            if BASE_MODE == "limitdown":
                is_base = c[i] / c[i - 1] - 1 <= -0.095 and d["o"][i + 1] > c[i] * 0.905
            elif BASE_MODE == "touch":  # 触板未封底座（第三底座）
                is_base = lp._touch_not_seal(d, i) and d["o"][i + 1] > 0
            else:  # gaplow：缺口低开≥3%（次日开盘买入口径不变）
                is_base = lp._gap_down(d, i) and d["o"][i + 1] > 0
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
        return {h: stat([fwd(stocks[c], i, h) for c, i in idxs]) for h in HORIZONS}

    rng = random.Random(2026)
    # 底座基线 + 对照边际基线（全 horizon）
    base_all = [(c, i) for c, i, _ in events]
    baseH = evalset(base_all)
    ctrl_s = rng.sample(ctrl_pool, min(len(base_all), len(ctrl_pool)))
    ctrlH = evalset(ctrl_s)
    base_marg = {h: round(baseH[h]["mean%"] - ctrlH[h]["mean%"], 2) for h in HORIZONS}
    print("底座全horizon:", " ".join(
        f"T+{h} {baseH[h]['win%']}%/{baseH[h]['mean%']}%/赔{baseH[h]['赔率']}/边{base_marg[h]}" for h in HORIZONS), flush=True)

    out = {"底座": {"curve": baseH, "边际": base_marg, "对照curve": ctrlH}, "pairs": {}}

    singles = {}
    for k, nm in enumerate(NAMES):
        idxs = [(c, i) for c, i, m in events if m & (1 << k)]
        singles[nm] = {"curve": evalset(idxs), "idxs_len": len(idxs)}
        s5 = singles[nm]["curve"][5]
        print(f"  单件 {nm}: n={len(idxs)} T+5 {s5 and s5['win%']}%/{s5 and s5['mean%']}%", flush=True)
    out["singles"] = {k: {"curve": v["curve"]} for k, v in singles.items()}

    survivors = []
    for a, b in combinations(range(len(NAMES)), 2):
        na, nb = NAMES[a], NAMES[b]
        idxs = [(c, i) for c, i, m in events if (m & (1 << a)) and (m & (1 << b))]
        if len(idxs) < 200:
            continue
        pH = evalset(idxs)
        # 对照：同位置随机日（从对照池按事件数采样）
        import zlib as _z
        cs = random.Random(_z.crc32(f"{na}×{nb}".encode())).sample(ctrl_pool, min(len(idxs), len(ctrl_pool)))  # 红队S3：每对独立 seed
        ccH = evalset(cs)
        marg = {h: round(pH[h]["mean%"] - ccH[h]["mean%"], 2) for h in HORIZONS}
        p5 = pH[5]
        sa, sb = singles[na]["curve"][5], singles[nb]["curve"][5]
        beats_both = (sa is None or p5["mean%"] > sa["mean%"]) and (sb is None or p5["mean%"] > sb["mean%"])
        rec = {"n": len(idxs), "curve": pH, "边际": marg, "对照curve": ccH, "优于两单件": beats_both}
        out["pairs"][f"{na}×{nb}"] = rec
        flag = "✅" if (marg[5] > 0 and beats_both) else ""
        print(f"  {na}×{nb}: n={len(idxs)} T+5 {p5['win%']}%/{p5['mean%']}% 边T1 {marg[1]}/T5 {marg[5]}/T20 {marg[20]} {flag}", flush=True)
        if marg[5] > 0 and beats_both and p5["win%"] >= 55:
            survivors.append((na, nb))
    out["幸存待submit"] = survivors
    (ROOT / f"data/cross_matrix_{BASE_MODE}_20260919.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("幸存对:", survivors, flush=True)
    print("saved stage1", flush=True)

    # Stage 2：幸存对注册临时检测器走 submit 全闸门
    if survivors:
        regime = lp.load_regime()
        stock_cap, qs = lp.load_cap_quintiles()
        for na, nb in survivors:
            base_tag = {"limitdown": "跌停低", "gaplow": "缺口低开低", "touch": "触板低"}[BASE_MODE]
            name = f"交叉_{base_tag}_{na}_{nb}"
            base_det = {"limitdown": lp._limitdown, "gaplow": lp._gap_down, "touch": lp._touch_not_seal}[BASE_MODE]
            base_fn = lambda d, i: (d["ma60"][i] is not None and d["c"][i] <= d["ma60"][i]
                                    and base_det(d, i))
            lp.REGISTRY[name] = (lambda bf, fa, fb: lambda d, i: (
                bf(d, i) and fa(d, i) and fb(d, i)))(base_fn, COMP[na], COMP[nb])
            passed, v = lp.submit_gate(name, lp.REGISTRY[name], stocks, regime, stock_cap, qs)
            print(f"SUBMIT {name}: {'PASS' if passed else 'REJECT'}", flush=True)
            print(json.dumps(v, ensure_ascii=False)[:400], flush=True)


if __name__ == "__main__":
    main()
