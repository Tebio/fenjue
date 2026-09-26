"""节日效应全测（2026-09-26 深夜，新角度：日历缺口自校准，国庆前最后交易日就在眼前）。

检测：指数日历中 ≥4 天的断档=节假日（春节/国庆/五一/中秋/端午/清明/元旦自动识别）。
测法：
  A 过节跳空：节前最后交易日收盘买 → 节后首日开盘/收盘出
  B 节后行情：节后首日开盘买 → T+5/T+10 收盘出
  C 节前避险：节前第 5 日收盘买 → 节前最后日收盘出（节前一周表现）
  分层：长假（≥7天=春节/国庆）vs 短假（4-6天）×分年×regime；对照=全年随机日。
"""
import collections
import json
import random
import statistics as st
import sys

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

ROOT = "/opt/data/fenjue"
stocks = lp.load_universe()
regime = lp.load_regime()
idx_data = json.load(open(f"{ROOT}/data/index_sh000001.json"))
cal = [k["date"] for k in idx_data]
idx_map = {k["date"]: float(k["close"]) for k in idx_data}
FEE = 0.0015

# 日历缺口
from datetime import date
gaps = []
for a, b in zip(cal, cal[1:]):
    da, db = date.fromisoformat(a), date.fromisoformat(b)
    if (db - da).days >= 4:
        gaps.append({"last": a, "first": b, "len": (db - da).days})
print(f"检测到节假日缺口 {len(gaps)} 个")


def trade(code, buy_d, sell_d, mode="cc"):
    """mode: cc=收收, co=收→次日开, oc=开收"""
    d = stocks.get(code)
    if not d or buy_d not in d["date"] or sell_d not in d["date"]:
        return None
    i, j = d["date"].index(buy_d), d["date"].index(sell_d)
    if i >= j or d["c"][i] <= 0:
        return None
    if mode == "cc":
        return d["c"][j] / d["c"][i] - 1 - FEE
    if mode == "co":
        return d["o"][j] / d["c"][i] - 1 - FEE if j < d["n"] else None
    return None


# 全市场等权视角：每次节日抽 800 只票
random.seed(11)
res = collections.defaultdict(list)
for g in gaps:
    i_last = cal.index(g["last"])
    i_first = cal.index(g["first"])
    long_gap = g["len"] >= 7
    for code, d in random.sample(sorted(stocks.items()), 800):
        if code[:2] not in ("60", "00"):
            continue
        r = trade(code, g["last"], g["first"], "co")   # A 过节跳空
        if r is not None:
            res[("A", long_gap)].append(r)
        # B 节后首日开买→T+5 收
        j_end = cal[min(i_first + 4, len(cal) - 1)]
        r = trade(code, g["first"], j_end, "oc") if False else None
        d2 = stocks[code]
        if g["first"] in d2["date"]:
            ii = d2["date"].index(g["first"])
            if ii + 5 < d2["n"] and d2["o"][ii] > 0:
                res[("B", long_gap)].append(d2["c"][ii + 5] / d2["o"][ii] - 1 - FEE)
        # C 节前一周：节前第5日收→节前最后日收
        i5 = cal[max(0, i_last - 5)]
        r = trade(code, i5, g["last"], "cc")
        if r is not None:
            res[("C", long_gap)].append(r)

# 对照：随机日同口径
ctrl = {"co": [], "oc5": [], "cc5": []}
for _ in range(6000):
    i = random.randint(60, len(cal) - 10)
    code = random.choice(list(stocks.keys()))
    d = stocks[code]
    if code[:2] not in ("60", "00") or cal[i] not in d["date"]:
        continue
    ii = d["date"].index(cal[i])
    if ii + 6 < d["n"] and d["c"][ii] > 0:
        ctrl["co"].append(d["o"][ii + 1] / d["c"][ii] - 1 - FEE)
        ctrl["oc5"].append(d["c"][ii + 5] / d["o"][ii + 1] - 1 - FEE)
        ctrl["cc5"].append(d["c"][ii + 5] / d["c"][ii] - 1 - FEE)


def rep(key, lb, ctrlkey):
    xs = res.get(key, [])
    if len(xs) < 10:
        print(f"  {lb}: n={len(xs)} 不足")
        return
    wr = sum(1 for x in xs if x > 0) / len(xs)
    c = ctrl[ctrlkey]
    cwr = sum(1 for x in c if x > 0) / len(c)
    print(f"  {lb:<22} n={len(xs):>5} {wr * 100:5.1f}%/{st.mean(xs) * 100:+5.2f}% | 对照 {cwr * 100:.1f}%/{st.mean(c) * 100:+.2f}%"
          f" → 边际 {st.mean(xs) * 100 - st.mean(c) * 100:+.2f}pp")


print("\n═══ A 过节跳空（节前收盘买→节后开盘出） ═══")
rep(("A", True), "长假(≥7天 春节/国庆)", "co")
rep(("A", False), "短假(4-6天)", "co")
print("═══ B 节后行情（节后开盘买→T+5收） ═══")
rep(("B", True), "长假", "oc5")
rep(("B", False), "短假", "oc5")
print("═══ C 节前一周（节前第5日收→节前末日收） ═══")
rep(("C", True), "长假前一周", "cc5")
rep(("C", False), "短假前一周", "cc5")

print("\n═══ 分年（A 长假） ═══")
by_year = collections.defaultdict(list)
for g in gaps:
    if g["len"] < 7:
        continue
    for code, d in random.sample(sorted(stocks.items()), 400):
        if code[:2] not in ("60", "00"):
            continue
        r = trade(code, g["last"], g["first"], "co")
        if r is not None:
            by_year[g["first"][:4]].append(r)
for y in sorted(by_year):
    xs = by_year[y]
    if len(xs) >= 10:
        wr = sum(1 for x in xs if x > 0) / len(xs)
        print(f"  {y}: n={len(xs):>4} {wr * 100:5.1f}%/{st.mean(xs) * 100:+.2f}%")
json.dump({f"{k[0]}_{k[1]}": v for k, v in res.items()}, open(f"{ROOT}/data/holiday_effect_20260926.json", "w"))
print("\nsaved")
