"""深夜连班四测（2026-09-25/26，用户「深夜把能搞的接着搞了」）。

A T1-MEGA 土壤门：缺口低簇≥20 日、量比前10、T+3 收盘出（生产口径）×指数位置
B X3 土壤门：恐慌期 streak≥2 日浅跌前三、T+5/-12%（近似）×指数位置
C 巨量三连阴×深档确认层（BACKLOG#20）：生产日 picks 中「前3日三连阴+第3日巨量>2x」的票是否更强
D B5×段龄（BACKLOG#19）：B5 近似（+6%未板+量比≥2+梯队≥3+首板+反人群=非妖股期）×妖段龄
口径：8 年，次日开盘入（B5=当日收盘入），费 0.15%，含退市股。
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
tl = json.load(open(f"{ROOT}/data/regime_timeline_hcap.json"))
regime = {x["date"]: x["regime"] for x in tl}
age_map = {}
cur_r, age = None, 0
for x in tl:
    if x["regime"] != cur_r:
        cur_r, age = x["regime"], 1
    else:
        age += 1
    age_map[x["date"]] = (x["regime"], age)

idx_data = json.load(open(f"{ROOT}/data/index_sh000001.json"))
idx_map = {k["date"]: float(k["close"]) for k in idx_data}
idx_dates = sorted(idx_map)
idx_ma20 = {}
for k, dt in enumerate(idx_dates):
    if k >= 19:
        idx_ma20[dt] = sum(idx_map[idx_dates[k - 19 + j]] for j in range(20)) / 20


def soil(dt):
    return idx_map.get(dt, 0) <= idx_ma20.get(dt, 0)


def is_lu(c, cp):
    return cp > 0 and c / cp - 1 >= 0.098


mmap = json.load(open(f"{ROOT}/data/industry_map.json"))
code2ind = {str(k).zfill(6): v["industry"] for k, v in mmap.items() if isinstance(v, dict) and v.get("industry")}
ind_boards = collections.defaultdict(lambda: collections.Counter())
for code, d in stocks.items():
    if code[:2] not in ("60", "00"):
        continue
    ind = code2ind.get(code, "")
    for i in range(61, d["n"]):
        if is_lu(d["c"][i], d["c"][i - 1]):
            ind_boards[d["date"][i]][ind] += 1

# ══ A T1-MEGA ══
gap_days = collections.defaultdict(list)
for code, d in stocks.items():
    if code[:2] not in ("60", "00"):
        continue
    n = d["n"]
    for i in range(61, n - 4):
        dt = d["date"][i]
        if d["c"][i - 1] <= 0 or d["o"][i + 1] <= 0:
            continue
        if d["o"][i] <= d["c"][i - 1] * 0.97 and d["h"][i] > d["l"][i] and \
           (d["c"][i] - d["l"][i]) / (d["h"][i] - d["l"][i]) <= 0.33:
            vr = d["v"][i] / (st.mean(d["v"][i - 20:i]) or 1)
            gap_days[dt].append({"code": code, "vr": vr,
                                 "t3": d["c"][i + 3] / d["o"][i + 1] - 1 - FEE})

print("═══ A T1-MEGA 土壤门（簇≥20，量比前10，T+3） ═══")
for lb, cond in (("真恐慌(指数≤MA20)", True), ("假恐慌(指数>MA20)", False)):
    bs = []
    for dt, cands in gap_days.items():
        if len(cands) < 20 or soil(dt) != cond:
            continue
        picks = sorted(cands, key=lambda x: -x["vr"])[:10]
        bs.append(st.mean(p["t3"] for p in picks))
    if len(bs) >= 5:
        nav = 1.0
        for x in bs:
            nav *= 1 + x
        print(f"  {lb}: 批数{len(bs):>3} 批胜率{sum(1 for x in bs if x > 0) / len(bs) * 100:3.0f}% "
              f"批均{st.mean(bs) * 100:+5.2f}% 最差批{min(bs) * 100:+6.1f}% 复利{nav:.2f}x")

# ══ B X3 ══
# 恐慌期 streak≥2：连续第2天起，浅跌前三（当日跌幅最小的三只非跌停深档件）——用「恐慌期第2天+大簇」近似：恐慌期日深档簇≥5 且前日也是恐慌期
print("\n═══ B X3 土壤门（恐慌期streak≥2，浅跌前三，T+5/-12%近似=T+5） ═══")
x3_days = []
prev_panic = False
for x in tl:
    dt = x["date"]
    if x["regime"] == "恐慌期" and prev_panic:
        x3_days.append(dt)
    prev_panic = x["regime"] == "恐慌期"
x3_set = set(x3_days)
shallow = collections.defaultdict(list)
for code, d in stocks.items():
    if code[:2] not in ("60", "00"):
        continue
    n = d["n"]
    for i in range(61, n - 6):
        dt = d["date"][i]
        if dt not in x3_set or d["c"][i - 1] <= 0 or d["o"][i + 1] <= 0:
            continue
        ma = d["ma60"][i]
        pct = d["c"][i] / d["c"][i - 1] - 1
        if ma and d["c"][i] <= ma and pct <= -0.03:  # 浅跌（-3% 以上跌幅+MA60 下）
            shallow[dt].append({"pct": pct, "t5": d["c"][i + 5] / d["o"][i + 1] - 1 - FEE})
for lb, cond in (("真恐慌", True), ("假恐慌", False)):
    bs = []
    for dt, cands in shallow.items():
        if soil(dt) != cond or len(cands) < 3:
            continue
        picks = sorted(cands, key=lambda x: x["pct"])[:3]  # 浅跌前三=跌幅最大的三只（浅跌族内最深）
        bs.append(st.mean(p["t5"] for p in picks))
    if len(bs) >= 5:
        nav = 1.0
        for x in bs:
            nav *= 1 + x
        print(f"  {lb}(指数{'≤' if cond else '>'}MA20): 批数{len(bs):>3} 批胜率{sum(1 for x in bs if x > 0) / len(bs) * 100:3.0f}% "
              f"批均{st.mean(bs) * 100:+5.2f}% 最差批{min(bs) * 100:+6.1f}% 复利{nav:.2f}x")

# ══ C 巨量三连阴×深档 ══
print("\n═══ C 巨量三连阴×深档确认层（BACKLOG#20） ═══")
cluster = collections.Counter()
events = []
for code, d in stocks.items():
    if code[:2] not in ("60", "00"):
        continue
    n = d["n"]
    for i in range(64, n - 11):
        if d["c"][i - 1] <= 0:
            continue
        ma = d["ma60"][i]
        if not ma:
            continue
        pct = d["c"][i] / d["c"][i - 1] - 1
        if pct <= -0.095 and d["c"][i] <= ma * 0.75:
            cluster[d["date"][i]] += 1
            if d["c"][i] <= ma * 0.65 and d["o"][i + 1] > 0:
                # 前 3 日三连阴+第 3 日巨量
                t3 = (d["c"][i - 2] < d["c"][i - 3] and d["c"][i - 1] < d["c"][i - 2] and d["c"][i] < d["c"][i - 1])
                vexp = d["v"][i] / ((d["v"][i - 2] + d["v"][i - 1]) / 2) if (d["v"][i - 2] + d["v"][i - 1]) > 0 else 1
                events.append({"date": d["date"][i], "depth": d["c"][i] / ma - 1,
                               "bigvol3": t3 and vexp >= 2,
                               "t10": d["c"][i + 10] / d["o"][i + 1] - 1 - FEE})
prod = {d for d, k in cluster.items() if k >= 5}
xs = [e for e in events if e["date"] in prod]
for lb, cond in (("前3日三连阴+巨量>2x", True), ("无此形态", False)):
    sel = [e for e in xs if e["bigvol3"] == cond]
    if len(sel) >= 15:
        wr = sum(1 for e in sel if e["t10"] > 0) / len(sel)
        print(f"  {lb}: 事件 n={len(sel)} {wr * 100:.1f}%/{st.mean([e['t10'] for e in sel]) * 100:+.2f}%")

# ══ D B5×段龄 ══
print("\n═══ D B5×段龄（BACKLOG#19，B5近似=+6%未板+量比≥2+梯队≥3+首板，非妖股期） ═══")
b5 = collections.defaultdict(list)
for code, d in stocks.items():
    if code[:2] not in ("60", "00"):
        continue
    n = d["n"]
    for i in range(61, n - 2):
        dt = d["date"][i]
        if d["c"][i - 1] <= 0:
            continue
        pct = d["c"][i] / d["c"][i - 1] - 1
        if not (0.06 <= pct < 0.098):  # +6% 未封板
            continue
        if any(is_lu(d["c"][j], d["c"][j - 1]) for j in range(i - 10, i)):
            continue
        vr = d["v"][i] / (st.mean(d["v"][i - 20:i]) or 1)
        if vr < 2:
            continue
        ind = code2ind.get(code, "")
        if ind_boards[dt].get(ind, 0) < 3:
            continue
        rg, a = age_map.get(dt, ("?", 0))
        b5[a].append({"rg": rg, "t1": d["c"][i + 1] / d["c"][i] - 1 - FEE})  # close-entry T+1
for lo, hi, lb in ((1, 3, "段龄1-2(启动期)"), (3, 6, "段龄3-5(发酵期)"), (6, 999, "段龄6+(退潮期)")):
    xs = [e["t1"] for a, rows in b5.items() if lo <= a < hi for e in rows]
    if len(xs) >= 20:
        wr = sum(1 for x in xs if x > 0) / len(xs)
        print(f"  {lb}: n={len(xs):>5} {wr * 100:5.1f}%/{st.mean(xs) * 100:+5.2f}%")
