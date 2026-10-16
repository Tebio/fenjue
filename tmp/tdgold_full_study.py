#!/usr/bin/env python3
"""三连阴_金股覆盖_v1 全历史事件研究（2026-10-15 卡 t_60428c85 任务②）。

注册口径（law_pipeline._three_down_gold）：三连阴（三日连跌且三阴）+ 当月金股名单在册。
入场=次日开盘，离场=T+1/5/20 收盘，净费 0.0015，一字开（|跳空|>=9.5%）剔。
产出：分年/分 regime/位置/量能画像 + 逐事件 JSON（供 KNN 审计与画像反推）。
"""
import sys, json, collections, statistics as st
sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

ROOT = "/opt/data/fenjue"
FEE = 0.0015

stocks = lp.load_universe()
gold = lp._load_gold()
det = lp.REGISTRY["三连阴_金股覆盖_v1"]

# regime 时间轴 + 指数（超额用）
regime_tl = {r["date"]: r["regime"] for r in json.load(open(f"{ROOT}/data/regime_timeline_hcap.json"))}
idx = json.load(open(f"{ROOT}/data/index_sh000001.json"))
idays = [r["date"] for r in idx]
iclose = {r["date"]: r["close"] for r in idx}
i2d = {d: i for i, d in enumerate(idays)}

events = []
for code, d in stocks.items():
    dates = d["date"]
    for i in range(3, d["n"] - 21):
        try:
            if not det(d, i):
                continue
        except Exception:
            continue
        day = dates[i]
        if day < "2020-01-01":
            continue
        # 入场：次日开盘；一字开剔
        if d["o"][i + 1] <= 0:
            continue
        gap = d["o"][i + 1] / d["c"][i] - 1
        if abs(gap) >= 0.095:
            continue
        entry = d["o"][i + 1]
        r1 = d["c"][i + 1] / entry - 1 - FEE
        r5 = d["c"][i + 5] / entry - 1 - FEE if i + 5 < d["n"] else None
        r20 = d["c"][i + 20] / entry - 1 - FEE if i + 20 < d["n"] else None
        # 画像字段（信号日收盘可知）
        ma60 = d["ma60"][i] if "ma60" in d else None
        depth60 = d["c"][i] / ma60 - 1 if ma60 else None
        hi60 = max(d["h"][max(0, i - 59):i + 1])
        dhigh60 = d["c"][i] / hi60 - 1 if hi60 > 0 else None
        base = d["v"][i - 5:i]
        volr5 = d["v"][i] / (sum(base) / 5) if len(base) == 5 and all(x > 0 for x in base) else None
        # 市场同期（T+20 窗口指数收益）
        mkt20 = None
        if day in i2d and i2d[day] + 21 < len(idays):
            mkt20 = iclose[idays[i2d[day] + 21]] / iclose[idays[i2d[day] + 1]] - 1
        events.append({"date": day, "code": code, "entry": entry,
                       "r1": r1, "r5": r5, "r20": r20,
                       "depth60": depth60, "dhigh60": dhigh60, "volr5": volr5,
                       "regime": regime_tl.get(day), "mkt20": mkt20})

print(f"总事件 {len(events)}")
json.dump(events, open(f"{ROOT}/data/tdgold_full_events_20261015.json", "w"), ensure_ascii=False)

def blk(rows, lb):
    if len(rows) < 10:
        print(f"{lb:<24} n={len(rows)} (太少)")
        return
    out = f"{lb:<24} n={len(rows):>6}"
    for h in ("r1", "r5", "r20"):
        xs = [r[h] for r in rows if r[h] is not None]
        if xs:
            out += f" | {h} {100*sum(x>0 for x in xs)/len(xs):4.0f}%/{100*st.mean(xs):+5.2f}%"
    ex = [r["r20"] - r["mkt20"] for r in rows if r["r20"] is not None and r["mkt20"] is not None]
    if ex:
        out += f" | 超额 {100*st.mean(ex):+5.2f}pp"
    print(out)

blk(events, "全部")
print("\n── 分年 ──")
for y in range(2020, 2027):
    blk([r for r in events if r["date"].startswith(str(y))], str(y))
print("\n── 分 regime ──")
for g in ("平淡期", "妖股期", "恐慌期", "主线期", None):
    blk([r for r in events if r["regime"] == g], str(g))
print("\n── 分年×regime（近段重点）──")
for y in ("2023", "2024", "2025", "2026"):
    for g in ("平淡期", "妖股期", "恐慌期", "主线期"):
        blk([r for r in events if r["date"].startswith(y) and r["regime"] == g], f"{y} {g}")
print("\n── 位置（depth60）──")
for lo, hi in [(-9, -0.30), (-0.30, -0.15), (-0.15, -0.05), (-0.05, 0.05), (0.05, 9)]:
    blk([r for r in events if r["depth60"] is not None and lo <= r["depth60"] < hi], f"depth [{lo},{hi})")
print("\n── 量能（volr5）──")
for lo, hi in [(0, 0.7), (0.7, 1.0), (1.0, 1.5), (1.5, 2.5), (2.5, 99)]:
    blk([r for r in events if r["volr5"] is not None and lo <= r["volr5"] < hi], f"volr [{lo},{hi})")
print("\n── 重复信号（同票 5 个交易日内重复触发）──")
by_code = collections.defaultdict(list)
for e in events:
    by_code[e["code"]].append(e["date"])
dup = 0
for c, ds in by_code.items():
    ds = sorted(ds)
    for a, b in zip(ds, ds[1:]):
        # 交易日差 <=5
        if a in i2d and b in i2d and i2d[b] - i2d[a] <= 5:
            dup += 1
print(f"同票5日内重复触发次数: {dup} / 总 {len(events)} = {100*dup/len(events):.1f}%")
