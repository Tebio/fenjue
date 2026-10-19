#!/usr/bin/env python3
"""金股时点结构研究（2026-10-19 用户「时间节点你要看金股的最高点：9月出票之前都有最高点和最低点」）。

回答三个问题，全部 PIT 口径（沿用 gold_pit_study.py 的月份修正）：
1. **出票点在哪**：出票价相对「出票前 60 日高」的位置，以及它落在「前高 → 买入后 20 日低点」
   这个区间的几分位（0=前高，1=后低）。用来判断券商出票时点本身有没有择时优势。
2. **后低/后高什么时候出现**：买入后 20 日内最低点、最高点分别出现在第几个交易日（中位）。
3. **出货规则有没有用**：持有到 T+1..T+20 的均值曲线、止盈 +2%/+3%/+5% 即卖、以及
   「完美抄在后低」「完美出在后高」两个上界（后者是择时天花板，不是可执行收益）。

用法：.venv/bin/python engine/gold_timing_study.py
"""
import collections
import glob
import json
import statistics as st
import sys

sys.path.insert(0, "/opt/data/fenjue/engine")
sys.path.insert(0, "/opt/data/python-libs")
import law_pipeline as lp
import trade_calendar as tc

ROOT = "/opt/data/fenjue"
FEE = 0.0015


def cohorts():
    rows = []
    for fp in glob.glob(f"{ROOT}/data/gold_raw/*.json"):
        rows += json.load(open(fp))
    combos = collections.defaultdict(lambda: collections.defaultdict(set))
    seen = set()
    for r in rows:
        c = str(r["股票代码"]).split(".")[0].zfill(6)
        if c[:2] not in ("60", "00"):
            continue
        ct = str(r["组合时间"])[:6]
        ann = str(r["公告日期"])
        k = (c, r["研究机构"], ann, ct)
        if k in seen:
            continue
        seen.add(k)
        combos[f"{ct[:4]}-{ct[4:]}"][c].add(ann)
    return combos


def month_days(mo):
    return [d for d in (tc.trading_days(int(mo[:4])) or []) if d.startswith(mo)]


def collect(U, combos, mo):
    days = month_days(mo)
    if len(days) < 7:
        return None, []
    entry = days[5]
    out = []
    for c, anns in combos[mo].items():
        if min(anns) > entry.replace("-", ""):
            continue
        d = U.get(c)
        if not d or entry not in d["date"]:
            continue
        j = d["date"].index(entry)
        if j < 25 or j + 20 >= d["n"] or d["o"][j] <= 0:
            continue
        e = d["o"][j]
        h60 = max(d["h"][max(0, j - 60):j + 1])
        lows = [d["l"][j + k] for k in range(1, 21)]
        highs = [d["h"][j + k] for k in range(1, 21)]
        low, hi = min(lows), max(highs)
        out.append({
            "code": c, "entry": e, "h60": h60, "low": low, "hi": hi,
            "days_to_low": lows.index(low) + 1, "days_to_hi": highs.index(hi) + 1,
            "pos": (e - h60) / (low - h60) if h60 > low else None,
            "mae": low / e - 1, "mfe": hi / e - 1,
            "r20": d["c"][j + 20] / e - 1 - FEE,
            "path": [d["c"][j + k] / e - 1 - FEE for k in range(1, 21)],
        })
    return entry, out


def main():
    U = lp.load_universe()
    combos = cohorts()
    for mo in sorted(combos):
        entry, rows = collect(U, combos, mo)
        if not rows or len(rows) < 10:
            continue
        n = len(rows)
        print(f"\n═══ 组合 {mo}  n={n}  入场 {entry} ═══")
        pos = [r["pos"] for r in rows if r["pos"] is not None]
        print(f"  出票价 距前60日高: 中位 {st.median([r['entry']/r['h60']-1 for r in rows])*100:+.1f}%")
        print(f"  出票点在前高→后低区间的位置: 中位 {st.median(pos)*100:.0f}%"
              f"（25/{50}/75 分位 {st.quantiles(pos, n=4)[0]*100:.0f}/{st.median(pos)*100:.0f}/{st.quantiles(pos, n=4)[2]*100:.0f}%）"
              f"，落在上半段占 {sum(1 for x in pos if x > 0.5)/len(pos)*100:.0f}%")
        print(f"  前高→后低 全段回撤: 中位 {st.median([r['low']/r['h60']-1 for r in rows])*100:+.1f}%")
        print(f"  买入后最低点: 中位 {st.median([r['mae'] for r in rows])*100:+.1f}%，出现在 T+{st.median([r['days_to_low'] for r in rows]):.0f}")
        print(f"  买入后最高点: 中位 {st.median([r['mfe'] for r in rows])*100:+.1f}%，出现在 T+{st.median([r['days_to_hi'] for r in rows]):.0f}")
        print(f"  实际 T+20: {st.mean([r['r20'] for r in rows])*100:+.2f}%/胜{sum(1 for r in rows if r['r20']>0)/n*100:.0f}%"
              f"  |  完美抄在后低持20日: {st.mean([r['r20']+ (r['entry']/r['low']-1) for r in rows])*100:+.2f}%"
              f"  |  完美出在后高: {st.mean([r['mfe'] for r in rows])*100:+.2f}%")
        best = max(range(20), key=lambda k: st.mean([r["path"][k] for r in rows]))
        print(f"  持有期均值最好的卖出日: T+{best+1}（{st.mean([r['path'][best] for r in rows])*100:+.2f}%）")
        for thr in (0.02, 0.03, 0.05):
            gains = []
            for r in rows:
                hit = next((i for i in range(20) if r["path"][i] >= thr), None)
                gains.append(r["path"][hit] if hit is not None else r["r20"])
            print(f"    止盈 +{thr*100:.0f}% 即卖(否则持到T+20): 均值 {st.mean(gains)*100:+.2f}%"
                  f"/胜率 {sum(1 for x in gains if x > 0)/len(gains)*100:.0f}%")


if __name__ == "__main__":
    main()
