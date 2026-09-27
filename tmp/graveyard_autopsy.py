"""坟场验尸（2026-09-26）：死策略里赢家的解剖——赔率、肥尾、统一分水岭。

覆盖五个死/退役策略：
1. 三连阴裸策略（#173 证伪绿柱变小）
2. 次新股超跌（#198 证伪：上市<250交易日 + 60日回撤>30%）
3. 妖股退潮期首板（#174：妖股期段龄>4 的首板）
4. 高位避雷针（黑名单：60日涨幅>50% + 长上影）
5. 巨量三连阴（#173 唯一活的子集做对照）

每个策略：事件 T+5/T+20，胜率、平均赢、平均亏、赔率=|avg_win/avg_loss|、
肥尾 P(>+15%)、腰斩尾 P(<-10%)、赢家vs输家特征（regime/次日走势/行业）。
"""
import json
import statistics as st
import sys
from collections import Counter

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

ROOT = "/opt/data/fenjue"
FEE = 0.0015
stocks = lp.load_universe()
regime = lp.load_regime()
mmap = json.load(open(f"{ROOT}/data/industry_map.json"))
code2ind = {str(k).zfill(6): v["industry"] for k, v in mmap.items() if isinstance(v, dict) and v.get("industry")}
ages = json.load(open(f"{ROOT}/data/regime_age.json"))["ages"]

def ma(d, i, n):
    if i < n:
        return None
    xs = d["c"][i - n:i]
    return sum(xs) / n if all(x > 0 for x in xs) else None

def collect():
    ev = {"three_down": [], "newstock_dip": [], "yao_fade_fb": [], "lightning": [], "vol3down": []}
    for code, d in stocks.items():
        n = d["n"]
        if n < 80:
            continue
        listed_days = n  # 近似：上市以来的交易日数（kcache 从上市起）
        for i in range(65, n - 21):
            pc = d["c"][i - 1]
            if pc <= 0 or d["o"][i + 1] <= 0:
                continue
            chg = d["c"][i] / pc - 1
            day = d["date"][i]
            rg = regime.get(day, "平淡期")
            ag = ages.get(day, {}).get("age", 99)
            entry = d["o"][i + 1]
            t1 = d["c"][i + 1] / entry - 1 - FEE
            t5 = d["c"][i + 5] / entry - 1 - FEE
            t20 = d["c"][i + 20] / entry - 1 - FEE
            base = {"code": code, "date": day, "rg": rg, "t1": t1, "t5": t5, "t20": t20}
            # 1. 三连阴（近三日全跌）
            if (d["c"][i] < d["o"][i] and d["c"][i-1] < d["o"][i-1] and d["c"][i-2] < d["o"][i-2]
                    and d["c"][i-1] < d["c"][i-2] and d["c"][i] < d["c"][i-1]):
                ev["three_down"].append(base)
                # 5. 巨量三连阴（当日量>20日均量2倍）
                mb = d["v"][i-20:i]
                if len(mb) == 20 and all(x > 0 for x in mb) and d["v"][i] > 2 * sum(mb)/20:
                    ev["vol3down"].append(base)
            # 2. 次新股超跌：上市<250交易日 + 收盘较60日高回撤>30%
            if listed_days - (n - i) < 250:  # 该bar距上市<250交易日
                hi60 = max(d["h"][i-60:i+1])
                if hi60 > 0 and d["c"][i] / hi60 - 1 <= -0.30 and chg <= -0.05:
                    ev["newstock_dip"].append(base)
            # 3. 妖股退潮期首板：妖股期段龄>4 + 当日涨停 + 前60日无板
            if rg == "妖股期" and ag > 4 and chg >= 0.098:
                fb = all(d["c"][j] / d["c"][j-1] - 1 < 0.098 for j in range(max(1, i-60), i) if d["c"][j-1] > 0)
                if fb:
                    ev["yao_fade_fb"].append(base)
            # 4. 高位避雷针：60日涨幅>50% + 上影>(实体+下影)
            if i >= 60 and d["c"][i-60] > 0 and d["c"][i-1] / d["c"][i-60] - 1 > 0.5:
                o, c, h, l = d["o"][i], d["c"][i], d["h"][i], d["l"][i]
                if h > max(o, c) and (h - max(o, c)) > (abs(c - o) + max(o, c) - l):
                    ev["lightning"].append(base)
    return ev

