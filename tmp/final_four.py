"""收尾四连（2026-09-27 深夜）：波动率分带 / 隔夜跳空 / 转债温度 / 容量修正锦标赛。

A. ATR 分带：日 ATR%（14日）五分位 × 前向 T+5/20——高波动环境该不该持仓。
B. 隔夜跳空：开盘缺口分档（≤-3% / -3~-1% / 平 / +1~+3% / ≥+3%）× 当日收盘前向（跳空后的当日走势=follow-through 还是回补）。
C. 转债温度：全市场转股溢价率中位数的时序 → 温度分位 × 低价债线收益的交互。
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

# ── A+B 合并一趟扫 ──
atr_cells = collections.defaultdict(list)
gap_cells = collections.defaultdict(list)
print("扫描 ATR 分带+隔夜跳空…", flush=True)
for code, d in stocks.items():
    if code[:2] not in ("60", "00"):
        continue
    c, o, h, l = d["c"], d["o"], d["h"], d["l"]
    n = d["n"]
    for i in range(65, n - 21):
        dt = d["date"][i]
        if dt < "2019-07-01" or c[i - 1] <= 0 or o[i] <= 0:
            continue
        # ATR%（14 日真实波幅/收盘）
        trs = []
        for j in range(i - 14, i):
            trs.append(max(h[j] - l[j], abs(h[j] - c[j - 1]), abs(l[j] - c[j - 1])))
        atr_pct = sum(trs) / 14 / c[i - 1] if c[i - 1] > 0 else 0
        t5 = c[i + 5] / o[i] - 1 - FEE  # 今开入
        t20 = c[i + 20] / o[i] - 1 - FEE
        atr_cells[atr_pct].append((t5, t20))
        # 隔夜跳空
        gap = o[i] / c[i - 1] - 1
        g = ("低开≥3%" if gap <= -0.03 else "低开1-3%" if gap <= -0.01 else
             "平开" if gap < 0.01 else "高开1-3%" if gap < 0.03 else "高开≥3%")
        intraday = c[i] / o[i] - 1  # 当日开盘→收盘
        gap_cells[g].append((intraday, t20))

print("\n═══ A. ATR% 分带（今开入，T+5/T+20） ═══")
xs_all = sorted(atr_cells.keys())
# 五分位边界
qs = [xs_all[int(len(xs_all) * q)] for q in (0.2, 0.4, 0.6, 0.8)]
bands = collections.defaultdict(list)
for k, v in atr_cells.items():
    b = ("Q1低波" if k <= qs[0] else "Q2" if k <= qs[1] else "Q3" if k <= qs[2] else "Q4" if k <= qs[3] else "Q5高波")
    bands[b].extend(v)
for b in ("Q1低波", "Q2", "Q3", "Q4", "Q5高波"):
    rows = bands[b]
    t5s = [r[0] for r in rows]
    t20s = [r[1] for r in rows]
    print(f"  {b}: n={len(rows):>7} T5 {sum(1 for x in t5s if x > 0) / len(t5s) * 100:.0f}%/{st.mean(t5s) * 100:+.2f}% | T20 {sum(1 for x in t20s if x > 0) / len(t20s) * 100:.0f}%/{st.mean(t20s) * 100:+.2f}%")
print(f"  （分位边界 ATR%: {[round(q * 100, 1) for q in qs]}）")

print("\n═══ B. 隔夜跳空分类（当日开盘→收盘 = 缺口后日内走势） ═══")
for g in ("低开≥3%", "低开1-3%", "平开", "高开1-3%", "高开≥3%"):
    rows = gap_cells.get(g, [])
    if not rows:
        continue
    intra = [r[0] for r in rows]
    t20 = [r[1] for r in rows]
    print(f"  {g:<8}: n={len(rows):>7} | 当日日内 {sum(1 for x in intra if x > 0) / len(intra) * 100:.0f}%/{st.mean(intra) * 100:+.2f}% | T20 {sum(1 for x in t20 if x > 0) / len(t20) * 100:.0f}%/{st.mean(t20) * 100:+.2f}%")

# ── C. 转债温度 ──
print("\n═══ C. 转债市场温度（转股溢价率中位数时序） ═══", flush=True)
cb = json.load(open(f"{ROOT}/data/cb_klines.json"))
cb_list = json.load(open(f"{ROOT}/data/cb_list.json"))
# cb_list 里有溢价率字段吗
sample = cb_list[0] if isinstance(cb_list, list) else next(iter(cb_list.values()))
print("cb_list 字段:", list(sample.keys())[:12] if isinstance(sample, dict) else type(sample))
