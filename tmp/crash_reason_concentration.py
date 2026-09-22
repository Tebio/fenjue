"""暴跌原因感知选股+集中度测试（2026-09-22 深夜，用户两问）。

Q1「知道为什么跌会不会好点」：深档事件按干净度分层——
  idio = 当日个股跌幅 - 板块均跌幅（独立暴跌=脏）；prior20 = 前20日涨幅（退潮出货=脏）；
  pead_bad = 近10日有首亏/预减公告（业绩雷=脏，data/pead_events.json）。
  对比 T+5 收益：干净组 vs 脏组。
Q2「集中 vs 平均」：同一信号日，深度最深前5只——
  A 平分（5×20%）；B 集中（第1只50%+第2只30%+第3只20%）；C 极集中（第1只100%）。
  组合指标对比：期末、回撤、胜率。2026 年+全史两段。
"""
import collections
import json
import math
import statistics as st
import sys

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

ROOT = "/opt/data/fenjue"
FEE = 0.0015

stocks = lp.load_universe()
regime = lp.load_regime()
mmap = json.loads(open(f"{ROOT}/data/industry_map.json").read())
code2ind = {str(k).zfill(6): v["industry"] for k, v in mmap.items() if isinstance(v, dict) and v.get("industry")}
pead = {}
for e in json.loads(open(f"{ROOT}/data/pead_events.json").read()):
    if e.get("FORECASTTYPE") in ("首亏", "预减", "增亏"):
        pead.setdefault(str(e.get("SECURITY_CODE", "")).zfill(6), []).append((e.get("NOTICE_DATE") or "")[:10])
print("universe", len(stocks), flush=True)

# 板块当日均跌幅（预先算好按日按行业）
# 逐日收集深档事件（-25% 簇门，-35% 出手件）
cluster = collections.Counter()
events = []
for code, d in stocks.items():
    if code[:2] not in ("60", "00"):
        continue
    n = d["n"]
    for i in range(60, n - 6):
        if d["c"][i - 1] <= 0:
            continue
        ma = d["ma60"][i]
        if not ma:
            continue
        pct = d["c"][i] / d["c"][i - 1] - 1
        if pct <= -0.095 and d["c"][i] <= ma * 0.75:
            cluster[d["date"][i]] += 1
            if d["c"][i] <= ma * 0.65:
                ind = code2ind.get(code, "")
                prior20 = d["c"][i - 1] / d["c"][i - 21] - 1 if i >= 21 and d["c"][i - 21] > 0 else 0
                bad = any(0 <= (lambda a, b: (__import__("datetime").date.fromisoformat(a) - __import__("datetime").date.fromisoformat(b)).days)(d["date"][i], pd) <= 10
                          for pd in pead.get(code, []))
                events.append({"code": code, "i": i, "date": d["date"][i], "pct": pct,
                               "depth": d["c"][i] / ma - 1, "ind": ind, "prior20": prior20,
                               "pead_bad": bad, "regime": regime.get(d["date"][i], "?")})
print(f"深跌件事件 {len(events)}", flush=True)

# 板块当日均跌幅（用来算 idio）
ind_day = collections.defaultdict(dict)  # date -> ind -> mean pct
for code, d in stocks.items():
    ind = code2ind.get(code, "")
    if not ind:
        continue
    n = d["n"]
    for i in range(1, n):
        if d["c"][i - 1] <= 0:
            continue
        dt = d["date"][i]
        if cluster.get(dt, 0) < 5:
            continue
        ind_day[dt].setdefault(ind, []).append(d["c"][i] / d["c"][i - 1] - 1)
ind_mean = {dt: {k: st.mean(v) for k, v in inds.items()} for dt, inds in ind_day.items()}

for e in events:
    d = stocks[e["code"]]
    i = e["i"]
    e["idio"] = e["pct"] - ind_mean.get(e["date"], {}).get(e["ind"], 0)
    e["t5"] = d["c"][i + 5] / d["o"][i + 1] - 1 - FEE if d["o"][i + 1] > 0 else None
    e["t1"] = d["c"][i + 1] / d["o"][i + 1] - 1 - FEE if d["o"][i + 1] > 0 else None

