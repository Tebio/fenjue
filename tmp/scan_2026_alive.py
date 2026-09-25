"""2026 年段策略存活扫描（2026-09-25，用户：找 26 年启动期/成长期能赚钱的体系）。

对主要策略族在 2026-01-01+ 单段重跑，n≥25 且胜率≥52% 且均值>0 的格子=2026 存活。
家族覆盖：主线期回踩、妖股摇篮、上午回封、强势首板、缺口低簇、深档、三连阴巨量、
恐慌期板块出清篮子、破线日、首板次日低吸（新变体：T+1 低开时接）。
口径：信号日收盘判，次日开盘入（特殊注明除外），T+1/T+5 收盘出，费 0.15%，含退市股。
"""
import collections
import json
import statistics as st
import sys

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

ROOT = "/opt/data/fenjue"
FEE = 0.0015
Y2026 = "2026-01-01"
stocks = lp.load_universe()
tl = json.load(open(f"{ROOT}/data/regime_timeline_hcap.json"))
regime = {x["date"]: x["regime"] for x in tl}
age_map = {}
cur_r, age = None, 0
for x in tl:
    if x["regime"] != cur_r:
        cur_r, age = x["regime"], 1
    else:
        age += 1
    age_map[x["date"]] = (x["regime"], age)
mmap = json.load(open(f"{ROOT}/data/industry_map.json"))
code2ind = {str(k).zfill(6): v["industry"] for k, v in mmap.items() if isinstance(v, dict) and v.get("industry")}


def is_lu(c, cp):
    return cp > 0 and c / cp - 1 >= 0.098


ind_boards = collections.defaultdict(lambda: collections.Counter())
for code, d in stocks.items():
    if code[:2] not in ("60", "00"):
        continue
    ind = code2ind.get(code, "")
    for i in range(61, d["n"]):
        if is_lu(d["c"][i], d["c"][i - 1]):
            ind_boards[d["date"][i]][ind] += 1

F = collections.defaultdict(list)  # family -> events

for code, d in stocks.items():
    if code[:2] not in ("60", "00"):
        continue
    n = d["n"]
    for i in range(64, n - 6):
        dt = d["date"][i]
        if dt < Y2026 or d["c"][i - 1] <= 0 or d["o"][i + 1] <= 0:
            continue
        rg, age = age_map.get(dt, ("?", 0))
        c, o, v = d["c"], d["o"], d["v"]
        ma = d["ma60"][i]
        entry = o[i + 1]
        t1 = c[i + 1] / entry - 1 - FEE
        t5 = c[i + 5] / entry - 1 - FEE
        pct = c[i] / c[i - 1] - 1
        lu = is_lu(c[i], c[i - 1])
        prior_lu = any(is_lu(c[j], c[j - 1]) for j in range(i - 10, i))
        ind = code2ind.get(code, "")
        vr = v[i] / (st.mean(v[i - 20:i]) or 1)

        # 1 主线期回踩（MA60上，当日跌≥3%）
        if rg == "主线期" and ma and c[i] > ma and pct <= -0.03:
            F["主线期回踩-3%"].append((t1, t5))
        # 2 妖股期回踩（同上）
        if rg == "妖股期" and ma and c[i] > ma and pct <= -0.03:
            F["妖股期回踩-3%"].append((t1, t5))
        # 3 妖股摇篮：恐慌期/刚出恐慌期的修复日首板
        if lu and not prior_lu and rg in ("恐慌期", "妖股期") and age <= 2:
            F["修复日首板(恐/妖启动)"].append((t1, t5))
        # 4 上午回封近似：炸板日（触板未收板）次日高开≥2%收阳 → 回封确认近似
        #   用日K近似：昨触板未封（high≥涨停价 收<涨停价），今开≥昨收×1.02 且收阳
        if i > 0 and d["h"][i - 1] >= round(c[i - 2] * 1.1, 2) * 0.999 and c[i - 1] < round(c[i - 2] * 1.1, 2) and o[i] >= c[i - 1] * 1.02 and c[i] > o[i]:
            F["炸板次日高开收阳(回封近似)"].append((t1, t5))
        # 5 缺口低簇（低开低走簇，T1-MEGA 近似个股）：开跌≥3%且收在日内下1/3
        if o[i] <= c[i - 1] * 0.97 and d["h"][i] > d["l"][i] and (c[i] - d["l"][i]) / (d["h"][i] - d["l"][i]) <= 0.33:
            F["缺口低个股"].append((t1, t5))
        # 6 深档件
        if ma and pct <= -0.095 and c[i] <= ma * 0.75:
            F["深档件(收≤MA60×0.75)"].append((t1, t5))
        # 7 三连阴+巨量
        if c[i - 2] < c[i - 3] and c[i - 1] < c[i - 2] and c[i] < c[i - 1]:
            vexp = v[i] / ((v[i - 2] + v[i - 1]) / 2) if (v[i - 2] + v[i - 1]) > 0 else 1
            if vexp >= 2:
                F["三连阴+巨量>2x"].append((t1, t5))
        # 8 首板次日低吸（新变体）：昨首板，今低开≥2% → 今日开盘接
        if prior_lu is False and i > 0 and is_lu(c[i - 1], c[i - 2]) and not any(is_lu(c[j], c[j - 1]) for j in range(i - 11, i - 1)) and o[i] <= c[i - 1] * 0.98:
            F["首板次日低开接(新变体)"].append((c[i + 1] / o[i + 1] - 1 - FEE if False else t1, t5))
        # 9 恐慌期个股深跌≥9.5%（跌停）次日接
        if rg == "恐慌期" and pct <= -0.095:
            F["恐慌期跌停次日接"].append((t1, t5))
        # 10 强势首板启动期 close-entry（对照已知负，验证用）
        if lu and not prior_lu and rg == "妖股期" and age <= 2 and vr >= 1.5 and ind_boards[dt].get(ind, 0) >= 3:
            F["启动期首板(对照)"].append((c[i + 1] / c[i] - 1 - FEE, c[i + 5] / c[i] - 1 - FEE))

print(f"{'家族':<26}{'n':>6} {'T+1':>14} {'T+5':>14}  判决")
for fam, rows in sorted(F.items(), key=lambda kv: -len(kv[1])):
    if len(rows) < 25:
        continue
    t1s = [r[0] for r in rows]
    t5s = [r[1] for r in rows]
    w1 = sum(1 for x in t1s if x > 0) / len(t1s)
    w5 = sum(1 for x in t5s if x > 0) / len(t5s)
    m1, m5 = st.mean(t1s), st.mean(t5s)
    alive1 = w1 >= 0.52 and m1 > 0
    alive5 = w5 >= 0.52 and m5 > 0
    verdict = ("T1活✅" if alive1 else "") + (" T5活✅" if alive5 else "") or "死❌"
    print(f"{fam:<26}{len(rows):>6} {w1 * 100:5.1f}%/{m1 * 100:+5.2f}% {w5 * 100:5.1f}%/{m5 * 100:+5.2f}%  {verdict}")
