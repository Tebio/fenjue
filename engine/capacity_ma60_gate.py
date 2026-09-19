#!/usr/bin/env python3
"""capacity_ma60_gate.py — MA60 回收出场的 G7 容量检验（2026-09-19）。

昨晚 exit_rule_grid 发现 ma60_out 在 6 个存活信号上全胜 fixed_5，但那是事件研究口径
（假设无限资金）。本脚本用 capacity_sim 槽位资金曲线验证：持有期 12-17 天的规则在
容量约束下是否还能赚钱（长持有=槽位占用久=容量更紧张，必须单独验）。
对照：同信号 fixed_5（hold=5）K1/K5 vs ma60 K1/K5。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import law_pipeline as lp

ROOT = Path(__file__).resolve().parent.parent

SIGNALS = [
    "组合_跌停低_长周期_超跌20",
    "组合_跌停低_三连阴",
    "跌停接_MA60下_缩量",
    "组合_跌停低_输家_超跌20_剔亏ST",
    "组合_跌停低_TD9买入滤",
]


def main():
    stocks = lp.load_universe()
    lp.build_xsection(stocks)
    out = {}
    for name in SIGNALS:
        det = lp.REGISTRY.get(name)
        if det is None:
            print(f"[skip] {name}")
            continue
        sigs = lp._collect_sigs(det, stocks)
        rec = {"事件日数": len(sigs)}
        for tag, xr, ck in [("fixed5_K1", None, 1), ("fixed5_K5", None, 5),
                            ("ma60_K1", "ma60", 1), ("ma60_K5", "ma60", 5)]:
            r = lp.capacity_sim(sigs, stocks, slots=10, hold=5, exit_rule=xr, cluster_k=ck)
            rec[tag] = r
        out[name] = rec
        f5, m5 = rec["fixed5_K1"], rec["ma60_K1"]
        print(f"{name}: fixed5_K1 年化{f5['年化%']}%/均笔{f5['均笔%']}%  vs  "
              f"ma60_K1 年化{m5['年化%']}%/均笔{m5['均笔%']}%/回撤{m5['回撤%']}%", flush=True)
        print(f"   K5: fixed5 {rec['fixed5_K5']['年化%']}%  vs  ma60 {rec['ma60_K5']['年化%']}%", flush=True)
    dst = ROOT / "data/capacity_ma60_gate_20260919.json"
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("saved", dst)


if __name__ == "__main__":
    main()
