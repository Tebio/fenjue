"""盲点清算（2026-09-27 上午）：
A. 金股效应的市值分层对照——同市值五分位内 金股 vs 非金股，排除「金股=大盘股代理」嫌疑。
B. 金股×深档生产批交叉——深档批里的票有多少当月金股覆盖？覆盖的是不是更强？
"""
import bisect
import glob
import json
import os
import statistics as st
import sys
from collections import defaultdict

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

ROOT = "/opt/data/fenjue"
FEE = 0.0015
stocks = lp.load_universe()
lp.build_xsection(stocks)  # _XCAP quintile boundaries

picks = {}
for fp in sorted(glob.glob(f"{ROOT}/data/gold_stock_cache/*.json")):
    mo = os.path.basename(fp)[:-5]
    rows = json.load(open(fp))
    if rows:
        picks[mo] = set(r["code"] for r in rows)
months = sorted(picks)
mo_set = set(months)
print(f"金股 {len(months)} 月就绪；市值分位边界就绪={lp._XCAP is not None}", flush=True)

# 市值五分位：cap_hist 当日市值 → 当日全市场分位（粗口径：用当日全市场市值分布五分位）
# law_pipeline 的 _XCAP 是 (dates, caps) per stock；造当日横截面五分位需全市场遍历——用替代：
# 用「当日市值绝对值分桶」（<50亿/50-100/100-300/300-1000/>1000亿），足够识别规模代理
def cap_of(code, day):
    packed = lp._XCAP.get(code) if hasattr(lp, "_XCAP") else None
    return None

# _XCAP 在 build_xsection 里是 quintile 边界不是逐股市值；直接用 cap_hist 文件
import pathlib
CAPDIR = pathlib.Path(f"{ROOT}/data/cap_hist")
def stock_cap_at(code, day):
    fp = CAPDIR / f"{code}.json"
    if not fp.exists():
        return None
    rows = json.load(open(fp))
    dates = [r[0] for r in rows]
    caps = [r[2] for r in rows]  # [date, 换手率, 流通市值(亿)]
    j = bisect.bisect_right(dates, day) - 1
    return caps[j] if j >= 0 else None

CAP_CACHE = {}
def cap_bucket(code, day):
    key = (code, day[:7])
    if key in CAP_CACHE:
        return CAP_CACHE[key]
    c = stock_cap_at(code, day)
    if c is None:
        CAP_CACHE[key] = None
        return None
    # cap_hist 单位：亿元？ 看数据——之前 #13 用过 cap 20-400 亿口径
    b = ("<50亿" if c < 50 else "50-100亿" if c < 100 else "100-300亿" if c < 300
         else "300-1000亿" if c < 1000 else ">1000亿")
    CAP_CACHE[key] = b
    return b

ev = json.load(open(f"{ROOT}/data/graveyard_autopsy_20260926.json"))
print("═══ A. 市值分层内 金股 vs 非金股（三连阴+避雷针合并样本，2020-01~2022-10） ═══", flush=True)
cells = defaultdict(lambda: {"g": [], "n": []})
for key in ("three_down", "lightning"):
    for r in ev[key]:
        mo = r["date"][:7]
        if mo not in mo_set:
            continue
        b = cap_bucket(r["code"], r["date"])
        if b is None:
            continue
        tag = "g" if r["code"] in picks[mo] else "n"
        cells[b][tag].append(r["t20"])
for b in ("<50亿", "50-100亿", "100-300亿", "300-1000亿", ">1000亿"):
    g, n = cells[b]["g"], cells[b]["n"]
    if len(g) < 30 or len(n) < 100:
        print(f"  {b}: 金股n={len(g)} 非金股n={len(n)} 不足")
        continue
    gw = sum(1 for x in g if x > 0) / len(g); nw = sum(1 for x in n if x > 0) / len(n)
    print(f"  {b:<10} 金股 n={len(g):>5} {gw*100:.0f}%/{st.mean(g)*100:+.2f}% | 非金股 n={len(n):>6} {nw*100:.0f}%/{st.mean(n)*100:+.2f}% | 净edge {st.mean(g)*100 - st.mean(n)*100:+.2f}pp")

# 金股自身的市值分布（它本来就是大盘股俱乐部吗）
print("═══ 金股名单的市值分布 ═══")
dist = defaultdict(int)
for mo in months:
    for code in picks[mo]:
        b = cap_bucket(code, mo + "-15")
        dist[b] += 1
tot = sum(dist.values())
for b in ("<50亿", "50-100亿", "100-300亿", "300-1000亿", ">1000亿"):
    print(f"  {b:<10} {dist.get(b,0)/tot*100:.1f}%")

print("═══ B. 金股×深档生产批（2020-01~2022-10 内的批） ═══", flush=True)
# 深档批重建：簇≥5+深跌≤-35%（与生产口径一致，tmp/deep_optimize 同款逻辑简化版）
# 直接读生产批记录文件若有
import subprocess
batch_fp = f"{ROOT}/data/deep_batches_20260922.json"
if not os.path.exists(batch_fp):
    cands = sorted(glob.glob(f"{ROOT}/data/*deep*batch*.json") + glob.glob(f"{ROOT}/data/*deep_low*.json"))
    batch_fp = cands[0] if cands else None
if batch_fp and os.path.exists(batch_fp):
    batches = json.load(open(batch_fp))
    print(f"  批文件 {os.path.basename(batch_fp)}: {len(batches) if isinstance(batches, list) else 'dict'}")
    # 遍历批内股票，看金股覆盖
    gcov, gnoc = [], []
    items = batches if isinstance(batches, list) else batches.get("batches", [])
    for b_ in items:
        day = b_.get("date") or b_.get("signal_date", "")
        mo = day[:7]
        if mo not in mo_set:
            continue
        for leg in (b_.get("stocks") or b_.get("legs") or []):
            code = leg.get("code") if isinstance(leg, dict) else leg
            r10 = leg.get("t10") or leg.get("r10") if isinstance(leg, dict) else None
            if r10 is None:
                continue
            (gcov if code in picks[mo] else gnoc).append(r10)
    print(f"  深档腿: 金股覆盖 n={len(gcov)} vs 未覆盖 n={len(gnoc)}")
    if len(gcov) >= 15:
        print(f"  金股腿 T10 {sum(1 for x in gcov if x>0)/len(gcov)*100:.0f}%/{st.mean(gcov)*100:+.2f}% | 非金股腿 {sum(1 for x in gnoc if x>0)/len(gnoc)*100:.0f}%/{st.mean(gnoc)*100:+.2f}%")
else:
    print("  深档批文件未找到，跳过")
