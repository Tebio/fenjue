"""X3 生产口径土壤门复核（2026-09-26 晚，#184⑤ 反向假设的正审判）。

生产逻辑（xrules_daily 原文）：恐慌期+streak≥2（连续第2天起）+大簇日（恐慌族簇≥5 或 缺口低簇≥8 或 ldc≥30）
→ 恐慌族信号（5 个探测器）里按距60日高最浅取前3 → 次日开盘入（周一跳过）→ T+5 收盘或 -12% 止损先到先出。
分桶：信号日指数≤MA20（真恐慌）vs >MA20（假恐慌）。8 年含退市股，费 0.15%。
"""
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

idx_data = json.load(open(f"{ROOT}/data/index_sh000001.json"))
idx_map = {k["date"]: float(k["close"]) for k in idx_data}
idx_dates = sorted(idx_map)
idx_ma20 = {}
for k, dt in enumerate(idx_dates):
    if k >= 19:
        idx_ma20[dt] = sum(idx_map[idx_dates[k - 19 + j]] for j in range(20)) / 20

PAN_DETS = ["组合_跌停低_三连阴", "反转族_跌停潮50", "妖股摇篮_成簇",
            "组合_跌停低_TD9买_输家250", "组合_跌停低_TD9买_超跌20"]

# 日级横截面：恐慌族簇/缺口低簇/ldc
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
            sigs_by_day[dt].append({"code": code, "pos60": pos60})
        # 缺口低簇（生产口径近似=低开≥3%+收>开阳线+MA60下）
        ma = d["ma60"][i]
        if ma and c[i] <= ma and c[i] > d["o"][i] and d["o"][i] <= c[i - 1] * 0.97:
            gap_cl[dt] += 1

# 恐慌 streak
dates = sorted(regime)
streak = {}
run = 0
for dt in dates:
    run = run + 1 if regime[dt] == "恐慌期" else 0
    streak[dt] = run

def soil(dt):
    return idx_map.get(dt, 0) <= idx_ma20.get(dt, 0)

buckets = collections.defaultdict(list)
for dt in dates:
    if regime.get(dt) != "恐慌期" or streak.get(dt, 0) < 2:
        continue
    big = pan_cl[dt] >= 5 or gap_cl[dt] >= 8 or ldc[dt] >= 30
    if not big:
        continue
    cands = sorted(sigs_by_day.get(dt, []), key=lambda r: -r["pos60"])[:3]
    if not cands:
        continue
    # 入场日=次交易日，跳周一
    k0 = idx_dates.index(dt) if dt in idx_dates else None
    if k0 is None or k0 + 6 >= len(idx_dates):
        continue
    entry_d = idx_dates[k0 + 1]
    wd = datetime.date.fromisoformat(entry_d).weekday()
    if wd == 0:
        continue
    rets = []
    for cnd in cands:
        d = stocks[cnd["code"]]
        if entry_d not in d["date"]:
            continue
        ei = d["date"].index(entry_d)
        if d["o"][ei] <= 0 or ei + 5 >= d["n"]:
            continue
        ep = d["o"][ei]
        # T+5 或 -12% 先到先出
        out = d["c"][ei + 5]
        for j in range(ei + 1, ei + 6):
            if d["c"][j] <= ep * 0.88:
                out = d["c"][j]
                break
        rets.append(out / ep - 1 - FEE)
    if rets:
        buckets[soil(dt)].append(st.mean(rets))

for cond, lb in ((True, "真恐慌(指数≤MA20)"), (False, "假恐慌(指数>MA20)")):
    bs = buckets[cond]
    if len(bs) < 3:
        print(f"{lb}: 批数{len(bs)} 不足")
        continue
    nav = 1.0
    for x in bs:
        nav *= 1 + x
    print(f"{lb}: 批数{len(bs):>3} 批胜率{sum(1 for x in bs if x > 0) / len(bs) * 100:3.0f}% "
          f"批均{st.mean(bs) * 100:+5.2f}% 最差批{min(bs) * 100:+6.1f}% 复利{nav:.2f}x")
# 分年（真恐慌内）
by_year = collections.defaultdict(list)
for dt in dates:
    pass
