"""信号日 10:30 上车 vs 次日开盘（2026-09-22，用户问「为什么买点不在10:30」——不辩，测）。

三组家族，m60 硬窗（2024-08-30+，两年）：
  F1 深档深跌件：官方=收≤-9.5%且收≤MA60×0.65（簇≥5）；10:30变体=10:30 bar收≤昨收×0.905且≤MA60est×0.65
  F2 缺口低巨簇：10:30代理簇（低开≥3%+现价≥开+价≤MA60est）≥20 → 10:30买 vs 官方簇≥20 → 次日开盘
  F3 缺口低 ≥8 簇同构
关键分解：
  - 10:30 信号里「收盘被官方确认」vs「假阳性」（10:30 像、收盘不像）——代理终局成本
  - 官方确认事件在信号日下午（10:30→收盘）的平均走势——10:30 提前上车吃到的是肉还是刀
  - 一字锁死（bar高=bar低且收≈跌停）不可买剔除
出场对齐：信号日+1/+3/+5 收盘（两口径同标尺），费 0.15%。
"""
import collections
import glob
import json
import math
import statistics as st
import sys

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

ROOT = "/opt/data/fenjue"
FEE = 0.0015
W0 = "2024-08-30"

stocks = lp.load_universe()
regime = lp.load_regime()
for d in stocks.values():
    d["_didx"] = {x: j for j, x in enumerate(d["date"])}
print("universe", len(stocks), flush=True)

m60 = {}
def bars(code):
    if code not in m60:
        try:
            ks = json.load(open(f"{ROOT}/data/m60_cache/{code}.json"))
            by = {}
            for b in ks:
                by.setdefault(b["day"][:10], {})[b["day"][11:16]] = b
            m60[code] = by
        except Exception:
            m60[code] = {}
    return m60[code]


def blk(rs):
    if not rs:
        return None
    out = {"n": len(rs)}
    for h in (1, 3, 5):
        xs = [r[h] for r in rs if r.get(h) is not None]
        if xs:
            m = st.mean(xs)
            sd = st.stdev(xs) if len(xs) > 1 else 0
            out[f"T+{h}"] = {"wr": round(sum(1 for x in xs if x > 0) / len(xs), 3),
                             "mean": round(m * 100, 2),
                             "t": round(m / (sd / math.sqrt(len(xs))), 1) if sd else None}
    return out


def fwd(d, i, entry_i, entry_px):
    out = {}
    for h in (1, 3, 5):
        j = i + h  # 信号日 +h 收盘
        out[h] = (d["c"][j] / entry_px - 1 - FEE) if j < d["n"] else None
    return out


# ═══ F1 深档深跌件 ═══
official, b_confirmed, b_false, untradeable = [], [], [], 0
cluster_close = collections.Counter()
cluster_1030 = collections.Counter()
# 第一遍：官方事件 + 簇计数
for code, d in stocks.items():
    if code[:2] not in ("60", "00"):
        continue
    n = d["n"]
    for i in range(60, n - 6):
        dt = d["date"][i]
        if dt < W0 or d["c"][i - 1] <= 0:
            continue
        ma = d["ma60"][i]
        if not ma:
            continue
        pct = d["c"][i] / d["c"][i - 1] - 1
        if pct <= -0.095 and d["c"][i] <= ma * 0.75:
            cluster_close[dt] += 1
for code, d in stocks.items():
    if code[:2] not in ("60", "00"):
        continue
    n = d["n"]
    for i in range(60, n - 6):
        dt = d["date"][i]
        if dt < W0 or cluster_close.get(dt, 0) < 5 or d["c"][i - 1] <= 0:
            continue
        ma = d["ma60"][i]
        if not ma:
            continue
        pct = d["c"][i] / d["c"][i - 1] - 1
        if pct <= -0.095 and d["c"][i] <= ma * 0.65:
            # 官方 A：次日开盘
            if d["o"][i + 1] > 0:
                official.append({**fwd(d, i, i + 1, d["o"][i + 1]), "code": code, "date": dt})
            # 10:30 B：同一只的官方事件，10:30 价
            bb = bars(code).get(dt, {})
            b1030 = bb.get("10:30")
            if b1030 and float(b1030["close"]) > 0:
                b_confirmed.append({**fwd(d, i, i, float(b1030["close"])), "code": code, "date": dt})
# 第二遍：10:30 代理全信号（不看收盘），量假阳性率
for code, d in stocks.items():
    if code[:2] not in ("60", "00"):
        continue
    n = d["n"]
    by = bars(code)
    for i in range(60, n - 6):
        dt = d["date"][i]
        if dt < W0 or d["c"][i - 1] <= 0:
            continue
        b1030 = by.get(dt, {}).get("10:30")
        if not b1030:
            continue
        p = float(b1030["close"])
        if p <= 0:
            continue
        ma_est = (sum(x for x in d["c"][i - 59:i]) + p) / 60
        if p / d["c"][i - 1] - 1 <= -0.095 and p <= ma_est * 0.65:
            cluster_1030[dt] += 1
for code, d in stocks.items():
    if code[:2] not in ("60", "00"):
        continue
    n = d["n"]
    by = bars(code)
    for i in range(60, n - 6):
        dt = d["date"][i]
        if dt < W0 or cluster_1030.get(dt, 0) < 5 or d["c"][i - 1] <= 0:
            continue
        b1030 = by.get(dt, {}).get("10:30")
        if not b1030:
            continue
        p = float(b1030["close"])
        if p <= 0:
            continue
        ma_est = (sum(x for x in d["c"][i - 59:i]) + p) / 60
        if p / d["c"][i - 1] - 1 <= -0.095 and p <= ma_est * 0.65:
            # 一字锁死剔除
            if float(b1030["high"]) <= p * 1.001 and p / d["c"][i - 1] - 1 <= -0.098:
                untradeable += 1
                continue
            ma = d["ma60"][i]
            confirmed = (d["c"][i] / d["c"][i - 1] - 1 <= -0.095 and ma and d["c"][i] <= ma * 0.65)
            rec = {**fwd(d, i, i, p), "code": code, "date": dt}
            (b_confirmed if confirmed else b_false).append(rec)

print("\n═══ F1 深档深跌件（簇≥5 语境）═══")
print(f"官方事件(次日开盘) {blk(official)}")
print(f"10:30代理·被官方确认 {blk(b_confirmed)}")
print(f"10:30代理·假阳性 {blk(b_false)}  （一字锁死剔除 {untradeable}）")

# 官方事件信号日下午走势（10:30→收盘）
aft = [d2["c"][i2] / float(bars(c2)[dt2]["10:30"]["close"]) - 1
       for e in official
       for c2, dt2 in [(e["code"], e["date"])]
       for i2, d2 in [(stocks[c2]["_didx"].get(dt2), stocks[c2])]
       if i2 and bars(c2).get(dt2, {}).get("10:30")]
if aft:
    print(f"官方事件信号日下午(10:30→收盘)：n={len(aft)} 均值{st.mean(aft) * 100:+.2f}% 中位{st.median(aft) * 100:+.2f}% 胜率{sum(1 for x in aft if x > 0) / len(aft) * 100:.0f}%")

json.dump({"official": blk(official), "b_confirmed": blk(b_confirmed), "b_false": blk(b_false)},
          open(f"{ROOT}/data/intraday_entry_1030_20260922.json", "w"), ensure_ascii=False, indent=1)
print("\nsaved data/intraday_entry_1030_20260922.json")
