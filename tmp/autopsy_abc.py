"""分年验尸三件套（2026-09-26 凌晨，用户「还有没有查不仔细的」——B5 金格教训回马枪）。

A 深档 T+10（已进生产！）：60 生产批分年批级胜率/均值——2024 集中度？
B 土壤门（已进生产！）：真恐慌批+假恐慌批的分年收益（之前只给了假恐慌的批数没给收益）
C 红利择时 B/C（委托单口径已改）：RSI<35/≤MA20×0.97 买入区 T+120 分年
"""
import collections
import json
import statistics as st
import sys

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

ROOT = "/opt/data/fenjue"
FEE = 0.0015
stocks = lp.load_universe()
idx_data = json.load(open(f"{ROOT}/data/index_sh000001.json"))
idx_map = {k["date"]: float(k["close"]) for k in idx_data}
idx_dates = sorted(idx_map)
idx_ma20 = {}
for k, dt in enumerate(idx_dates):
    if k >= 19:
        idx_ma20[dt] = sum(idx_map[idx_dates[k - 19 + j]] for j in range(20)) / 20

# ══ A+B：生产批（簇≥5 深跌≤-35% 前5）分年 × T+10 × 土壤 ══
cluster = collections.Counter()
events = []
for code, d in stocks.items():
    if code[:2] not in ("60", "00"):
        continue
    n = d["n"]
    for i in range(60, n - 11):
        if d["c"][i - 1] <= 0 or d["o"][i + 1] <= 0:
            continue
        ma = d["ma60"][i]
        if not ma:
            continue
        pct = d["c"][i] / d["c"][i - 1] - 1
        if pct <= -0.095 and d["c"][i] <= ma * 0.75:
            cluster[d["date"][i]] += 1
            if d["c"][i] <= ma * 0.65:
                events.append({"date": d["date"][i], "depth": d["c"][i] / ma - 1,
                               "t10": d["c"][i + 10] / d["o"][i + 1] - 1 - FEE})
prod = {d for d, k in cluster.items() if k >= 5}
by_day = collections.defaultdict(list)
for e in events:
    if e["date"] in prod:
        by_day[e["date"]].append(e)

batches = []
for dt, evs in by_day.items():
    p = sorted([e for e in evs if e["depth"] <= -0.35], key=lambda x: x["depth"])[:5]
    if p:
        batches.append({"date": dt, "ret": st.mean(e["t10"] for e in p),
                        "soil": idx_map.get(dt, 0) <= idx_ma20.get(dt, 0)})

print("═══ A 深档 T+10 批级分年 ═══")
for y in sorted({b["date"][:4] for b in batches}):
    xs = [b["ret"] for b in batches if b["date"][:4] == y]
    wr = sum(1 for x in xs if x > 0) / len(xs)
    print(f"  {y}: 批数{len(xs):>3} {wr * 100:3.0f}%/{st.mean(xs) * 100:+5.2f}%")
n24 = sum(1 for b in batches if b["date"][:4] == "2024")
print(f"  2024 批数占比: {n24}/{len(batches)} = {n24 / len(batches) * 100:.0f}%")

print("\n═══ B 土壤门分年（真/假恐慌批各自收益） ═══")
for soil_v, lb in ((True, "真恐慌"), (False, "假恐慌")):
    print(f"  {lb}:")
    for y in sorted({b["date"][:4] for b in batches if b["soil"] == soil_v}):
        xs = [b["ret"] for b in batches if b["date"][:4] == y and b["soil"] == soil_v]
        if xs:
            wr = sum(1 for x in xs if x > 0) / len(xs)
            print(f"    {y}: 批数{len(xs):>3} {wr * 100:3.0f}%/{st.mean(xs) * 100:+5.2f}%")

# ══ C：红利择时分年 ══
print("\n═══ C 红利择时（买入区内 RSI14<35）T+120 分年 ═══")
import bisect
div = json.load(open(f"{ROOT}/data/dividend_history.json"))
uni = json.load(open(f"{ROOT}/data/dividend_universe.json"))
codes = [r["code"] for r in uni["rows"]]


def rsi(closes, i, n=14):
    if i < n:
        return None
    gains, losses = [], []
    for k in range(i - n + 1, i + 1):
        ch = closes[k] - closes[k - 1]
        gains.append(max(ch, 0))
        losses.append(max(-ch, 0))
    al = st.mean(losses)
    if al == 0:
        return 100.0
    return 100 - 100 / (1 + st.mean(gains) / al)


by_year_c = collections.defaultdict(list)
for code in codes:
    try:
        ks = json.load(open(f"{ROOT}/data/big_kcache/{code}.json"))
    except Exception:
        continue
    if len(ks) < 130:
        continue
    dates = [k["date"] for k in ks]
    closes = [float(k["close"]) for k in ks]
    opens = [float(k["open"]) for k in ks]
    divs = sorted(div.get(code, []))
    div_dates = [x[0] for x in divs]
    last_sig = -999
    for i in range(60, len(ks) - 121):
        lo = bisect.bisect_right(div_dates, dates[max(0, i - 365)])
        hi = bisect.bisect_right(div_dates, dates[i])
        ttm = sum(x[1] for x in divs[lo:hi])
        if closes[i] <= 0 or ttm / closes[i] < 0.045:
            continue
        r = rsi(closes, i)
        if r is None or r >= 35 or i - last_sig <= 120 or opens[i + 1] <= 0:
            continue
        last_sig = i
        by_year_c[dates[i][:4]].append(closes[i + 120] / opens[i + 1] - 1 - FEE)
for y in sorted(by_year_c):
    xs = by_year_c[y]
    if len(xs) >= 10:
        wr = sum(1 for x in xs if x > 0) / len(xs)
        print(f"  {y}: n={len(xs):>4} {wr * 100:5.1f}%/{st.mean(xs) * 100:+5.2f}%")
