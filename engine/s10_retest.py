#!/usr/bin/env python3
"""engine/s10_retest.py — 跌停次日接（S10）一字剔除复核（claims LIMITDOWN_NEXT_DAY 前置欠账）

原口径问题（成交假设乐观）：T+1 开盘若是一字涨停（买不进）或全天一字跌停锁死
（T+1 买进去 T+2 卖不出好价），回测却假设按开盘价成交。
三变体同跑：
  raw       原始（zoo S10 基线）
  noLU      剔除 T+1 开盘≈涨停（>=+9.5%，买不进）
  noLU_noLD 再剔除 T+1 全天一字跌停锁死（开盘≈-10%且振幅<1%）
口径：信号日 i 收盘 chg<=-9.5% → T+1 开盘买 → T+1/T+5 尾盘卖，净-0.15%。
"""
import json, glob, statistics as st
from pathlib import Path

KC = Path("/opt/data/fenjue/data/big_kcache")
FEE = 0.0015
OUT = Path("/opt/data/fenjue/data/s10_retest_20260912.json")

stocks = {}
for fp in glob.glob(str(KC / "*.json")):
    ks = json.loads(open(fp).read())
    if len(ks) >= 300:
        stocks[Path(fp).stem] = ks
print("universe:", len(stocks))


def S(rs):
    if len(rs) < 30:
        return None
    return {"n": len(rs), "win%": round(100 * sum(r > 0 for r in rs) / len(rs), 1),
            "mean%": round(100 * st.mean(rs), 2), "med%": round(100 * st.median(rs), 2)}


def run(mode, y0, y1):
    r1, r5 = [], []
    for ks in stocks.values():
        c = [k["close"] for k in ks]; o = [k["open"] for k in ks]
        h = [k["high"] for k in ks]; l = [k["low"] for k in ks]
        for i in range(65, len(ks) - 6):
            if not (y0 <= ks[i]["date"] <= y1):
                continue
            if c[i - 1] <= 0 or c[i] / c[i - 1] - 1 > -0.095:
                continue
            e = o[i + 1]
            if e <= 0:
                continue
            gap = e / c[i] - 1
            if mode != "raw" and gap >= 0.095:      # 一字/秒板涨停，买不进
                continue
            if mode == "noLU_noLD" and gap <= -0.095 and (h[i + 1] - l[i + 1]) / c[i] < 0.01:
                continue                              # 全天一字跌停锁死
            r1.append(c[i + 1] / e - 1 - FEE)
            r5.append(c[i + 5] / e - 1 - FEE)
    return {"T+1尾盘": S(r1), "T+5尾盘": S(r5)}


R = {}
for mode in ["raw", "noLU", "noLU_noLD"]:
    R[mode] = {seg: run(mode, y0, y1) for seg, y0, y1 in
               [("全段", "2019-01-01", "2026-12-31"), ("前半", "2019-01-01", "2022-12-31"),
                ("后半", "2023-01-01", "2026-12-31")]}
    print(mode, "done", flush=True)
OUT.write_text(json.dumps(R, ensure_ascii=False, indent=1))
print(json.dumps(R, ensure_ascii=False, indent=1))
print("saved", OUT)
