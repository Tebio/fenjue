"""欠账清算六连测（2026-09-20）。
T1 T1-MEGA组合层账本（10槽分散 vs 限3，巨簇日）
T2 主线期/恐慌期剂量曲线（妖股期已有）
T3 巨簇日出场 T+1/T+2/T+3 衰减
T4 簇阈值 15/18/20/22/25 寻优
T5 巨簇日×周一（次日是周一接不接）
T6 妖股期孤立跌停（X2泄漏口440）：次日开盘买 T+5/T+10/T+20 池级
"""
import sys, json, statistics as st
from datetime import date
from collections import defaultdict
sys.path.insert(0, 'engine')
import law_pipeline as lp

stocks = lp.load_universe()
lp.build_xsection(stocks)
regime = lp.load_regime()
FEE = 0.003
WIN0, WIN1 = '2019-01-01', '2026-09-18'

def wd(ds):
    return date(int(ds[:4]), int(ds[5:7]), int(ds[8:10])).weekday()

# ── 缺口低全池（含 fwd 1/2/3 日）──
det = lp.REGISTRY['组合_缺口低开_低位阳线_避周一']
pool = []
for code, d in stocks.items():
    n = d['n']
    c, h, v = d['c'], d['h'], d['v']
    for i in range(lp.START, n - 4):
        dt = d['date'][i]
        if dt < WIN0 or dt > WIN1 or lp._epx(d, i) <= 0:
            continue
        try:
            if not det(d, i):
                continue
        except Exception:
            continue
        vols = [v[x] for x in range(max(1, i - 5), i)]
        vr = v[i] / (sum(vols) / len(vols)) if vols and sum(vols) > 0 else 1
        ep = lp._epx(d, i)
        pool.append({'dt': dt, 'code': code, 'rg': regime.get(dt, '?'),
                     'r1': c[i + 2] / ep - 1 - FEE, 'r2': c[i + 3] / ep - 1 - FEE,
                     'r3': c[i + 4] / ep - 1 - FEE, 'vr': vr,
                     'entry_d': d['date'][i + 1]})
by_day = defaultdict(list)
for r in pool:
    by_day[r['dt']].append(r)
day_n = {dt: len(rows) for dt, rows in by_day.items()}

# ── T4 阈值寻优（妖股期，T+1口径=池级）──
print('== T4 簇阈值寻优（妖股期，池级 T+1）==')
for th in (12, 15, 18, 20, 22, 25, 30):
    rets = [r['r1'] for dt, rows in by_day.items()
            if len(rows) >= th and regime.get(dt) == '妖股期' for r in rows]
    nd = sum(1 for dt, rows in by_day.items() if len(rows) >= th and regime.get(dt) == '妖股期')
    if rets:
        w = sum(1 for x in rets if x > 0)
        print(f'  簇≥{th}: {nd}天 {len(rets)}信号 胜率{100*w/len(rets):.0f}% 均{100*st.mean(rets):+.2f}%')

# ── T2 主线期/恐慌期剂量曲线 ──
print('\n== T2 各 regime 剂量曲线（池级 T+1）==')
for rg in ('主线期', '恐慌期', '平淡期'):
    for lo, hi, lb in ((1, 3, '1-3'), (4, 9, '4-9'), (10, 19, '10-19'), (20, 999, '≥20')):
        rets = [r['r1'] for dt, rows in by_day.items()
                if lo <= len(rows) <= hi and regime.get(dt) == rg for r in rows]
        if len(rets) >= 30:
            w = sum(1 for x in rets if x > 0)
            print(f'  {rg} 簇{lb}: {len(rets)}信号 胜率{100*w/len(rets):.0f}% 均{100*st.mean(rets):+.2f}%')

# ── T3 巨簇日出场衰减（妖股期簇≥20）──
print('\n== T3 巨簇日出场衰减（妖股期簇≥20，池级）==')
mega = [r for dt, rows in by_day.items() if len(rows) >= 20 and regime.get(dt) == '妖股期' for r in rows]
for nm, k in (('T+1', 'r1'), ('T+2', 'r2'), ('T+3', 'r3')):
    v = [r[k] for r in mega]
    w = sum(1 for x in v if x > 0)
    print(f'  {nm}: 胜率{100*w/len(v):.0f}% 均{100*st.mean(v):+.2f}%')

# ── T5 巨簇日×周一 ──
print('\n== T5 巨簇日×入场日周几（妖股期簇≥20）==')
mon = [r['r1'] for r in mega if wd(r['entry_d']) == 0]
non = [r['r1'] for r in mega if wd(r['entry_d']) != 0]
for lb, v in (('周一入场', mon), ('非周一', non)):
    if v:
        w = sum(1 for x in v if x > 0)
        print(f'  {lb}: {len(v)}信号 胜率{100*w/len(v):.0f}% 均{100*st.mean(v):+.2f}%')

# ── T1 组合层账本（妖股期巨簇日，次日开盘分散接入，T+1 卖）──
print('\n== T1 组合层账本（妖股期簇≥20，T+1，5万）==')
mega_days = sorted(dt for dt, rows in by_day.items() if len(rows) >= 20 and regime.get(dt) == '妖股期')
for cap_n in (3, 5, 10):
    pnl = 0.0
    taken = 0
    for dt in mega_days:
        rows = sorted(by_day[dt], key=lambda r: -r['vr'])[:cap_n]  # 量比排序保成交
        for r in rows:
            pnl += r['r1'] * 5000
            taken += 1
    wins_p = sum(1 for dt in mega_days for r in sorted(by_day[dt], key=lambda r: -r['vr'])[:cap_n] if r['r1'] > 0)
    print(f'  日接{cap_n}张: {len(mega_days)}天 {taken}笔 总盈亏{pnl:+,.0f}元 胜率{100*wins_p/taken:.0f}%')
print(f'  （巨簇日 {len(mega_days)} 天/8年 ≈ {len(mega_days)/7.7:.1f} 次/年）')

# ── T6 妖股期孤立跌停（X2 泄漏口）──
print('\n== T6 妖股期孤立跌停（非大簇日，池级）==')
iso = []
for code, d in stocks.items():
    n = d['n']
    c = d['c']
    for i in range(lp.START, n - 21):
        dt = d['date'][i]
        if dt < WIN0 or dt > WIN1:
            continue
        if regime.get(dt) != '妖股期':
            continue
        if c[i] / c[i - 1] - 1 > -0.095:
            continue
        if lp._epx(d, i) <= 0:
            continue
        # 孤立=当日缺口低簇<8（非大簇）
        if day_n.get(dt, 0) >= 8:
            continue
        ep = lp._epx(d, i)
        iso.append({'r5': c[i + 5] / ep - 1 - FEE, 'r10': c[i + 10] / ep - 1 - FEE,
                    'r20': c[i + 20] / ep - 1 - FEE})
if iso:
    for nm in ('r5', 'r10', 'r20'):
        v = [r[nm] for r in iso]
        w = sum(1 for x in v if x > 0)
        big_win = sum(1 for x in v if x > 0.20)
        print(f'  {nm[1:]}: n={len(v)} 胜率{100*w/len(v):.0f}% 均{100*st.mean(v):+.2f}% 中位{100*st.median(v):+.2f}% | >+20%占比{100*big_win/len(v):.0f}%')