print("扫描中（63万bar级）…", flush=True)
events = collect()
for k, v in events.items():
    print(f"{k}: {len(v)} 事件", flush=True)

def autopsy(rows, lb):
    if len(rows) < 100:
        print(f"\n═══ {lb}: n={len(rows)} 不足"); return
    xs5 = [r["t5"] for r in rows]; xs20 = [r["t20"] for r in rows]
    wins = [r for r in rows if r["t20"] > 0]; loses = [r for r in rows if r["t20"] <= 0]
    w_amt = [r["t20"] for r in wins]; l_amt = [r["t20"] for r in loses]
    wr = len(wins) / len(rows)
    aw = st.mean(w_amt) if w_amt else 0; al = st.mean(l_amt) if l_amt else 0
    odds = abs(aw / al) if al else 0
    fat = sum(1 for x in xs20 if x > 0.15) / len(rows)
    tail = sum(1 for x in xs20 if x < -0.10) / len(rows)
    print(f"\n═══ {lb} n={len(rows)} ═══")
    print(f"  T+5 {sum(1 for x in xs5 if x>0)/len(xs5)*100:.0f}%/{st.mean(xs5)*100:+.2f}% | T+20 {wr*100:.0f}%/{st.mean(xs20)*100:+.2f}%")
    print(f"  赔率: 平均赢{aw*100:+.2f}% vs 平均亏{al*100:+.2f}% → 赔率{odds:.2f} | 肥尾P(>+15%)={fat*100:.1f}% 腰斩尾P(<-10%)={tail*100:.1f}%")
    # 盈亏期望 = wr*aw + (1-wr)*al
    exp = wr * aw + (1 - wr) * al
    print(f"  期望复核: {exp*100:+.2f}% (=胜率×平均赢+败率×平均亏)")
    # 次日确认分水岭（龙虎榜同款）
    conf = [r for r in rows if r["t1"] > 0.03]
    deny = [r for r in rows if r["t1"] < -0.03]
    if len(conf) > 50:
        c20 = [r["t20"] for r in conf]
        print(f"  次日涨>3%确认: n={len(conf)} T20 {sum(1 for x in c20 if x>0)/len(c20)*100:.0f}%/{st.mean(c20)*100:+.2f}%")
    if len(deny) > 50:
        d20 = [r["t20"] for r in deny]
        print(f"  次日跌>3%否认: n={len(deny)} T20 {sum(1 for x in d20 if x>0)/len(d20)*100:.0f}%/{st.mean(d20)*100:+.2f}%")
    # 赢家 regime/行业集中度
    wrg = Counter(r["rg"] for r in wins); lrg = Counter(r["rg"] for r in loses)
    print(f"  赢家regime: {dict(wrg.most_common(4))}")
    wind = Counter(code2ind.get(r["code"], "?") for r in wins)
    lind = Counter(code2ind.get(r["code"], "?") for r in loses)
    top = wind.most_common(3)
    for ind, n_ in top:
        print(f"  赢家行业 {ind[:12]}: 赢{n_/max(len(wins),1)*100:.1f}% vs 输{lind.get(ind,0)/max(len(loses),1)*100:.1f}%")

for k, lb in (("three_down", "三连阴（裸）"), ("vol3down", "巨量三连阴（对照·活）"),
              ("newstock_dip", "次新股超跌"), ("yao_fade_fb", "妖股退潮期首板"),
              ("lightning", "高位避雷针")):
    autopsy(events[k], lb)
json.dump({k: v for k, v in events.items()}, open(f"{ROOT}/data/graveyard_autopsy_20260926.json", "w"), ensure_ascii=False)
print("\nsaved")
