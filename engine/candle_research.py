#!/usr/bin/env python3
"""engine/candle_research.py — K线形态实证（2026-09-11 用户点名：神奇九转/大长腿/避雷针）

神奇九转(TD9简化)：连续9根收盘高于/低于4根前收盘 → 反转信号
大长腿：下影线≥实体2倍 且 下影线≥当日振幅价3%（长下影/锤头）
避雷针：上影线≥实体2倍 且 上影线≥3%（长上影/射击之星）
按 MA60 上下分组（低位大长腿=反转? 高位大长腿=上吊线）。
口径：信号日收盘确认→次日开盘成交，净-0.15%，big_kcache 全量。
"""
import json, glob, statistics as st
from pathlib import Path

KC = Path("/opt/data/fenjue/data/big_kcache")
FEE = 0.0015
OUT = Path("/opt/data/fenjue/data/candle_research_20260911.json")

stocks = {Path(fp).stem: json.loads(open(fp).read()) for fp in glob.glob(str(KC / "*.json"))}
stocks = {k: v for k, v in stocks.items() if len(v) >= 300}
print("stocks:", len(stocks))


def S(rets):
    if len(rets) < 30:
        return None
    n = len(rets)
    return {"n": n, "win%": round(sum(1 for r in rets if r > 0) / n * 100, 1),
            "mean%": round(st.mean(rets) * 100, 2), "med%": round(st.median(rets) * 100, 2)}


R = {"TD9买入": [], "TD9卖出": [], "大长腿_低位": [], "大长腿_高位": [],
     "避雷针_低位": [], "避雷针_高位": [], "随机对照": []}
import random
random.seed(42)

for ks in stocks.values():
    c = [k["close"] for k in ks]
    o = [k["open"] for k in ks]
    h = [k["high"] for k in ks]
    l = [k["low"] for k in ks]
    n = len(ks)
    for i in range(65, n - 6):
        entry = o[i + 1]
        if entry <= 0:
            continue
        r5 = c[i + 5] / entry - 1 - FEE
        ma60 = sum(c[i - 60:i]) / 60
        low_pos = c[i] <= ma60

        # TD9：连续9根 c[j]<c[j-4]（买入结构）/ c[j]>c[j-4]（卖出结构）
        if all(c[i - k] < c[i - k - 4] for k in range(9)):
            R["TD9买入"].append(r5)
        if all(c[i - k] > c[i - k - 4] for k in range(9)):
            R["TD9卖出"].append(r5)

        body = abs(c[i] - o[i])
        lower = min(c[i], o[i]) - l[i]
        upper = h[i] - max(c[i], o[i])
        rng = h[i] - l[i]
        if rng > 0:
            if lower >= max(2 * body, 0.03 * c[i]):  # 大长腿
                R["大长腿_低位" if low_pos else "大长腿_高位"].append(r5)
            if upper >= max(2 * body, 0.03 * c[i]):  # 避雷针
                R["避雷针_低位" if low_pos else "避雷针_高位"].append(r5)

keys = list(stocks.keys())
while len(R["随机对照"]) < 20000:
    ks = stocks[random.choice(keys)]
    i = random.randint(66, len(ks) - 7)
    R["随机对照"].append(ks[i + 5]["close"] / ks[i + 1]["open"] - 1 - FEE)

out = {k: S(v) for k, v in R.items()}
OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1))
for k, v in out.items():
    print(k, v)
print("saved", OUT)
