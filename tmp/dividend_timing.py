"""红利买点择时测试（2026-09-23，用户问「算不出买点卖点吗」）。

问题：股息锚买入区（TTM息率≥4.5%）裸进 vs 区内技术择时，谁的前瞻收益好？
变体：
  A 裸进：息率首次上穿 4.5%（出区再入才重新计）
  B 超卖进：区内 + RSI14<35
  C 贴线进：区内 + 收盘≤MA20×0.97
入场=信号次日开盘，T+20/60/120 收盘出，费 0.15%。宇宙=dividend_universe 115 只。
TTM 股息=除权日在过去 365 天的分红之和（时点口径，无未来函数）。
"""
import json
import statistics as st
import sys

sys.path.insert(0, "/opt/data/fenjue/engine")

ROOT = "/opt/data/fenjue"
FEE = 0.0015

div = json.load(open(f"{ROOT}/data/dividend_history.json"))
uni = json.load(open(f"{ROOT}/data/dividend_universe.json"))
codes = [r["code"] for r in uni["rows"]]
print(f"宇宙 {len(codes)}", flush=True)


def rsi(closes, i, n=14):
    if i < n:
        return None
    gains, losses = [], []
    for k in range(i - n + 1, i + 1):
        ch = closes[k] - closes[k - 1]
        gains.append(max(ch, 0))
        losses.append(max(-ch, 0))
    ag, al = st.mean(gains), st.mean(losses)
    if al == 0:
        return 100.0
    return 100 - 100 / (1 + ag / al)


import bisect

sigs = {"A": [], "B": [], "C": []}
for code in codes:
    kf = f"{ROOT}/data/big_kcache/{code}.json"
    try:
        ks = json.load(open(kf))
    except Exception:
        continue
    if len(ks) < 130:
        continue
    dates = [k["date"] for k in ks]
    closes = [float(k["close"]) for k in ks]
    opens = [float(k["open"]) for k in ks]
    divs = sorted(div.get(code, []))  # [ex_date, dps]
    div_dates = [d[0] for d in divs]
    n = len(ks)
    last_sig = {"A": -999, "B": -999, "C": -999}
    fired_zone = False
    for i in range(60, n - 121):
        # TTM 股息（除权日 ∈ (i-365, i]）
        lo = bisect.bisect_right(div_dates, dates[max(0, i - 365)])
        hi = bisect.bisect_right(div_dates, dates[i])
        ttm = sum(d[1] for d in divs[lo:hi])
        yld = ttm / closes[i] if closes[i] > 0 else 0
        zone = yld >= 0.045
        r = rsi(closes, i)
        ma20 = st.mean(closes[i - 19:i + 1])
        if not zone:
            fired_zone = False
            continue
        entry = opens[i + 1]
        if entry <= 0:
            continue
        conds = {"A": not fired_zone,  # 区内首日
                 "B": r is not None and r < 35,
                 "C": closes[i] <= ma20 * 0.97}
        for tag, ok in conds.items():
            if ok and i - last_sig[tag] > 120:
                sigs[tag].append({"code": code, "date": dates[i], "yld": yld,
                                  "t20": closes[i + 20] / entry - 1 - FEE,
                                  "t60": closes[i + 60] / entry - 1 - FEE,
                                  "t120": closes[i + 120] / entry - 1 - FEE})
                last_sig[tag] = i
        fired_zone = True

print("\n═══ 择时对比（信号次日开盘入，费后）═══")
for tag, lb in (("A", "A 裸进(息率上穿)"), ("B", "B 区内RSI<35"), ("C", "C 区内≤MA20×0.97")):
    rows = sigs[tag]
    if not rows:
        continue
    line = f"{lb:<16} n={len(rows):>4}"
    for h in ("t20", "t60", "t120"):
        xs = [r[h] for r in rows]
        wr = sum(1 for x in xs if x > 0) / len(xs)
        line += f" | T+{h[1:]} {wr * 100:.0f}%/{st.mean(xs) * 100:+.2f}%"
    print(line)

json.dump({k: v for k, v in sigs.items()}, open(f"{ROOT}/data/dividend_timing_20260923.json", "w"))
print("\nsaved data/dividend_timing_20260923.json")
