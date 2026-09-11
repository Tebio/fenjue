#!/usr/bin/env python3
"""engine/smallcap_research.py — A股小市值因子月度轮动实证（2026-09-11）

用户点名要「黑马策略」研究。小市值是A股最著名因子（2019-2023神迹，2024-01微盘股崩盘）。
口径：每月最后一个交易日收盘后，按时点流通市值（cap_hist，换手率反推，无前复权问题）
取最小 50 只（过滤：cap>0、当日不复权价≥2元防仙股），次一交易日开盘买入（qfq），
持有至下月调仓日开盘卖出，净费 -0.15%×2（双边各一次/月）。
对照：同期全宇宙等权。分段：2019-2022 / 2023-2026。
已知限制：退市股不在 big_kcache（小市值因子最大的存活者偏差来源——2024-01 崩盘前
退市的票不在样本里，结果系统性偏暖，正文必须标注）。
"""
import json, glob, statistics as st
from pathlib import Path

KC = Path("/opt/data/fenjue/data/big_kcache")
CAP = Path("/opt/data/fenjue/data/cap_hist")
FEE2 = 0.003  # 双边
OUT = Path("/opt/data/fenjue/data/smallcap_20260911.json")

caps = {}
for fp in glob.glob(str(CAP / "*.json")):
    code = Path(fp).stem
    rows = json.loads(open(fp).read())
    caps[code] = {d: (c, cap) for d, c, cap in rows}
print("cap_hist stocks:", len(caps))

kcache = {}
for fp in glob.glob(str(KC / "*.json")):
    code = Path(fp).stem
    if code not in caps:
        continue
    ks = json.loads(open(fp).read())
    kcache[code] = {k["date"]: (k["open"], k["close"]) for k in ks}
print("matched:", len(kcache))

# 全交易日历（并集排序）
all_dates = sorted({d for c in caps.values() for d in c})
# 月末交易日
month_end = {}
for d in all_dates:
    month_end[d[:7]] = d
me_dates = sorted(month_end.values())
# 每月末日 → 次一交易日
next_day = {me_dates[i]: (me_dates[i + 1] if i + 1 < len(me_dates) else None)
            for i in range(len(me_dates))}
# 找 t 之后的第一个交易日作为入场日
def entry_after(d):
    i = all_dates.index(d)
    return all_dates[i + 1] if i + 1 < len(all_dates) else None

periods = []
for i, me in enumerate(me_dates[:-1]):
    nxt_me = me_dates[i + 1]
    e0, e1 = entry_after(me), entry_after(nxt_me)
    if e0 and e1:
        periods.append((me, e0, e1))
print("periods:", len(periods), periods[0], periods[-1])

uni_ret, sc_ret, detail = [], [], []
for me, e0, e1 in periods:
    cands = []
    univ = []
    for code, capmap in caps.items():
        if me not in capmap:
            continue
        close_raw, cap = capmap[me]
        if not cap or cap <= 0 or not close_raw or close_raw < 2:
            continue
        kc = kcache.get(code)
        if not kc or e0 not in kc or e1 not in kc:
            continue
        o0, o1 = kc[e0][0], kc[e1][0]
        if o0 <= 0 or o1 <= 0:
            continue
        r = o1 / o0 - 1 - FEE2
        univ.append(r)
        cands.append((cap, code, r))
    if len(cands) < 100:
        continue
    cands.sort()
    picks = cands[:50]
    u = st.mean(univ)
    s = st.mean([p[2] for p in picks])
    uni_ret.append(u)
    sc_ret.append(s)
    detail.append({"month": me[:7], "smallcap": round(s * 100, 2), "universe": round(u * 100, 2),
                   "win": s > u})

def era(y0, y1):
    sel = [d for d in detail if y0 <= d["month"] <= y1]
    if not sel:
        return None
    sm = [d["smallcap"] for d in sel]
    um = [d["universe"] for d in sel]
    cum_s, cum_u = 1.0, 1.0
    for a, b in zip(sm, um):
        cum_s *= 1 + a / 100
        cum_u *= 1 + b / 100
    return {"months": len(sel), "月均小市值%": round(st.mean(sm), 2), "月均全市场%": round(st.mean(um), 2),
            "月胜率(跑赢全市场)%": round(sum(1 for d in sel if d["win"]) / len(sel) * 100, 1),
            "累计小市值%": round((cum_s - 1) * 100, 1), "累计全市场%": round((cum_u - 1) * 100, 1)}

R = {"全段": era("2019", "2026"), "2019-2022": era("2019", "2022"), "2023-2026": era("2023", "2026"),
     "逐月明细": detail}
OUT.write_text(json.dumps(R, ensure_ascii=False, indent=1))
print(json.dumps({k: v for k, v in R.items() if k != "逐月明细"}, ensure_ascii=False, indent=1))
worst = sorted(detail, key=lambda d: d["smallcap"])[:5]
print("最差5个月:", worst)
print("saved", OUT)
