"""板块轮动横截面（2026-09-27 深夜）：自建等权板块日收益指数，测月度动量 vs 反转。
上月板块收益五分位 → 次月收益。轮换频率：月度。
"""
import collections
import json
import statistics as st
import sys

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

stocks = lp.load_universe()
mmap = json.load(open("/opt/data/fenjue/data/industry_map.json"))
code2ind = {str(k).zfill(6): v["industry"] for k, v in mmap.items() if isinstance(v, dict) and v.get("industry")}

# 板块日收益 = 成分等权均值（当日≥5 只有效）
day_ind = collections.defaultdict(lambda: collections.defaultdict(list))
for code, d in stocks.items():
    if code[:2] not in ("60", "00"):
        continue
    ind = code2ind.get(code)
    if not ind:
        continue
    c = d["c"]
    for i in range(1, d["n"]):
        if c[i - 1] > 0:
            day_ind[d["date"][i]][ind].append(c[i] / c[i - 1] - 1)

ind_ret = collections.defaultdict(dict)
for dt, inds in day_ind.items():
    for ind, rs in inds.items():
        if len(rs) >= 5:
            ind_ret[ind][dt] = sum(rs) / len(rs)
print(f"板块数 {len(ind_ret)}", flush=True)

days_all = sorted({dt for m in ind_ret.values() for dt in m})
days_all = [d for d in days_all if d >= "2019-08-01"]
months = sorted({d[:7] for d in days_all})
print(f"月数 {len(months)}", flush=True)

cells = collections.defaultdict(list)
for k in range(1, len(months) - 1):
    mo, nxt = months[k], months[k + 1]
    mdays = [d for d in days_all if d.startswith(mo)]
    ndays = [d for d in days_all if d.startswith(nxt)]
    if len(mdays) < 10 or len(ndays) < 3:
        continue
    perf = {}
    for ind, m in ind_ret.items():
        rp = [m[d] for d in mdays if d in m]
        rn = [m[d] for d in ndays if d in m]
        if len(rp) < 8 or not rn:
            continue
        past = 1.0
        for x in rp:
            past *= 1 + x
        perf[ind] = (past - 1, sum(rn))
    if len(perf) < 25:
        continue
    ranked = sorted(perf.items(), key=lambda kv: kv[1][0])
    q = max(len(ranked) // 5, 1)
    cells["上月最弱Q1"].append(st.mean(v[1] for _, v in ranked[:q]))
    cells["上月最强Q5"].append(st.mean(v[1] for _, v in ranked[-q:]))
    cells["全场均值"].append(st.mean(v[1] for v in perf.values()))

print(f"有效月 {len(cells['全场均值'])}")
print("═══ 板块月度动量 vs 反转 ═══")
for lb in ("上月最强Q5", "上月最弱Q1", "全场均值"):
    xs = cells[lb]
    print(f"  {lb:<8}: 次月均 {st.mean(xs) * 100:+.2f}% | 胜率 {sum(1 for x in xs if x > 0) / len(xs) * 100:.0f}%")
ex_top = [t - a for t, a in zip(cells["上月最强Q5"], cells["全场均值"])]
ex_bot = [b - a for b, a in zip(cells["上月最弱Q1"], cells["全场均值"])]
wr_t = sum(1 for x in ex_top if x > 0) / len(ex_top)
wr_b = sum(1 for x in ex_bot if x > 0) / len(ex_bot)
print(f"  最强Q5 超额 {st.mean(ex_top) * 100:+.2f}pp/月（胜率{wr_t * 100:.0f}%）")
print(f"  最弱Q1 超额 {st.mean(ex_bot) * 100:+.2f}pp/月（胜率{wr_b * 100:.0f}%）")
# 分年
by_y = collections.defaultdict(list)
for k, (t, a) in enumerate(zip(cells["上月最强Q5"], cells["全场均值"])):
    by_y[months[k + 1][:4]].append(t - a)
print("  最强Q5超额分年:", {y: f"{st.mean(v) * 100:+.2f}pp" for y, v in sorted(by_y.items())})
