#!/usr/bin/env python3
"""engine/panic_percentile.py — 绝对家数 vs 滚动分位数口径对决（2026-10-19）

K3 的指控（可能是今天最实质的一条）：
  绝对跌停家数跨年不可比——上市家数增长、ST改革、20cm板块扩容，使分布右移。
  今天 25 只的分位数可能远低于 2019 年的 25 只，实际强度可能落在「10-23 基本没用」的区域。
  修法：用滚动 250 日分位数，弃绝对家数。

本脚本：
  A. 输出各年跌停家数分布，看今天的 25 只落在各年的什么分位
  B. 用滚动 250 日分位数重构信号，与绝对门槛 ≥24/≥25 对决
"""
import json
import statistics as st
from pathlib import Path

ROOT = Path('/opt/data/fenjue')
KC = ROOT / 'data/big_kcache'
COST, HOLD = 0.002, 5
MB = ('600', '601', '603', '605', '000', '001', '002', '003')

data = {}
for p in KC.glob('*.json'):
    c = p.stem
    if c[:3] not in MB:
        continue
    try:
        ks = json.loads(p.read_text())
    except Exception:
        continue
    if isinstance(ks, list) and len(ks) >= 130:
        data[c] = ks


def is_ld(ks, i):
    if i < 1 or i >= len(ks):
        return False
    pc = ks[i - 1]['close']
    if pc <= 0:
        return False
    lim = round(pc * 0.9, 2)
    return lim * 0.994 <= ks[i]['close'] <= lim * 1.0005


n_dn = {}
for c, ks in data.items():
    for i in range(1, len(ks)):
        if is_ld(ks, i):
            n_dn[ks[i]['date']] = n_dn.get(ks[i]['date'], 0) + 1

IX = {r['date']: r for r in json.loads((ROOT / 'data/index_sh000001.json').read_text())}
cal = sorted({k['date'] for ks in data.values() for k in ks})
ci = {d: i for i, d in enumerate(cal)}


def trade(d):
    j = ci.get(d)
    if j is None or j + 1 + HOLD >= len(cal):
        return None
    bd, sd = cal[j + 1], cal[j + 1 + HOLD]
    if bd not in IX or sd not in IX:
        return None
    bp, sp = IX[bd]['open'], IX[sd]['close']
    if bp <= 0 or sp <= 0:
        return None
    return (sp / bp - 1 - COST) * 100


# ── A. 各年家数分布 ────────────────────────────────
series = [(d, n_dn.get(d, 0)) for d in cal]
print('=== A. 绝对跌停家数分年分布（K3 说分布整体右移）===')
print(f"{'年份':<7}{'中位':>6}{'P75':>6}{'P90':>7}{'P95':>7}{'最大':>7}{'≥24天数':>9}{'今天的25在该年分位':>19}")
for y in sorted({d[:4] for d, _ in series}):
    v = sorted(n for d, n in series if d[:4] == y)
    if len(v) < 20:
        continue
    pct = sum(1 for x in v if x < 25) / len(v) * 100
    ge24 = sum(1 for x in v if x >= 24)
    print(f'  {y:<5}{st.median(v):>6.0f}{v[int(len(v)*.75)]:>6}{v[int(len(v)*.90)]:>7}'
          f'{v[int(len(v)*.95)]:>7}{max(v):>7}{ge24:>9}{pct:>17.1f}%')

# ── B. 滚动分位数口径 ──────────────────────────────
print('\n=== B. 滚动 250 日分位数口径 vs 绝对家数 ===')


def rolling_pct(d, win=250):
    j = ci[d]
    lo = max(0, j - win)
    hist = [n_dn.get(cal[k], 0) for k in range(lo, j)]
    if len(hist) < 120:
        return None
    cur = n_dn.get(d, 0)
    return sum(1 for x in hist if x < cur) / len(hist) * 100


print(f"{'规则':<26}{'信号':>6}{'可兑现':>7}{'均值':>9}{'胜率':>8}")
res = {}
for th in (24, 25):
    days = sorted(d for d in n_dn if n_dn[d] >= th)
    R = [trade(d) for d in days]
    R = [x for x in R if x is not None]
    res[f'绝对≥{th}'] = R
    print(f'  {"绝对跌停家数 ≥"+str(th):<24}{len(days):>6}{len(R):>7}{st.mean(R):>+8.2f}%'
          f'{sum(1 for x in R if x>0)/len(R)*100:>7.1f}%')

for q in (90, 95, 97, 98):
    days = sorted(d for d in cal if (rolling_pct(d) or -1) >= q)
    R = [trade(d) for d in days]
    R = [x for x in R if x is not None]
    if len(R) < 10:
        continue
    res[f'分位≥{q}'] = R
    print(f'  {"滚动250日分位 ≥"+str(q):<24}{len(days):>6}{len(R):>7}{st.mean(R):>+8.2f}%'
          f'{sum(1 for x in R if x>0)/len(R)*100:>7.1f}%')

print('\n=== C. 今天 25 只在各口径下的强度 ===')
today_pct = rolling_pct('2026-10-16')
if today_pct is not None:
    print(f'  2026-10-16（库内最后一日）跌停 {n_dn.get("2026-10-16",0)} 只，'
          f'滚动250日分位 {today_pct:.1f}%')
print('  2026-10-19 跌停 25 只（新浪快照口径）')
y26 = sorted(n for d, n in series if d[:4] == '2026')
print(f'  25 只落在 2026 年内分位: {sum(1 for x in y26 if x < 25)/len(y26)*100:.1f}%')
y19 = sorted(n for d, n in series if d[:4] == '2019')
print(f'  25 只落在 2019 年内分位: {sum(1 for x in y19 if x < 25)/len(y19)*100:.1f}%')
