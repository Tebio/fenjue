#!/usr/bin/env python3
"""engine/seat_gene_gates.py — 席位信号过 law_pipeline 标准闸门（2026-09-12）

复用 law_pipeline 全套（双段/regime/市值五分位/成本/日历时间/DSR/位置匹配边际），
席位事件表达为 detect（d["_sig_idx"] 索引集合），与形态族/Sequoia-X 同标准。
结构限制（诚实标注）：席位数据仅 1 年深，管线 L2_时间分段（2019-2022 vs 2023-2026）
必然 ❌——另报窗内中点分段（2026-03-12）作为替代时效检验。
信号组：
  ORG_BUY      机构净买入（lhb_org org_net_value>0）
  GEJU_BUY     格局型席位净买入（章盟主/成都系/中山东路/思明南路）
  SHOUGE_BUY   收割型席位净买入（T王/山东帮）
  ZHANG_BUY    章盟主净买入（单独）
"""
import json, sys, statistics as st
from pathlib import Path

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

ROOT = Path("/opt/data/fenjue")
HT = ROOT / "data/hithink"
GEJU = {"章盟主", "成都系", "中山东路", "思明南路"}
SHOUGE = {"T王", "山东帮"}
MID = "2026-03-12"


def build_events():
    ev = {"ORG_BUY": set(), "GEJU_BUY": set(), "SHOUGE_BUY": set(), "ZHANG_BUY": set()}
    for ddir in sorted(HT.iterdir()):
        fo = ddir / "lhb_org.json"
        if fo.exists():
            for r in json.loads(fo.read_text())["data"].get("stock_items") or []:
                if (r.get("org_net_value") or 0) > 0:
                    ev["ORG_BUY"].add((r["ticker"], ddir.name))
        fh = ddir / "lhb_hot.json"
        if fh.exists():
            for seat in json.loads(fh.read_text())["data"].get("hot_money_items") or []:
                nm = seat["name"]
                for r in seat.get("rows") or []:
                    if (r.get("hot_money_item_net_value") or 0) <= 0:
                        continue
                    key = (r["ticker"], ddir.name)
                    if nm in GEJU:
                        ev["GEJU_BUY"].add(key)
                    if nm in SHOUGE:
                        ev["SHOUGE_BUY"].add(key)
                    if nm == "章盟主":
                        ev["ZHANG_BUY"].add(key)
    return {k: sorted(v) for k, v in ev.items()}


def midpoint_split(stocks, events, horizon=5, fee=0.0015):
    """窗内中点分段（1年深数据的时效替代检验）。"""
    idx = {}
    for code, d in stocks.items():
        idx[code] = {dt: i for i, dt in enumerate(d["date"])}
    a, b = [], []
    for code, dt in events:
        d = stocks.get(code)
        if not d:
            continue
        i = idx[code].get(dt)
        if i is None or i + horizon >= d["n"] or d["o"][i+1] <= 0:
            continue
        r = d["c"][i + horizon] / d["o"][i + 1] - 1 - fee
        (a if dt < MID else b).append(r)
    return {seg: ({"n": len(v), "mean%": round(100*st.mean(v), 2),
                   "win%": round(100*sum(x > 0 for x in v)/len(v), 1)} if v else None)
            for seg, v in [("H1", a), ("H2", b)]}


def main():
    events = build_events()
    print({k: len(v) for k, v in events.items()}, flush=True)
    stocks = lp.load_universe()
    regime = lp.load_regime()
    stock_cap, qs = lp.load_cap_quintiles()
    results = {}
    for name, evs in events.items():
        by_code = {}
        for code, dt in evs:
            by_code.setdefault(code, set()).add(dt)
        for code, d in stocks.items():
            dts = by_code.get(code)
            d["_sig_idx"] = {i for i, dt in enumerate(d["date"]) if dts and dt in dts} if dts else set()
        detect = lambda d, i: i in d["_sig_idx"]
        print(f"=== {name} ===", flush=True)
        res = lp.run_pipeline(name, detect, stocks, regime, stock_cap, qs)
        res["matched_marginal_pp"] = lp.matched_marginal(detect, stocks, [1, 5, 20])
        res["midpoint_split_T5"] = midpoint_split(stocks, evs)
        results[name] = res
        print(json.dumps({"n": res.get("n"), "edge_pp": res.get("edge_pp"),
                          "decay_T1": res.get("decay", {}).get("T+1"),
                          "decay_T5": res.get("decay", {}).get("T+5"),
                          "matched": res["matched_marginal_pp"],
                          "mid_T5": res["midpoint_split_T5"],
                          "verdict": res.get("verdict")}, ensure_ascii=False), flush=True)
    (ROOT / "data/seat_gene_gates_20260912.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1, default=str))
    print("SAVED data/seat_gene_gates_20260912.json")


if __name__ == "__main__":
    main()
