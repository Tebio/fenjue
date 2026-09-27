"""金股×技术指标综合测试（2026-09-27 深夜，用户点名 MA5/MACD/KDJ）。

金股事件（每月第6交易日入场=前视审计过的可执行口径），按入场日技术态分桶：
  MA5 上/下、MACD 金叉区(DIF>DEA)/死叉区、MACD 柱方向、KDJ 的 K 值档（<20/20-80/>80）、RSI6 档（<30/30-70/>70）
前向 T+20 超额 vs 300。缓存段 2020-01~2022-10。
判问题：技术过滤在金股线上是增强还是拖累（对照 #224C 回踩陷阱=等回调买输家）。
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
idx = json.load(open(f"{ROOT}/data/index_sh000001.json"))
idays = [r["date"] for r in idx]
iclose = {r["date"]: r["close"] for r in idx}

picks = {}
for fp in sorted(glob.glob(f"{ROOT}/data/gold_stock_cache/*.json")):
    mo = os.path.basename(fp)[:-5]
    rows = json.load(open(fp))
    if rows:
        picks[mo] = {r["code"] for r in rows}
months = sorted(picks)

def ema_series(c, n):
    k = 2 / (n + 1)
    out = [c[0]]
    for x in c[1:]:
        out.append(out[-1] + k * (x - out[-1]))
    return out

def kdj_k(d, i):
    """K 值（9,3,3，SMA 递推近似）"""
    if i < 9:
        return None
    k_ = 50.0
    for j in range(i - 9 + 1, i + 1):
        lo = min(d["l"][max(0, j - 8):j + 1])
        hi = max(d["h"][max(0, j - 8):j + 1])
        rsv = (d["c"][j] - lo) / (hi - lo) * 100 if hi > lo else 50
        k_ = k_ * 2 / 3 + rsv / 3
    return k_

def rsi6(c, i):
    if i < 7:
        return None
    g = sum(max(c[j] - c[j - 1], 0) for j in range(i - 5, i + 1))
    l = sum(max(c[j - 1] - c[j], 0) for j in range(i - 5, i + 1))
    return 100 if l == 0 else 100 - 100 / (1 + g / l)

cells = collections.defaultdict(list)
n_ev = 0
for mo in months:
    mdays = [d for d in idays if d.startswith(mo)]
    if len(mdays) < 6:
        continue
    d6 = mdays[5]
    for code in picks[mo]:
        d = stocks.get(code)
        if not d:
            continue
        i = bisect.bisect_left(d["date"], d6)
        if i >= d["n"] or d["date"][i] != d6 or i < 30 or i + 21 >= d["n"] or d["o"][i] <= 0:
            continue
        c = d["c"]
        e12, e26 = ema_series(c[max(0, i - 120):i + 1], 12), ema_series(c[max(0, i - 120):i + 1], 26)
        dif = e12[-1] - e26[-1]
        # DEA: DIF 的 9 日 EMA —— 用 dif 序列近似（尾部 9 日均值代）
        difs = [a - b for a, b in zip(e12[-15:], e26[-15:])]
        dea = sum(difs[-9:]) / 9
        hist = dif - dea
        difs_prev = [a - b for a, b in zip(e12[-16:-1], e26[-16:-1])]
        hist_prev = difs_prev[-1] - sum(difs_prev[-9:]) / 9
        kk = kdj_k(d, i)
        rr = rsi6(c, i)
        t20 = c[i + 20] / d["o"][i] - 1 - FEE
        i0 = bisect.bisect_left(idays, d6)
        if i0 + 20 >= len(idays):
            continue
        ex = t20 - (iclose[idays[i0 + 20]] / iclose[idays[i0]] - 1)
        n_ev += 1
        cells[("MA5", "线上" if c[i] > sum(c[i - 5:i]) / 5 else "线下")].append(ex)
        cells[("MACD", "金叉区" if dif > dea else "死叉区")].append(ex)
        cells[("MACD柱", "柱放大" if hist > hist_prev else "柱缩小")].append(ex)
        if kk is not None:
            cells[("KDJ-K", "超卖<20" if kk < 20 else "超买>80" if kk > 80 else "中间")].append(ex)
        if rr is not None:
            cells[("RSI6", "<30" if rr < 30 else ">70" if rr > 70 else "中间")].append(ex)

print(f"金股事件 {n_ev}")
print("═══ 金股 × 技术态（第6日入，T+20 超额） ═══")
for (ind, state) in sorted(cells.keys()):
    xs = cells[(ind, state)]
    if len(xs) < 80:
        print(f"  {ind:<6} {state:<8}: n={len(xs)} 薄")
        continue
    wr = sum(1 for x in xs if x > 0) / len(xs)
    print(f"  {ind:<6} {state:<8}: n={len(xs):>4} 超额 {wr * 100:.0f}%/{st.mean(xs) * 100:+.2f}pp")
