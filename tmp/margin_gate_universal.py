"""杠杆门通用性测试（2026-09-27 中午）：两融杠杆门是深档专属还是通用环境传感器？

X3 生产口径批 + 妖股摇篮事件，分别 × 杠杆门（RZYE 20 日变化 <-3%）。
X3 逻辑直接复用 x3_soil_replay 的生产口径（恐慌期+streak≥2+大簇+恐慌族5探测器+浅跌前3+T+5/-12%止损+跳周一）。
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
idx_map = {k["date"]: float(k["close"]) for k in idx_data}
idx_dates = sorted(idx_map)

PAN_DETS = ["组合_跌停低_三连阴", "反转族_跌停潮50", "妖股摇篮_成簇",
            "组合_跌停低_TD9买_输家250", "组合_跌停低_TD9买_超跌20"]

# ── X3 生产口径重建（与 x3_soil_replay 同逻辑）──
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
        c, pc = d["c"][i], d["c"][i - 1]
        if pc <= 0:
            continue
        pct = c / pc - 1
        if pct <= -0.095:
            ldc[dt] += 1
        for det in PAN_DETS:
            try:
                if lp.REGISTRY[det](d, i):
                    pan_cl[dt] += 1
                    hi60 = max(d["h"][max(0, i - 60):i + 1])
                    shallow = c / hi60 - 1
                    sigs_by_day[dt].append((shallow, code, i))
                    break
            except Exception:
                pass

print("X3 扫描完，重建批…", flush=True)
x3_batches = []
sorted_days = sorted(set(d for s in stocks.values() for d in s["date"] if d >= "2019-07-01"))
panic_streak = collections.Counter()
prev_day = None
for dt in sorted_days:
    rg = regime.get(dt, "平淡期")
    big_cluster = pan_cl[dt] >= 5 or ldc[dt] >= 30
    panic_streak[dt] = (panic_streak.get(prev_day, 0) + 1) if (rg == "恐慌期" and prev_day) else (1 if rg == "恐慌期" else 0)
    prev_day = dt
    if rg != "恐慌期" or panic_streak[dt] < 2 or not big_cluster:
        continue
    cands = sorted(sigs_by_day.get(dt, []))[:3]
    if not cands:
        continue
    # 周一跳（信号日周五→入场周一跳）
    wd = datetime.date.fromisoformat(dt).weekday()
    if wd == 4:
        continue
    legs = []
    for shallow, code, i in cands:
        d = stocks[code]
        entry = d["o"][i + 1]
        # T+5 收盘或 -12% 止损先到先出
        r = None
        for j in range(i + 1, min(i + 6, d["n"])):
            if d["c"][j] / entry - 1 <= -0.12:
                r = d["c"][j] / entry - 1 - FEE
                break
        if r is None:
            r = d["c"][min(i + 5, d["n"] - 1)] / entry - 1 - FEE
        legs.append(r)
    if legs:
        x3_batches.append({"date": dt, "r": st.mean(legs)})
print(f"X3 批 {len(x3_batches)} 个", flush=True)

print("═══ X3 批 × 杠杆门（T+5/-12%止损口径） ═══")
cells = collections.defaultdict(list)
for b in x3_batches:
    g = margin_gate(b["date"])
    if g:
        cells[g].append(b["r"])
for k in ("去杠杆", "中段", "加杠杆"):
    xs = cells.get(k, [])
    if not xs:
        continue
    wr = sum(1 for x in xs if x > 0) / len(xs)
    print(f"  {k:<6} n={len(xs):>3} 批 | 批均 {st.mean(xs)*100:+.2f}% | 批胜率 {wr*100:.0f}% | 最差 {min(xs)*100:+.1f}%")

# ── 摇篮事件 × 杠杆门 ──
print("摇篮事件扫描…", flush=True)
cradle = []
for code, d in stocks.items():
    if code[:2] not in ("60", "00"):
        continue
    n = d["n"]
    for i in range(65, n - 21):
        dt = d["date"][i]
        if dt < "2019-07-01" or d["o"][i + 1] <= 0:
            continue
        try:
            if lp.REGISTRY["妖股摇篮_成簇"](d, i):
                cradle.append({"date": dt, "t20": d["c"][i + 20] / d["o"][i + 1] - 1 - FEE})
        except Exception:
            pass
print(f"摇篮事件 {len(cradle)}")
print("═══ 摇篮 × 杠杆门（T+20） ═══")
cells2 = collections.defaultdict(list)
for e in cradle:
    g = margin_gate(e["date"])
    if g:
        cells2[g].append(e["t20"])
for k in ("去杠杆", "中段", "加杠杆"):
    xs = cells2.get(k, [])
    if not xs:
        continue
    wr = sum(1 for x in xs if x > 0) / len(xs)
    print(f"  {k:<6} n={len(xs):>4} | T20 {wr*100:.0f}%/{st.mean(xs)*100:+.2f}%")
