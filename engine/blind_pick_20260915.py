#!/usr/bin/env python3
"""blind_pick_20260915.py — 前向盲测出票机（2026-09-19 用户游戏立项）。

铁律：数据物理截断在 2026-09-15（周二）收盘，之后的数据在内存里不存在。
出票 = 9/15 收盘后各 G7 存活组合的命中票；买入约定 = 9/16（周三）开盘。
用户自验周三/后续收益，我不回填、不偷看。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import law_pipeline as lp

CUTOFF = "2026-09-15"

# 出战名单：全七闸 PASS 的组合（2026-09-18/19 submit）
SQUAD = [
    "组合_跌停低_长周期_超跌20",
    "组合_跌停低_三连阴",
    "组合_跌停低_缩量_剔亏ST",
    "组合_跌停低_避雷针_缩量",
    "组合_跌停低_输家_超跌20_剔亏ST",
    "组合_跌停低_TD9买入滤",
    "组合_跌停低_输家_超跌20_TD9滤",
]


def truncate(stocks, cutoff):
    out = {}
    for code, d in stocks.items():
        idx = [j for j, x in enumerate(d["date"]) if x <= cutoff]
        if len(idx) < 66:
            continue
        last = idx[-1]
        nd = {}
        for k, v in d.items():
            if isinstance(v, list) and len(v) == d["n"]:
                nd[k] = v[:last + 1]
            else:
                nd[k] = v
        nd["n"] = last + 1
        out[code] = nd
    return out


def main():
    stocks = lp.load_universe()
    stocks = truncate(stocks, CUTOFF)
    lp.build_xsection(stocks)   # 截断后重建横截面（Q20 等只用 ≤9/15 数据）
    picks = {}
    total_signals = 0
    for name in SQUAD:
        det = lp.REGISTRY[name]
        hits = []
        for code, d in stocks.items():
            i = d["n"] - 1
            if d["date"][i] != CUTOFF:
                continue
            try:
                if det(d, i):
                    hits.append(code)
            except Exception:
                pass
        total_signals += len(hits)
        if hits:
            picks[name] = hits
    # 成簇检查（容量纪律：当日全市场信号数）
    base_sigs = 0
    det0 = lp.REGISTRY["跌停接_MA60下"]
    for code, d in stocks.items():
        i = d["n"] - 1
        if d["date"][i] == CUTOFF:
            try:
                if det0(d, i):
                    base_sigs += 1
            except Exception:
                pass
    print(f"截止 {CUTOFF} 收盘（数据已物理截断，9/16+ 不存在于内存）")
    print(f"当日底座信号数（成簇判断）: {base_sigs}")
    print()
    for name, codes in picks.items():
        print(f"[{name}] {len(codes)} 只: {', '.join(codes)}")
    if not picks:
        print("无命中——空仓就是答案（没有合格信号不硬推）")
    Path("/opt/data/fenjue/data/blind_pick_20260915.json").write_text(
        json.dumps({"cutoff": CUTOFF, "base_signals": base_sigs, "picks": picks},
                   ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
