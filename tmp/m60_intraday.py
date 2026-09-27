"""m60 日内形态研究（2026-09-27 深夜，2 年 60 分钟线，3377 只）。

日内形态四测（入场=次日开盘，零前视，费0.15%）：
  A. 尾盘拉升：最后一小时 bar 涨幅 ≥+2%（抢筹还是诱多？）
  B. 尾盘跳水：最后一小时 ≤-2%
  C. 开盘放量：首小时量占全日 ≥45%（早盘信息密度）
  D. 收在 VWAP 上方/下方（收盘强弱）
口径注记：m60 为不复权价（#26 B6），日内 bar 收益不受影响，跨日前向含除权噪声（可忽略级）。
"""
import bisect
import collections
import glob
import json
import statistics as st
import sys

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

ROOT = "/opt/data/fenjue"
FEE = 0.0015
stocks = lp.load_universe()

cells = collections.defaultdict(list)
n_days = 0
for fp in sorted(glob.glob(f"{ROOT}/data/m60_cache/*.json")):
    code = fp.rsplit("/", 1)[-1][:-5]
    if code[:2] not in ("60", "00"):
        continue
    d = stocks.get(code)
    if not d:
        continue
    try:
        bars = json.load(open(fp))
    except Exception:
        continue
    # 按日分组
    by_day = collections.defaultdict(list)
    for b in bars:
        by_day[b["day"][:10]].append(b)
    dates = sorted(by_day)
    for k in range(1, len(dates) - 6):
        day = dates[k]
        bb = by_day[day]
        if len(bb) < 4:
            continue
        n_days += 1
        o = [float(x["open"]) for x in bb]
        c = [float(x["close"]) for x in bb]
        v = [float(x["volume"]) for x in bb]
        last_ret = c[-1] / o[-1] - 1
        first_vol_share = v[0] / sum(v) if sum(v) > 0 else 0
        vwap = sum(x * y for x, y in zip(c, v)) / sum(v) if sum(v) > 0 else c[-1]
        close_vs_vwap = c[-1] / vwap - 1
        # 次日开盘→T+1 收盘 / T+5（从 big_kcache 对齐）
        i = bisect.bisect_left(d["date"], day)
        if i >= d["n"] - 6 or d["date"][i] != day or d["o"][i + 1] <= 0:
            continue
        t1 = d["c"][i + 1] / d["o"][i + 1] - 1 - FEE
        t5 = d["c"][i + 5] / d["o"][i + 1] - 1 - FEE
        cells["全部"].append((t1, t5))
        if last_ret >= 0.02:
            cells["尾盘拉升≥2%"].append((t1, t5))
        elif last_ret <= -0.02:
            cells["尾盘跳水≤-2%"].append((t1, t5))
        if first_vol_share >= 0.45:
            cells["首小时量≥45%"].append((t1, t5))
        if close_vs_vwap > 0.005:
            cells["收>VWAP+0.5%"].append((t1, t5))
        elif close_vs_vwap < -0.005:
            cells["收<VWAP-0.5%"].append((t1, t5))

print(f"股票日 {n_days}")
print("═══ m60 日内形态（次日开盘入） ═══")
for lb, rows in cells.items():
    if len(rows) < 500:
        print(f"  {lb}: n={len(rows)} 薄")
        continue
    t1s = [r[0] for r in rows]
    t5s = [r[1] for r in rows]
    print(f"  {lb:<14}: n={len(rows):>7} | T+1 {sum(1 for x in t1s if x > 0) / len(t1s) * 100:.0f}%/{st.mean(t1s) * 100:+.2f}% | T+5 {sum(1 for x in t5s if x > 0) / len(t5s) * 100:.0f}%/{st.mean(t5s) * 100:+.2f}%")
json.dump({k: len(v) for k, v in cells.items()}, open(f"{ROOT}/data/m60_intraday_20260927.json", "w"))
print("saved")
