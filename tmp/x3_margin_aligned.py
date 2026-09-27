"""X3×杠杆门：生产口径严格对齐重测（2026-09-27 午后，修正 margin_gate_universal 的两处偏差：
缺口低簇≥8 分支 + 浅跌排序方向=pos60 最高前三）。
"""
import bisect
import collections
import datetime
import json
import statistics as st
import sys

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

ROOT = "/opt/data/fenjue"
FEE = 0.0015
stocks = lp.load_universe()
lp.build_xsection(stocks)
regime = lp.load_regime()

margin = json.load(open(f"{ROOT}/data/margin_history.json"))
mrec = {str(r.get("date"))[:10]: float(r.get("rzye") or r.get("RZYE") or 0) for r in margin} if isinstance(margin, list) else margin
mdays = sorted(mrec)
def margin_gate(day):
    i = bisect.bisect_left(mdays, day)
    if i < 20 or i >= len(mdays):
        return None
    base = mrec[mdays[i - 20]]
    if base <= 0:
        return None
    chg = mrec[mdays[i]] / base - 1
    return "去杠杆" if chg < -0.03 else ("加杠杆" if chg > 0.073 else "中段")

idx_data = json.load(open(f"{ROOT}/data/index_sh000001.json"))
idx_dates = [r["date"] for r in idx_data]

PAN_DETS = ["组合_跌停低_三连阴", "反转族_跌停潮50", "妖股摇篮_成簇",
            "组合_跌停低_TD9买_输家250", "组合_跌停低_TD9买_超跌20"]

pan_cl = collections.Counter()
gap_cl = collections.Counter()
ldc = collections.Counter()
sigs_by_day = collections.defaultdict(list)
for code, d in stocks.items():
    if code[:2] not in ("60", "00"):
        continue
    n = d["n"]
    for i in range(65, n - 6):
        dt = d["date"][i]
        if dt < "2019-07-01":
            continue
        c = d["c"]
        if c[i - 1] <= 0:
            continue
        if c[i] / c[i - 1] - 1 <= -0.095:
            ldc[dt] += 1
        hit = False
        for det in PAN_DETS:
            try:
                if lp.REGISTRY[det](d, i):
                    hit = True
                    break
            except Exception:
                pass
        if hit:
            pan_cl[dt] += 1
            hi60 = max(d["h"][i - 60:i]) if i >= 60 else d["h"][i]
            pos60 = c[i] / hi60 - 1 if hi60 > 0 else 0
            sigs_by_day[dt].append({"code": code, "pos60": pos60, "i": i})
        ma = d["ma60"][i]
        if ma and c[i] <= ma and c[i] > d["o"][i] and d["o"][i] <= c[i - 1] * 0.97:
            gap_cl[dt] += 1

dates = sorted(regime)
streak = {}
run = 0
for dt in dates:
    run = run + 1 if regime[dt] == "恐慌期" else 0
    streak[dt] = run

print("扫描完，重建 X3 批（生产严格口径）…", flush=True)
batches = []
for dt in dates:
    if dt < "2019-07-01" or regime.get(dt) != "恐慌期" or streak.get(dt, 0) < 2:
        continue
    if not (pan_cl[dt] >= 5 or gap_cl[dt] >= 8 or ldc[dt] >= 30):
        continue
    cands = sorted(sigs_by_day.get(dt, []), key=lambda r: -r["pos60"])[:3]
    if not cands:
        continue
    if datetime.date.fromisoformat(dt).weekday() == 4:  # 周五信号→周一入场，跳
        continue
    legs = []
    for c_ in cands:
        d = stocks[c_["code"]]
        i = c_["i"]
        if i + 1 >= d["n"] or d["o"][i + 1] <= 0:
            continue
        entry = d["o"][i + 1]
        r = None
        for j in range(i + 1, min(i + 6, d["n"])):
            if d["c"][j] / entry - 1 <= -0.12:
                r = d["c"][j] / entry - 1 - FEE
                break
        if r is None:
            r = d["c"][min(i + 5, d["n"] - 1)] / entry - 1 - FEE
        legs.append(r)
    if legs:
        batches.append({"date": dt, "r": st.mean(legs)})
print(f"X3 批 {len(batches)} 个（对齐 #193 的 43）", flush=True)
print("═══ X3 × 杠杆门（生产严格口径） ═══")
cells = collections.defaultdict(list)
for b in batches:
    g = margin_gate(b["date"])
    if g:
        cells[g].append(b["r"])
for k in ("去杠杆", "中段", "加杠杆"):
    xs = cells.get(k, [])
    if not xs:
        continue
    wr = sum(1 for x in xs if x > 0) / len(xs)
    print(f"  {k:<6} n={len(xs):>3} 批 | 批均 {st.mean(xs)*100:+.2f}% | 批胜率 {wr*100:.0f}% | 最差 {min(xs)*100:+.1f}%")
# 全批基线对照
xs = [b["r"] for b in batches]
print(f"  全批基线 n={len(xs)} {st.mean(xs)*100:+.2f}%/{sum(1 for x in xs if x>0)/len(xs)*100:.0f}%（#193 生产回放 64%/+3.70%）")
json.dump(batches, open(f"{ROOT}/data/x3_batches_margin_20260927.json", "w"), ensure_ascii=False)
