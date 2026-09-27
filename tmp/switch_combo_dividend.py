"""杠杆门切换组合 + 分红事件（2026-09-27 晚）。

A. 切换组合（2020-01~2022-10 金股可比段）：每日按杠杆门状态分配——
   加杠杆期：打金股组合（新鲜独家）；去杠杆期：打深档批+摇篮；中段：空仓持币。
   与单线/买入持有对照。
B. 分红提升事件：年度每股分红同比提升≥30% 的票，公告年次年表现（首次分红=从0到有）。
"""
import bisect
import collections
import glob
import json
import os
import statistics as st
import sys

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

ROOT = "/opt/data/fenjue"
FEE = 0.0015
stocks = lp.load_universe()
idx = json.load(open(f"{ROOT}/data/index_sh000001.json"))
idays = [r["date"] for r in idx]
iclose = {r["date"]: r["close"] for r in idx}

margin = json.load(open(f"{ROOT}/data/margin_history.json"))
mrec = {str(r.get("date"))[:10]: float(r.get("rzye") or r.get("RZYE") or 0) for r in margin} if isinstance(margin, list) else margin
mdays = sorted(mrec)
def margin_gate(day):
    i = bisect.bisect_left(mdays, day)
    if i < 20 or i >= len(mdays):
        return "中段"
    base = mrec[mdays[i - 20]]
    if base <= 0:
        return "中段"
    chg = mrec[mdays[i]] / base - 1
    return "去杠杆" if chg < -0.03 else ("加杠杆" if chg > 0.073 else "中段")

# ── A. 切换组合 ──
picks = {}
for fp in sorted(glob.glob(f"{ROOT}/data/gold_stock_cache/*.json")):
    mo = os.path.basename(fp)[:-5]
    rows = json.load(open(fp))
    if rows:
        cnt = collections.Counter(r["code"] for r in rows)
        picks[mo] = cnt
deep = {b["date"]: b["r10"] for b in json.load(open(f"{ROOT}/data/deep_batches_full_20260927.json"))}
cradle = collections.defaultdict(list)
for e in json.load(open(f"{ROOT}/data/cradle_horizon_20260927.json")):
    cradle[e["date"]].append(e["t20"])

seen = collections.defaultdict(set)
gold_events = collections.defaultdict(list)
for mo in sorted(picks):
    mdays_ = [d for d in idays if d.startswith(mo)]
    if len(mdays_) < 6:
        continue
    d6 = mdays_[5]
    for code in sorted(picks[mo]):
        if picks[mo][code] > 1 or code in seen[mo[:4]]:  # 独家+新鲜
            continue
        seen[mo[:4]].add(code)
        d = stocks.get(code)
        if not d:
            continue
        i = bisect.bisect_left(d["date"], d6)
        if i < d["n"] and d["date"][i] == d6 and i + 21 < d["n"] and d["o"][i] > 0:
            gold_events[d6].append(d["c"][i + 20] / d["o"][i] - 1 - FEE)

def sim_switch(start, end, use_switch=True):
    cash, positions, curve = 50000.0, [], []
    for day in idays:
        if day < start or day > end:
            continue
        for p in [p for p in positions if p["exit"] <= day]:
            cash += p["amt"] * (1 + p["ret"])
            positions.remove(p)
        gate = margin_gate(day) if use_switch else "全部"
        # 深档批（去杠杆日才打；对照组全部打）
        if day in deep and (gate in ("去杠杆",) or not use_switch):
            if cash >= 10000 and len(positions) < 5:
                i = bisect.bisect_left(idays, day)
                positions.append({"amt": 10000.0, "ret": deep[day], "exit": idays[min(i + 11, len(idays) - 1)]})
                cash -= 10000.0
        # 摇篮（去杠杆日才打）
        if day in cradle and (gate == "去杠杆" or not use_switch):
            for r in cradle[day][:2]:
                if cash >= 10000 and len(positions) < 5:
                    i = bisect.bisect_left(idays, day)
                    positions.append({"amt": 10000.0, "ret": r, "exit": idays[min(i + 21, len(idays) - 1)]})
                    cash -= 10000.0
        # 金股（加杠杆日才打；对照组全部打）
        if day in gold_events and (gate == "加杠杆" or not use_switch):
            for r in gold_events[day][:3]:
                if cash >= 10000 and len(positions) < 5:
                    i = bisect.bisect_left(idays, day)
                    positions.append({"amt": 10000.0, "ret": r, "exit": idays[min(i + 21, len(idays) - 1)]})
                    cash -= 10000.0
        curve.append((day, cash + sum(p["amt"] for p in positions)))
    final = cash + sum(p["amt"] * (1 + p["ret"]) for p in positions)
    peak, mdd = 50000.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    i0, i1 = bisect.bisect_left(idays, start), bisect.bisect_left(idays, end)
    idx_ret = iclose[idays[i1]] / iclose[idays[i0]] - 1
    return final, mdd, idx_ret

print("═══ A. 杠杆门切换组合（2020-01→2022-10 金股可比段） ═══", flush=True)
f1, m1, ir = sim_switch("2020-01-01", "2022-10-31", use_switch=True)
print(f"  切换组合（加杠杆打金股/去杠杆打恐慌/中段空仓）: 5万→{f1:,.0f}（{(f1 / 50000 - 1) * 100:+.0f}%）回撤{m1 * 100:.0f}% | 同期300 {ir * 100:+.0f}%")
f2, m2, _ = sim_switch("2020-01-01", "2022-10-31", use_switch=False)
print(f"  不切换对照（三线全时段都打）: 5万→{f2:,.0f}（{(f2 / 50000 - 1) * 100:+.0f}%）回撤{m2 * 100:.0f}%")

# ── B. 分红提升/首次分红事件 ──
print("\n═══ B. 分红提升事件（年报口径，次年持有 T+120 超额） ═══", flush=True)
dh = json.load(open(f"{ROOT}/data/dividend_history.json"))
# 结构探测
sample_k = next(iter(dh))
print("dividend_history 结构:", type(dh), str(dh[sample_k])[:200])