# Q1：干净度分层
print("\n═══ Q1 暴跌原因分层（T+5）═══")


def blk(rows):
    rows = [r for r in rows if r["t5"] is not None]
    n = len(rows)
    if n < 30:
        return None
    m = st.mean(r["t5"] for r in rows)
    sd = st.stdev([r["t5"] for r in rows]) if n > 1 else 0
    return {"n": n, "win": round(sum(1 for r in rows if r["t5"] > 0) / n, 3),
            "mean": round(m * 100, 2), "t": round(m / (sd / math.sqrt(n)), 1) if sd else None}


groups = {
    "全部深跌件": events,
    "干净(板块同跌 idio>-3%)": [e for e in events if e["idio"] > -0.03],
    "脏(独立暴跌 idio≤-6%)": [e for e in events if e["idio"] <= -0.06],
    "脏(前20日大涨>15%=退潮)": [e for e in events if e["prior20"] > 0.15],
    "干净(前20日没涨)": [e for e in events if e["prior20"] <= 0.05],
    "脏(近10日业绩雷)": [e for e in events if e["pead_bad"]],
    "干净(无业绩雷)": [e for e in events if not e["pead_bad"]],
    "双干净(板块同跌+无雷)": [e for e in events if e["idio"] > -0.03 and not e["pead_bad"] and e["prior20"] <= 0.05],
    "双脏(独立暴跌+退潮)": [e for e in events if e["idio"] <= -0.06 and e["prior20"] > 0.15],
}
q1 = {}
for lb, rows in groups.items():
    b = blk(rows)
    q1[lb] = b
    if b:
        print(f"  {lb:<22} n={b['n']:>5} T+5 {b['mean']:+6.2f}%(t{b['t']}) 胜率{b['win'] * 100:.0f}%")

# Q2：集中度模拟（成簇日按深度排序前5，2026+全史各一遍）
print("\n═══ Q2 集中度对比 ═══")
by_day = collections.defaultdict(list)
for e in events:
    if e["t5"] is not None:
        by_day[e["date"]].append(e)

def sim(mode):
    # mode: 'equal' 5×20%, 'top2' 50/30/20, 'top1' 100%
    trades = []
    for dt, evs in by_day.items():
        evs = sorted(evs, key=lambda x: x["depth"])[:5]
        if mode == "equal":
            weights = [(e, 1 / len(evs)) for e in evs]
        elif mode == "top2":
            w = [0.5, 0.3, 0.2, 0, 0][:len(evs)]
            weights = [(e, w[k]) for k, e in enumerate(evs) if w[k] > 0]
        else:
            weights = [(evs[0], 1.0)]
        for e, w in weights:
            trades.append(e["t5"] * w)
    return trades

for mode, lb in (("equal", "平分5只"), ("top2", "集中50/30/20"), ("top1", "梭哈第1只")):
    rs = sim(mode)
    if not rs:
        continue
    # 组合日频近似：按信号日聚合等权
    byday_ret = []
    for dt, evs in by_day.items():
        evs = sorted(evs, key=lambda x: x["depth"])[:5]
        if mode == "equal":
            byday_ret.append(st.mean(e["t5"] for e in evs))
        elif mode == "top2":
            byday_ret.append(0.5 * evs[0]["t5"] + 0.3 * evs[1]["t5"] + (0.2 * evs[2]["t5"] if len(evs) > 2 else 0))
        else:
            byday_ret.append(evs[0]["t5"])
    days_n = len(byday_ret)
    total = sum(byday_ret)
    worst = min(byday_ret)
    print(f"  {lb:<12} 批次数{days_n} 累计和{total * 100:+.1f}% 批均{st.mean(byday_ret) * 100:+.2f}% 最差批{worst * 100:+.1f}%")

json.dump({"q1": q1}, open(f"{ROOT}/data/crash_reason_concentration_20260922.json", "w"), ensure_ascii=False, indent=1)
print("\nsaved data/crash_reason_concentration_20260922.json")
