#!/usr/bin/env python3
"""engine/downtrend_raid8.py — 下跌中继突袭：正式走 law_pipeline.submit_gate 六闸门 + G7（stage 8）

用仓库**真实**生产闸门函数（lp.run_pipeline / lp.matched_marginal / lp.capacity_sim），
在同一份紧凑宇宙上跑，市值用月度 PIT 适配器（月键 'YYYY-MM-01' 存上月末值，
qs 键 'YYYY-MM' 存上月横截面分位 → 与 law_pipeline.cap_at_date/cap_quintile 语义一致）。
"""
import json
import sys
import statistics as st
from collections import defaultdict

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp
from downtrend_raid import (ROOT, load_compact, load_cap_month, downtrend_ctx,
                            raid_big7, raid_limitup, START)


def main():
    stocks, cal = load_compact()
    print("stocks:", len(stocks), flush=True)
    regime = lp.load_regime()
    packed, qs0 = load_cap_month(stocks)
    stock_cap = {c: (k, v) for c, (k, v) in packed.items()}          # 月键 'YYYY-MM-01'
    qs = {k[:7]: v for k, v in qs0.items()}                            # 'YYYY-MM'
    print("cap=%d qs=%d" % (len(stock_cap), len(qs)), flush=True)

    for name, det in (("下跌中继_大涨7", raid_big7), ("下跌中继_涨停", raid_limitup)):
        print("\n" + "=" * 78, flush=True)
        print("== %s ==" % name, flush=True)
        passed, v = lp.submit_gate(name, det, stocks, regime, stock_cap, qs)
        print("判决:", v["判决"], flush=True)
        print("闸门:", json.dumps(v["闸门"], ensure_ascii=False), flush=True)
        print("全样本:", json.dumps(v["全样本"], ensure_ascii=False), flush=True)
        print("随机对照:", json.dumps(v["随机对照"], ensure_ascii=False), flush=True)
        print("衰减曲线:", flush=True)
        for h, s in v["衰减曲线"].items():
            print("   %-5s n=%-5d win=%5.1f%% mean=%+6.2f%% t=%5s t_NW=%5s 过Harvey=%s" % (
                h, s["n"], s["win%"], s["mean%"], s["t"], s.get("t_NW"), s.get("过Harvey门槛")), flush=True)
        print("时间分段:", json.dumps(v["时间分段"], ensure_ascii=False), flush=True)
        print("regime分段:", json.dumps(v["regime分段"], ensure_ascii=False), flush=True)
        print("市值五分位(闸门内已算):", json.dumps(v["闸门"].get("G4_市值≥4/5"), ensure_ascii=False), flush=True)
        print("成本压力: 见 data/downtrend_raid_gate_*.json（verdict 未回传该字段）", flush=True)
        print("位置匹配边际pp:", json.dumps(v["位置匹配边际pp"], ensure_ascii=False), flush=True)
        print("日历时间DSR:", v["日历时间DSR"], flush=True)
        print("容量:", json.dumps(v["容量"], ensure_ascii=False), flush=True)
        print("每票每年触发:", v["每票每年触发"], flush=True)
        (ROOT / ("data/downtrend_raid_gate_%s.json" % ("big7" if det is raid_big7 else "lu"))) \
            .write_text(json.dumps(v, ensure_ascii=False, indent=1, default=str))
    print("saved gate verdicts")


if __name__ == "__main__":
    main()
