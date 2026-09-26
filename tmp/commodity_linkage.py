"""商品价格突破→资源股联动（2026-09-26 晚，BACKLOG#16，洛阳钼业型）。

信号：商品主力连续收盘创 20 日新高（或 60 日新高）；次日开盘买映射股票；T+5/20/60 收盘出，费 0.15%。
映射（只留干净链）：CU0→紫金/江西铜业/铜陵/洛钼；AL0→中铝/云铝/南山；AU0→山东黄金/中金黄金/紫金；
SC0→中石油/中石化/海油；LC0→天齐/赣锋；NI0→华友；SR0→中粮糖业；ZN0→驰宏锌锗；AG0→兴业银锡。
对照：同股票无信号日。分层：分品种/分年/regime。剔信号日重叠（同票同日多品种只记一次）。
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
regime = lp.load_regime()

MAP = {
    "CU0": ["601899", "600362", "000630", "603993"],
    "AL0": ["601600", "000807", "600219"],
    "AU0": ["600547", "600489", "601899"],
    "SC0": ["601857", "600028", "600938"],
    "LC0": ["002466", "002460"],
    "NI0": ["603799"],
    "SR0": ["600737"],
    "ZN0": ["600497"],
    "AG0": ["000426"],
}

events = []
for sym, codes in MAP.items():
    try:
        cd = json.load(open(f"{ROOT}/data/commodity/{sym}.json"))
    except Exception:
        continue
    rows = cd["rows"]
    for i in range(60, len(rows) - 1):
        dt = rows[i]["date"]
        c20 = max(r["close"] for r in rows[i - 20:i])
        c60 = max(r["close"] for r in rows[max(0, i - 60):i]) if i >= 61 else None
        hi20 = rows[i]["close"] > c20 and rows[i - 1]["close"] <= max(r["close"] for r in rows[i - 21:i - 1])
        hi60 = bool(c60) and rows[i]["close"] > c60 and rows[i - 1]["close"] <= max(r["close"] for r in rows[i - 61:i - 1])
        if not (hi20 or hi60):
            continue
        for code in codes:
            d = stocks.get(code)
            if not d or dt not in d["date"]:
                continue
            si = d["date"].index(dt)
            if si + 61 >= d["n"] or d["o"][si + 1] <= 0:
                continue
            entry = d["o"][si + 1]
            events.append({"sym": sym, "code": code, "date": dt, "hi60": hi60,
                           "t5": d["c"][si + 5] / entry - 1 - FEE,
                           "t20": d["c"][si + 20] / entry - 1 - FEE,
                           "t60": d["c"][si + 60] / entry - 1 - FEE,
                           "rg": regime.get(dt, "?")})
# 去重：同票同日多品种只留一个
seen = set()
dedup = []
for e in events:
    k = (e["code"], e["date"])
    if k in seen:
        continue
    seen.add(k)
    dedup.append(e)
events = dedup
print(f"事件 {len(events)}", flush=True)

# 对照：同票无信号日（抽样 3 万）
import random
random.seed(7)
ctrl = []
codes_all = list({c for codes in MAP.values() for c in codes})
sig_days = {(e["code"], e["date"]) for e in events}
for code in codes_all:
    d = stocks.get(code)
    if not d:
        continue
    for _ in range(2000):
        i = random.randint(61, d["n"] - 62)
        if d["o"][i + 1] <= 0 or (code, d["date"][i]) in sig_days:
            continue
        entry = d["o"][i + 1]
        ctrl.append({"t5": d["c"][i + 5] / entry - 1 - FEE,
                     "t20": d["c"][i + 20] / entry - 1 - FEE,
                     "t60": d["c"][i + 60] / entry - 1 - FEE})
        if len(ctrl) >= 30000:
            break
    if len(ctrl) >= 30000:
        break


def blk(rows, lb):
    if len(rows) < 15:
        print(f"  {lb}: n={len(rows)} 不足")
        return
    line = f"  {lb:<20} n={len(rows):>5}"
    for h in ("t5", "t20", "t60"):
        xs = [r[h] for r in rows]
        wr = sum(1 for x in xs if x > 0) / len(xs)
        line += f" | {h.upper()} {wr * 100:5.1f}%/{st.mean(xs) * 100:+5.2f}%"
    print(line)


blk(ctrl, "对照(同票无信号日)")
blk(events, "全部突破信号")
blk([e for e in events if e["hi60"]], "60日新高（更强）")
blk([e for e in events if not e["hi60"]], "仅20日新高")
print("\n分品种:")
for sym in MAP:
    blk([e for e in events if e["sym"] == sym], sym)
print("\n分年:")
for y in ("2020", "2021", "2022", "2023", "2024", "2025", "2026"):
    blk([e for e in events if e["date"][:4] == y], f"{y}年")
print("\nregime:")
for g in ("主线期", "妖股期", "平淡期", "恐慌期"):
    blk([e for e in events if e["rg"] == g], g)
json.dump(events, open(f"{ROOT}/data/commodity_linkage_20260926.json", "w"), ensure_ascii=False)
print("\nsaved data/commodity_linkage_20260926.json")
