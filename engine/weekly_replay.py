#!/usr/bin/env python3
"""weekly_replay.py — 本周（9/14-9/18）新管道全回放（2026-09-19 用户令）。

每个交易日收盘后按执行链出票：
  成簇判定（底座信号≥3 或 全市场跌停≥100）→ 旗舰组合命中去重 → 超跌最深排序取前3
  → 次日 10:30 价（m60 bar 收盘；缺 bar 回退次日开盘）
T+1 验证列由用户自查；结果列落盘供赛后对账（不展示）。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import law_pipeline as lp

ROOT = Path(__file__).resolve().parent.parent
WEEK = ["2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18"]
SQUAD = ["组合_跌停低_三连阴_深跌", "组合_跌停低_深跌_跌停潮", "组合_跌停低_深跌",
         "组合_跌停低_三连阴", "组合_跌停低_长周期_超跌20", "组合_跌停低_TD9买入滤"]


def truncate(stocks, cutoff):
    out = {}
    for code, d in stocks.items():
        idx = [j for j, x in enumerate(d["date"]) if x <= cutoff]
        if len(idx) < 66:
            continue
        last = idx[-1]
        nd = {}
        for k, v in d.items():
            nd[k] = v[:last + 1] if isinstance(v, list) and len(v) == d["n"] else v
        nd["n"] = last + 1
        out[code] = nd
    return out


def next_day(dates_all, day):
    for x in sorted(dates_all):
        if x > day:
            return x
    return None


def main():
    stocks_full = lp.load_universe()
    lp.build_xsection(stocks_full)
    all_dates = sorted({x for s in stocks_full.values() for x in s["date"]})
    m60_cache = {}

    def entry_1030(code, day):
        if code not in m60_cache:
            fp = ROOT / f"data/m60_cache/{code}.json"
            m60_cache[code] = None
            if fp.exists():
                bars = {}
                for b in json.loads(fp.read_text()):
                    bars.setdefault(b["day"][:10], []).append(b)
                m60_cache[code] = bars
        bars = (m60_cache[code] or {}).get(day)
        if bars:
            b0 = [b for b in bars if b["day"][11:16] == "10:30"]
            if b0:
                return float(b0[0]["close"]), "10:30bar"
        d = stocks_full.get(code)
        if d:
            idx = {x: j for j, x in enumerate(d["date"])}
            j = idx.get(day)
            if j is not None:
                return d["o"][j], "次日开盘(回退)"
        return None, None

    report = {}
    for day in WEEK:
        st = truncate(stocks_full, day)
        # 截断宇宙的横截面（QD/跌停数用当日前数据）
        ldc_today = sum(1 for code, d in st.items()
                        if d["n"] >= 2 and d["c"][-1] > 0 and d["c"][-2] > 0
                        and d["c"][-1] / d["c"][-2] - 1 <= -0.095)
        base_hits, combo_hits = [], {}
        for code, d in st.items():
            i = d["n"] - 1
            if d["date"][i] != day:
                continue
            ma = d["ma60"][i]
            if ma is None or d["c"][i] <= 0 or d["c"][i - 1] <= 0:
                continue
            if d["c"][i] / d["c"][i - 1] - 1 <= -0.095 and d["c"][i] <= ma:
                base_hits.append(code)
            for sig in SQUAD:
                try:
                    if lp.REGISTRY[sig](d, i):
                        combo_hits.setdefault(code, []).append(sig)
                except Exception:
                    pass
        fired = len(base_hits) >= 3 or ldc_today >= 100
        rec = {"底座信号": len(base_hits), "全市场跌停": ldc_today, "成簇出手": fired, "picks": []}
        if fired and combo_hits:
            # 深跌排序（距MA60最远）
            ranked = sorted(combo_hits.items(),
                            key=lambda kv: st[kv[0]]["c"][-1] / st[kv[0]]["ma60"][-1] - 1)
            nd = next_day(all_dates, day)
            for code, sigs in ranked[:3]:
                px, how = entry_1030(code, nd) if nd else (None, None)
                rec["picks"].append({"code": code, "combos": sigs, "深度%": round(
                    (st[code]["c"][-1] / st[code]["ma60"][-1] - 1) * 100, 1),
                    "信号日": day, "入场日": nd, "入场价": px, "口径": how})
        report[day] = rec
        print(f"\n=== {day} 收盘：底座信号 {len(base_hits)} | 全市场跌停 {ldc_today} | {'🔥成簇出手' if fired else '静默（空仓是答案）'}")
        for p in rec["picks"]:
            print(f"  → {p['code']} 深度{p['深度%']}% 命中{len(p['combos'])}组合 | {p['入场日']} 入场参考价 {p['入场价']}（{p['口径']}）")

    (ROOT / "data/weekly_replay_20260914_0918.json").write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print("\nsaved data/weekly_replay_20260914_0918.json")


if __name__ == "__main__":
    main()
