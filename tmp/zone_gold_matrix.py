"""位置×金股×策略综合矩阵（2026-09-27，用户点名「细测+综合」）。

每个股票日打四个标签：位置带（MA20 深度）/当月金股/三连阴/恐慌剂量（当日跌幅档）。
交叉格：
  A. 位置带 × 金股（金股在深带=质量+便宜？金股在强带=逃过动量惩罚？）
  B. 位置带 × 三连阴（活策略的位置画像）
  C. 三连阴 × 金股 × 位置带（三重过滤的顶点格）
  D. 金股 × 均线排列（完美空头里的金股=极度悲观里的质量票？）
前向 T+20（次日开盘入，费0.15%）。金股段限 2020-01~2022-10（缓存范围）。
"""
import bisect
import collections
import glob
import json
import os
import statistics as st
import sys

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

ROOT = "/opt/data/fenjue"
FEE = 0.0015
stocks = lp.load_universe()

picks = {}
for fp in sorted(glob.glob(f"{ROOT}/data/gold_stock_cache/*.json")):
    mo = os.path.basename(fp)[:-5]
    rows = json.load(open(fp))
    if rows:
        picks[mo] = {r["code"] for r in rows}
gold_months = set(picks)

def zone_of(px, m20):
    dev = px / m20 - 1
    return ("线上" if dev > 0 else "浅破0~-5%" if dev > -0.05 else
            "中-5~-15%" if dev > -0.15 else "深-15~-25%" if dev > -0.25 else "极深≤-25%")

ZONES = ["线上", "浅破0~-5%", "中-5~-15%", "深-15~-25%", "极深≤-25%"]
A = collections.defaultdict(list)   # (zone, gold) -> t20
B = collections.defaultdict(list)   # (zone, three_down) -> t20
C = collections.defaultdict(list)   # (zone, gold) -> t20 for three_down only
D = collections.defaultdict(list)   # (align, gold) -> t20

print("综合扫描中…", flush=True)
for code, d in stocks.items():
    if code[:2] not in ("60", "00"):
        continue
    c, o = d["c"], d["o"]
    n = d["n"]
    for i in range(255, n - 21):
        dt = d["date"][i]
        if dt < "2019-07-01" or c[i] <= 0 or d["o"][i + 1] <= 0:
            continue
        m20 = sum(c[i - 20:i]) / 20 if all(x > 0 for x in c[i - 20:i]) else None
        if not m20:
            continue
        z = zone_of(c[i], m20)
        mo = dt[:7]
        gold = mo in gold_months and code in picks[mo]
        td = (c[i] < c[i - 1] < c[i - 2] and c[i] < o[i] and c[i - 1] < o[i - 1] and c[i - 2] < o[i - 2])
        t20 = c[i + 20] / d["o"][i + 1] - 1 - FEE
        if mo in gold_months:  # A/D 限金股段（金股标签只有这段有）
            A[(z, gold)].append(t20)
            seq = []
            ok = True
            for m in (5, 10, 20, 60, 120):
                xs = c[i - m:i]
                if not all(x > 0 for x in xs):
                    ok = False
                    break
                seq.append(sum(xs) / m)
            if ok:
                al = ("完美多头" if all(seq[j] > seq[j + 1] for j in range(4)) else
                      "完美空头" if all(seq[j] < seq[j + 1] for j in range(4)) else "纠缠")
                D[(al, gold)].append(t20)
        B[(z, td)].append(t20)  # 全时段（三连阴不要金股标签）
        if td and mo in gold_months:
            C[(z, gold)].append(t20)

def show(cells, dims, title, filter_td=None):
    print(f"\n═══ {title} ═══")
    for z in ZONES:
        row = f"  {z:<12}"
        for flag in (True, False):
            xs = cells.get((z, flag), [])
            if len(xs) < 200:
                row += f" | {'n薄':>13}"
                continue
            wr = sum(1 for x in xs if x > 0) / len(xs)
            row += f" | {wr * 100:3.0f}%/{st.mean(xs) * 100:+5.2f}%"
        print(row)

show(A, None, "A. 位置带 × 金股（2020-01~2022-10，左=当月金股 右=非金股）")
show(B, None, "B. 位置带 × 三连阴（全史，左=三连阴 右=非三连阴）")
show(C, None, "C. 三连阴内：位置带 × 金股（顶点交叉，左=金股 右=非金股）")

print("\n═══ D. 均线排列 × 金股（2020-01~2022-10，左=金股 右=非金股） ═══")
for al in ("完美多头", "纠缠", "完美空头"):
    row = f"  {al:<6}"
    for flag in (True, False):
        xs = D.get((al, flag), [])
        if len(xs) < 200:
            row += f" | {'n薄':>13}"
            continue
        wr = sum(1 for x in xs if x > 0) / len(xs)
        row += f" | {wr * 100:3.0f}%/{st.mean(xs) * 100:+5.2f}%（n={len(xs)}）"
    print(row)
