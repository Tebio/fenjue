"""恐慌日板块修复速度预测（2026-09-22 深夜，用户问「那种日子能选到最快修复的板块吗」）。

设计：恐慌日=恐慌期 regime 日（权威时间轴）。板块日收益=成分股等权均值（big_kcache+industry_map）。
当日板块特征：①当日板块跌幅（跌得深=杀得狠）②板块内跌停数（出清度）③前 5 日板块涨幅
（前期强势=主线余温）④板块内深跌件数（恐慌深度，咱家信号的板块版）。
前瞻：板块 T+1/3/5 收益。问题：哪个/哪些特征预测修复最快？结论形态=深档选票的行业倾斜依据。
"""
import collections
import json
import math
import statistics as st
import sys

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

ROOT = "/opt/data/fenjue"
stocks = lp.load_universe()
regime = lp.load_regime()
mmap = json.loads(open(f"{ROOT}/data/industry_map.json").read())
code2ind = {str(k).zfill(6): v["industry"] for k, v in mmap.items() if isinstance(v, dict) and v.get("industry")}

# 板块日收益序列（等权成分股日收益）
panic_days = {d for d, r in regime.items() if r == "恐慌期"}
print(f"恐慌期日 {len(panic_days)} 天", flush=True)

# 逐板块逐日：当日收益/前5日收益/跌停数/深跌件数 + T+1/3/5
recs = []
by_day_ind = collections.defaultdict(lambda: collections.defaultdict(list))
for code, d in stocks.items():
    ind = code2ind.get(code, "")
    if not ind:
        continue
    n = d["n"]
    for i in range(61, n - 6):
        dt = d["date"][i]
        if dt not in panic_days or d["c"][i - 1] <= 0:
            continue
        pct = d["c"][i] / d["c"][i - 1] - 1
        deep = pct <= -0.095
        by_day_ind[dt][ind].append((pct, deep, d["c"], i, n))

for dt, inds in by_day_ind.items():
    for ind, rows in inds.items():
        if len(rows) < 5:
            continue
        rets = [r[0] for r in rows]
        day_ret = st.mean(rets)
        ld = sum(1 for r in rows if r[0] <= -0.095)
        deep_n = sum(1 for r in rows if r[1])
        # 前 5 日板块收益
        prior5 = []
        for pct, deep, c, i, n in rows:
            if i >= 66 and c[i - 6] > 0:
                prior5.append(c[i - 1] / c[i - 6] - 1)
        p5 = st.mean(prior5) if prior5 else 0
        # 前瞻（用第一只票的日期索引对齐板块 T+N≈成分均值近似：取成分股各自 T+N 收益均值）
        f1 = [r[2][r[3] + 1] / r[2][r[3]] - 1 for r in rows if r[3] + 1 < r[4]]
        f3 = [r[2][r[3] + 3] / r[2][r[3]] - 1 for r in rows if r[3] + 3 < r[4]]
        f5 = [r[2][r[3] + 5] / r[2][r[3]] - 1 for r in rows if r[3] + 5 < r[4]]
        if not (f1 and f3 and f5):
            continue
        recs.append({"date": dt, "ind": ind, "n": len(rows), "day_ret": day_ret,
                     "ld": ld, "deep_n": deep_n, "prior5": p5,
                     "f1": st.mean(f1), "f3": st.mean(f3), "f5": st.mean(f5)})
print(f"板块×恐慌日 样本 {len(recs)}", flush=True)


def corr_cut(key, lo, hi, label):
    sel = [r for r in recs if lo <= r[key] < hi]
    if len(sel) < 20:
        return
    f1 = st.mean(r["f1"] for r in sel)
    f3 = st.mean(r["f3"] for r in sel)
    f5 = st.mean(r["f5"] for r in sel)
    print(f"  {label:<18} n={len(sel):>5} T+1 {f1*100:+5.2f}% T+3 {f3*100:+5.2f}% T+5 {f5*100:+5.2f}%")


print("\n═══ 按当日板块跌幅 ═══")
for lo, hi, lb in ((-1, -0.05, "跌>5%"), (-0.05, -0.03, "跌3-5%"), (-0.03, -0.01, "跌1-3%"), (-0.01, 1, "跌<1%")):
    corr_cut("day_ret", lo, hi, lb)
print("\n═══ 按板块内跌停数 ═══")
for lo, hi, lb in ((0, 1, "0只"), (1, 3, "1-2只"), (3, 999, "≥3只")):
    corr_cut("ld", lo, hi, lb)
print("\n═══ 按前5日板块涨幅 ═══")
for lo, hi, lb in ((-1, -0.03, "前5日跌>3%"), (-0.03, 0.01, "-3~+1%"), (0.01, 0.05, "+1~5%"), (0.05, 1, "+5%以上")):
    corr_cut("prior5", lo, hi, lb)
print("\n═══ 按板块内深跌件数 ═══")
for lo, hi, lb in ((0, 1, "0件"), (1, 3, "1-2件"), (3, 999, "≥3件")):
    corr_cut("deep_n", lo, hi, lb)

json.dump(recs, open(f"{ROOT}/data/panic_sector_bounce_20260922.json", "w"), ensure_ascii=False)
print("\nsaved data/panic_sector_bounce_20260922.json")
