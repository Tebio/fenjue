"""2026 年深档 v2 生产规则逐日回放（2026-09-22 深夜，用户问「之前做出来会推什么票」）。

生产口径全保真：簇门=深档件(收≤MA60×0.75)≥5，出手票=深跌件(收≤MA60×0.65)按深度最深取前5，
剔 ST/退（现行名——历史回放轻微前视，注记），含退市股，信号日收盘后判定，次日开盘入场，
T+1/3/5/10 收盘出场，费 0.15%。零未来函数：特征全用 ≤t 日数据。
"""
import json
import sys

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

ROOT = "/opt/data/fenjue"
FEE = 0.0015

stocks = lp.load_universe()
names = {str(s["code"]).zfill(6): s.get("name", "")
         for s in json.loads(open(f"{ROOT}/data/main_board_codes.json").read())["stocks"]}
print("universe", len(stocks), flush=True)

# 第一遍：簇计数（深档件 -25% 口径）
cluster = {}
for code, d in stocks.items():
    if code[:2] not in ("60", "00"):
        continue
    nm = names.get(code, "")
    if "ST" in nm or "退" in nm:
        continue
    n = d["n"]
    for i in range(60, n):
        if d["c"][i - 1] <= 0 or d["date"][i] < "2026-01-01":
            continue
        ma = d["ma60"][i]
        if not ma:
            continue
        if d["c"][i] / d["c"][i - 1] - 1 <= -0.095 and d["c"][i] <= ma * 0.75:
            cluster[d["date"][i]] = cluster.get(d["date"][i], 0) + 1

# 第二遍：成簇日的出手票（-35% 深跌件，深度最深前 5）
days = sorted(d for d, k in cluster.items() if k >= 5)
print(f"2026 成簇日 {len(days)} 天", flush=True)
print(f"{'信号日':<12}{'代码':<9}{'名称':<8}{'当日%':>7}{'深度':>7}  T+1     T+3     T+5     T+10")
all_recs = []
for dt in days:
    picks = []
    for code, d in stocks.items():
        if code[:2] not in ("60", "00"):
            continue
        nm = names.get(code, "")
        if "ST" in nm or "退" in nm:
            continue
        i = d["_didx"].get(dt) if "_didx" in d else None
        if i is None:
            i = d["date"].index(dt) if dt in d["date"] else None
        if i is None or i < 60 or i + 1 >= d["n"]:
            continue
        ma = d["ma60"][i]
        if not ma or d["c"][i - 1] <= 0:
            continue
        pct = d["c"][i] / d["c"][i - 1] - 1
        depth = d["c"][i] / ma - 1
        if pct <= -0.095 and depth <= -0.35:
            picks.append((depth, code, nm, pct, i))
    picks.sort()
    for depth, code, nm, pct, i in picks[:5]:
        d = stocks[code]
        e = d["o"][i + 1]
        if e <= 0:
            continue
        rs = {}
        for h in (1, 3, 5, 10):
            j = i + h
            rs[h] = (d["c"][j] / e - 1 - FEE) if j < d["n"] else None
        all_recs.append({"date": dt, "code": code, "name": nm, "pct": pct, "depth": depth, **rs})
        fmt = lambda x: f"{x * 100:+6.1f}%" if x is not None else "   —  "
        print(f"{dt:<12}{code:<9}{nm:<8}{pct * 100:+6.1f}%{depth * 100:+6.0f}%  {fmt(rs[1])} {fmt(rs[3])} {fmt(rs[5])} {fmt(rs[10])}")

import statistics as st
for h, lb in ((1, "T+1"), (3, "T+3"), (5, "T+5"), (10, "T+10")):
    xs = [r[h] for r in all_recs if r.get(h) is not None]
    if xs:
        print(f"\n{lb}: n={len(xs)} 胜率{sum(1 for x in xs if x > 0) / len(xs) * 100:.0f}% 均值{st.mean(xs) * 100:+.2f}% 中位{st.median(xs) * 100:+.2f}%")
json.dump(all_recs, open(f"{ROOT}/data/deep_v2_replay_2026_20260922.json", "w"), ensure_ascii=False, indent=1)
print("saved data/deep_v2_replay_2026_20260922.json")
