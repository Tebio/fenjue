#!/usr/bin/env python3
"""y2026_check.py — 2026 单年胜率实测（2026-09-19 用户点名）。

对存活主张跑 2026 年仅含当年事件的 T+1/T+5（next_open、净-0.15%、剔一字跌停买不进）。
警告：2026 年恐慌日少，组合 n 小；这是「当前还活着吗」的体温计，不是新判决。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import law_pipeline as lp

SQUAD = ["跌停接_MA60下", "跌停接_MA60下_缩量", "组合_跌停低_长周期_超跌20", "组合_跌停低_三连阴",
         "组合_跌停低_避雷针_缩量", "组合_跌停低_缩量_剔亏ST", "组合_跌停低_输家_超跌20_剔亏ST",
         "组合_跌停低_TD9买入滤", "组合_跌停低_输家_超跌20_TD9滤",
         "组合_缺口低开_低位阳线", "组合_触板未封_低位", "组合_跌停低_避雷针低位",
         "组合_跌停低_输家_超跌20_缩量", "组合_跌停低_三连阴_缩量"]
FEE = 0.0015


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
            "mean%": round(100 * sum(rs) / len(rs), 2),
            "赔率": round(odds, 2) if odds else None}


HORIZONS = (1, 2, 3, 5, 10, 20)  # 2026-09-19 用户批评「只出 T+5」→ 全 horizon 胜率+赔率


def main():
    stocks = lp.load_universe()
    lp.build_xsection(stocks)
    out = {}
    for name in SQUAD:
        det = lp.REGISTRY.get(name)
        if not det:
            continue
        rs = {h: [] for h in HORIZONS}
        for code, d in stocks.items():
            for i in range(61, d["n"] - 21):
                if d["date"][i] < "2026-01-01":
                    continue
                try:
                    if det(d, i):
                        for h in HORIZONS:
                            rs[h].append(fwd(d, i, h))
                except Exception:
                    pass
        out[name] = {f"T+{h}": stat(rs[h]) for h in HORIZONS}
        line = f"{name}:"
        for h in HORIZONS:
            s = out[name][f"T+{h}"]
            if s:
                line += f"  T+{h} {s['win%']}%/{s['mean%']}%/赔{s['赔率']}"
        print(line, flush=True)
    (ROOT := Path(__file__).resolve().parent.parent)
    (ROOT / "data/y2026_check_20260919.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("saved")


if __name__ == "__main__":
    main()
