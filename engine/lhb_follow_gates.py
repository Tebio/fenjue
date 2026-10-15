#!/usr/bin/env python3
"""engine/lhb_follow_gates.py — 席位跟随最强候选过 law_pipeline submit 六闸门+G7（2026-10-15）

候选来源：data/lhb_follow_study_20261015.json 逐席位排名，仅两只 T5/T20 边际为正：
  SIMING_BUY  思明南路净买入（T5 margC2 +1.9 / T20 +3.15，但 cal t_NW=0.5 预期 G1 死）
  DIWEI_BUY   低位挖掘净买入（T20 margC2 +2.14，T5 -0.48）
结构限制（诚实标注）：样本仅 2025-09-12..2026-10-15，G2 双段时间分段结构性不可能全绿，
另见主研究的窗内中点分段与日历时间 t_NW。
"""
import json, sys
from pathlib import Path

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

ROOT = Path("/opt/data/fenjue")
HT = ROOT / "data/hithink"
CANDS = {"SIMING_BUY": {"思明南路"}, "DIWEI_BUY": {"低位挖掘"}}


def build_events(names):
    ev = set()
    for ddir in sorted(HT.iterdir()):
        fh = ddir / "lhb_hot.json"
        if not fh.exists():
            continue
        for s in json.loads(fh.read_text())["data"].get("hot_money_items") or []:
            if s["name"] not in names:
                continue
            for r in s.get("rows") or []:
                if (r.get("hot_money_item_net_value") or 0) > 0:
                    ev.add((r["ticker"], ddir.name))
    return sorted(ev)


def main():
    stocks = lp.load_universe()
    print("stocks:", len(stocks), flush=True)
    # 探测器和闸门均不依赖横截面全局（_sig_idx 索引），跳过 build_xsection 防 OOM
    regime = lp.load_regime()
    stock_cap, qs = lp.load_cap_quintiles()
    results = {}
    for name, names in CANDS.items():
        evs = build_events(names)
        by_code = {}
        for code, dt in evs:
            by_code.setdefault(code, set()).add(dt)
        for code, d in stocks.items():
            dts = by_code.get(code)
            d["_sig_idx"] = {i for i, dt in enumerate(d["date"]) if dts and dt in dts} if dts else set()
        detect = lambda d, i: i in d["_sig_idx"]
        print(f"=== {name} events={len(evs)} ===", flush=True)
        passed, v = lp.submit_gate(name, detect, stocks, regime, stock_cap, qs)
        results[name] = v
        print(json.dumps({"判决": v["判决"], "闸门": v["闸门"],
                          "全样本": v["全样本"], "衰减T5": v["衰减曲线"].get("T+5"),
                          "位置匹配边际pp": v["位置匹配边际pp"], "日历时间DSR": v["日历时间DSR"],
                          "容量K1": v["容量"]["槽10_K1"]}, ensure_ascii=False), flush=True)
    dst = ROOT / "data/lhb_follow_gates_20261015.json"
    dst.write_text(json.dumps(results, ensure_ascii=False, indent=1, default=str))
    print("SAVED", dst)


if __name__ == "__main__":
    main()
