"""毒气室验尸 + 摇篮出场结构（2026-09-27 午后）。

A. 毒气室 29 批（趋势平涨×杠杆中段）里 8 个赢批的特征：簇大小/腿数/深度/regime/节日窗/月份。
B. 摇篮事件多 horizon 出场结构：T+5/10/20/30/60，全史+分年+杠杆门分层。
"""
import bisect
import collections
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
ages = json.load(open(f"{ROOT}/data/regime_age.json"))["ages"]

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
idays = [r["date"] for r in idx_data]
iclose = {r["date"]: r["close"] for r in idx_data}
def idx_chg20(day):
    i = bisect.bisect_left(idays, day)
    return iclose[idays[i]] / iclose[idays[i - 20]] - 1 if i >= 20 else None

# 重建深档批（带簇大小/腿数/深度细节）
daily = collections.defaultdict(list)
for code, d in stocks.items():
    if code[:2] not in ("60", "00"):
        continue
    n = d["n"]
    for i in range(60, n - 11):
        if d["c"][i - 1] <= 0 or d["o"][i + 1] <= 0:
            continue
        pct = d["c"][i] / d["c"][i - 1] - 1
        ma = d["ma60"][i]
        if ma and pct <= -0.095 and d["c"][i] < ma and d["c"][i] <= ma * 0.75:
            daily[d["date"][i]].append((d["c"][i] / ma - 1, code, i))

batches = []
for dt, evs in sorted(daily.items()):
    if dt < "2019-07-01" or len(evs) < 5:
        continue
    deep = sorted(e for e in evs if e[0] <= -0.35)
    if not deep:
        continue
    legs = []
    for depth, code, i in deep[:5]:
        d = stocks[code]
        legs.append(d["c"][i + 10] / d["o"][i + 1] - 1 - FEE)
    batches.append({"date": dt, "cluster": len(evs), "n_legs": len(legs),
                    "mean_depth": st.mean(e[0] for e in deep[:5]),
                    "r10": st.mean(legs), "hit": sum(1 for x in legs if x > 0) / len(legs)})

# 节日窗标注（长假±10 交易日）
import datetime
HOLIDAYS = [("2020-01-24", "春节"), ("2020-10-09", "国庆"), ("2021-02-18", "春节"), ("2021-10-08", "国庆"),
            ("2022-02-07", "春节"), ("2022-10-10", "国庆"), ("2023-01-30", "春节"), ("2023-10-09", "国庆"),
            ("2024-02-19", "春节"), ("2024-10-08", "国庆"), ("2025-02-05", "春节"), ("2025-10-09", "国庆"),
            ("2026-02-24", "春节"), ("2026-10-09", "国庆")]
def near_holiday(dt):
    d0 = datetime.date.fromisoformat(dt)
    for hd, name in HOLIDAYS:
        hd_ = datetime.date.fromisoformat(hd)
        if abs((d0 - hd_).days) <= 20:
            return name
    return None

print("═══ A. 毒气室 29 批逐批验尸 ═══", flush=True)
toxic = []
for b in batches:
    g = margin_gate(b["date"])
    ic = idx_chg20(b["date"])
    if g == "中段" and ic is not None and ic >= -0.03:
        toxic.append(b)
toxic.sort(key=lambda b: b["r10"])
print(f"毒气室 {len(toxic)} 批，按收益排序：")
for b in toxic:
    rg = regime.get(b["date"], "?")
    ag = ages.get(b["date"], {}).get("age", "?")
    hol = near_holiday(b["date"]) or ""
    print(f"  {b['date']} {rg}龄{ag} 簇{b['cluster']:>3} 腿{b['n_legs']} 深{b['mean_depth']*100:.0f}% → {b['r10']*100:+6.1f}% {hol}")

# 赢批 vs 亏批特征
win = [b for b in toxic if b["r10"] > 0]
lose = [b for b in toxic if b["r10"] <= 0]
if win and lose:
    print(f"\n赢批 {len(win)} vs 亏批 {len(lose)}：")
    for k, lb in (("cluster", "簇大小"), ("n_legs", "腿数"), ("mean_depth", "平均深度")):
        w = sorted(b[k] for b in win); l = sorted(b[k] for b in lose)
        print(f"  {lb}: 赢中位 {w[len(w)//2]:.2f} vs 亏中位 {l[len(l)//2]:.2f}")
    print(f"  节日窗: 赢 {[b['date'] for b in win if near_holiday(b['date'])]} / 亏 {sum(1 for b in lose if near_holiday(b['date']))}/{len(lose)}")

# ── B. 摇篮出场结构 ──
print("\n═══ B. 摇篮出场结构（T+5/10/20/30/60） ═══", flush=True)
cradle = []
for code, d in stocks.items():
    if code[:2] not in ("60", "00"):
        continue
    n = d["n"]
    for i in range(65, n - 61):
        dt = d["date"][i]
        if dt < "2019-07-01" or d["o"][i + 1] <= 0:
            continue
        try:
            if lp.REGISTRY["妖股摇篮_成簇"](d, i):
                e = {"date": dt, "gate": margin_gate(dt)}
                for h in (5, 10, 20, 30, 60):
                    e[f"t{h}"] = d["c"][i + h] / d["o"][i + 1] - 1 - FEE
                cradle.append(e)
        except Exception:
            pass
print(f"摇篮事件 {len(cradle)}（i+60 截断）")
for h in (5, 10, 20, 30, 60):
    xs = [e[f"t{h}"] for e in cradle]
    wr = sum(1 for x in xs if x > 0) / len(xs)
    # 杠杆门分层
    g1 = [e[f"t{h}"] for e in cradle if e["gate"] == "去杠杆"]
    g1wr = sum(1 for x in g1 if x > 0) / len(g1) if g1 else 0
    print(f"  T+{h:<3} 全部 {wr*100:.0f}%/{st.mean(xs)*100:+.2f}% | 去杠杆 {g1wr*100:.0f}%/{st.mean(g1)*100:+.2f}%" + (f"（n={len(g1)}）" if g1 else ""))
json.dump(cradle, open(f"{ROOT}/data/cradle_horizon_20260927.json", "w"), ensure_ascii=False)
print("saved")
