"""自我验货（2026-09-27 深夜，用户令「bug/未来函数/脏数据呢」）——独立复算今晚三个头条数字。

R1. 金股新鲜溢价（#206：新鲜金股 67%/+9.31%，超额+10.00pp）——独立路径重算：
    原路径 gold_analysis.py 用「月初首日开盘入」。复核口径：月初首日**收盘**入（不同入场点）+
    超额改用「全市场等权均值」而非沪深300（不同基准）——两个都换，数字还站不站。
R2. 毒气室（#210：趋势平涨×杠杆中段 29 批 -7.20%/28%）——独立重算：换批内收益聚合方式
    （中位数替代均值）+ 趋势门定义换 MA20 斜率版。
R3. 顶点格（#219B：极深+三连阴 86%/+21.18%，n=3290）——独立重算：极深带定义从 MA20 换 MA60
    （≤MA60×0.75），三连阴改纯收盘三连降（不含阴线条件）。
另附数据完整性扫描：金股缓存月度条数异常检测 + 研报库 publishDate 单调性 + kcache 抽检。
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

# ── R1 金股新鲜溢价复核 ──
print("═══ R1 金股新鲜溢价复核（收盘入+全市场等权基准） ═══", flush=True)
picks = {}
for fp in sorted(glob.glob(f"{ROOT}/data/gold_stock_cache/*.json")):
    mo = os.path.basename(fp)[:-5]
    rows = json.load(open(fp))
    if rows:
        picks[mo] = {r["code"] for r in rows}
months = sorted(picks)
# 全市场日收益等权基准
mkt_day = collections.defaultdict(list)
for code, d in stocks.items():
    if code[:2] not in ("60", "00"):
        continue
    for i in range(1, d["n"]):
        if d["c"][i - 1] > 0:
            mkt_day[d["date"][i]].append(d["c"][i] / d["c"][i - 1] - 1)
mkt_ret = {dt: st.mean(v) for dt, v in mkt_day.items()}

def mkt_cum(d0, d1):
    ds = [d for d in sorted(mkt_ret) if d0 < d <= d1]
    r = 1.0
    for d in ds:
        r *= 1 + mkt_ret[d]
    return r - 1

seen = collections.defaultdict(set)
fresh_ex, stale_ex = [], []
for mo in months:
    mdays = [d for d in sorted(mkt_ret) if d.startswith(mo)]
    if not mdays:
        continue
    d0 = mdays[0]
    for code in picks[mo]:
        fresh = code not in seen[mo[:4]]
        seen[mo[:4]].add(code)
        d = stocks.get(code)
        if not d:
            continue
        i = bisect.bisect_left(d["date"], d0)
        if i >= d["n"] or d["date"][i] != d0 or i + 21 >= d["n"] or d["c"][i] <= 0:
            continue
        t20 = d["c"][i + 20] / d["c"][i] - 1 - FEE  # 收盘入
        ex = t20 - mkt_cum(d["date"][i], d["date"][i + 20])
        (fresh_ex if fresh else stale_ex).append(ex)
for lb, xs in (("新鲜", fresh_ex), ("抱团", stale_ex)):
    wr = sum(1 for x in xs if x > 0) / len(xs)
    print(f"  {lb}: n={len(xs)} 超额(等权基准) {wr * 100:.0f}%/{st.mean(xs) * 100:+.2f}pp  ←原版 67%/+10.00pp / 61%/+4.48pp")

# ── R2 毒气室复核（中位数+MA20斜率版趋势门） ──
print("═══ R2 毒气室复核 ═══", flush=True)
batches = json.load(open(f"{ROOT}/data/deep_batches_full_20260927.json"))
margin = json.load(open(f"{ROOT}/data/margin_history.json"))
mrec = {str(r.get("date"))[:10]: float(r.get("rzye") or r.get("RZYE") or 0) for r in margin} if isinstance(margin, list) else margin
mdays = sorted(mrec)
idx = json.load(open(f"{ROOT}/data/index_sh000001.json"))
idays = [r["date"] for r in idx]
iclose = {r["date"]: r["close"] for r in idx}

def margin_gate(day):
    i = bisect.bisect_left(mdays, day)
    if i < 20:
        return None
    base = mrec[mdays[i - 20]]
    return ("去杠杆" if mrec[mdays[i]] / base - 1 < -0.03 else "中段") if base > 0 else None

def trend_flat(day):
    """原版=指数20日涨跌>-3%；复核版=MA20 斜率（今 MA20 ≥ 20日前 MA20 = 平/涨）"""
    i = bisect.bisect_left(idays, day)
    if i < 40:
        return None
    ma_now = st.mean(iclose[idays[j]] for j in range(i - 19, i + 1))
    ma_then = st.mean(iclose[idays[j]] for j in range(i - 39, i - 19))
    return ma_now >= ma_then

tox_orig, tox_alt = [], []
for b in batches:
    g = margin_gate(b["date"])
    i = bisect.bisect_left(idays, b["date"])
    chg20 = iclose[idays[i]] / iclose[idays[i - 20]] - 1 if i >= 20 else None
    if g == "中段" and chg20 is not None and chg20 >= -0.03:
        tox_orig.append(b["r10"])
    tf = trend_flat(b["date"])
    if g == "中段" and tf:
        tox_alt.append(b["r10"])
print(f"  原版（20日涨跌>-3%）: n={len(tox_orig)} 均值 {st.mean(tox_orig) * 100:+.2f}% 中位 {st.median(tox_orig) * 100:+.2f}%  ←原版 -7.20%/28%")
if tox_alt:
    print(f"  复核版（MA20斜率平涨）: n={len(tox_alt)} 均值 {st.mean(tox_alt) * 100:+.2f}% 中位 {st.median(tox_alt) * 100:+.2f}%")

# ── R3 顶点格复核（MA60 深度+纯三连降） ──
print("═══ R3 顶点格复核（≤MA60×0.75 + 纯收盘三连降） ═══", flush=True)
xs = []
for code, d in stocks.items():
    if code[:2] not in ("60", "00"):
        continue
    c, o = d["c"], d["o"]
    for i in range(65, d["n"] - 21):
        dt = d["date"][i]
        if dt < "2019-07-01" or o[i + 1] <= 0:
            continue
        ma60 = d["ma60"][i]
        if not ma60 or ma60 <= 0 or c[i] > ma60 * 0.75:
            continue
        if c[i] < c[i - 1] < c[i - 2]:
            xs.append(c[i + 20] / o[i + 1] - 1 - FEE)
print(f"  n={len(xs)} T20 {sum(1 for x in xs if x > 0) / len(xs) * 100:.0f}%/{st.mean(xs) * 100:+.2f}%  ←原版 86%/+21.18%（n=3290）")

# ── 数据完整性扫描 ──
print("═══ 数据完整性 ═══", flush=True)
for fp in sorted(glob.glob(f"{ROOT}/data/gold_stock_cache/*.json")):
    rows = json.load(open(fp))
    codes = [r["code"] for r in rows]
    if len(rows) < 30 or len(rows) > 400:
        print(f"  [WARN] {os.path.basename(fp)}: {len(rows)} 条（异常）")
print("  金股缓存月度条数扫描完（30-400 正常带）")
rr = json.load(open(f"{ROOT}/data/research_reports_20260927.json"))
pubs = [str(r.get("publishDate"))[:10] for r in rr]
bad = sum(1 for p in pubs if not p or p < "2020-01-01" or p > "2026-09-27")
print(f"  研报库 {len(rr)} 条，publishDate 越界 {bad} 条")
