#!/usr/bin/env python3
"""engine/alpha_by_breadth.py — 策略A 同日市场调整 + 按跌停广度分档（2026-10-19）

待办：#324 ⑤
  ① 策略A 的同日市场调整（减等权）用不复权新样本重算
  ② 按「当日跌停家数滚动分位」分档，钉死加权悖论：
     预期 —— 跌停成潮时个股反弹差，跌停零星时个股好
"""
import json
import statistics as st
from pathlib import Path

ROOT = Path('/opt/data/fenjue')
UNADJ = ROOT / 'data/big_kcache_unadj'
FQ = ROOT / 'data/big_kcache'
HOLD = 5
MB = ('600', '601', '603', '605', '000', '001', '002', '003')
EPS = 0.0015


def lp(pc, r):
    return round(pc * r + 1e-9, 2)


def mt(a, b):
    return abs(a - b) <= EPS


events = []          # (signal_date, buy_date, sell_date, ret, is_st)
ld_days = {}         # date -> 封死跌停家数
mkt_acc = {}
cal_set = set()

for p in FQ.glob('*.json'):
    c = p.stem
    if c[:3] not in MB:
        continue
    uf = UNADJ / f'{c}.json'
    if not uf.exists():
        continue
    try:
        fk = json.loads(p.read_text())
        uk = json.loads(uf.read_text())
    except Exception:
        continue
    if not isinstance(fk, list) or len(fk) < 130 or not isinstance(uk, list):
        continue
    ud = {k['date']: k for k in uk}
    n = len(fk)
    cal_set.update(k['date'] for k in fk)
    for i in range(1, n):
        pc = fk[i - 1]['close']
        if pc > 0:
            a = mkt_acc.setdefault(fk[i]['date'], [0.0, 0])
            a[0] += fk[i]['close'] / pc - 1
            a[1] += 1

    closes = [k['close'] for k in fk]
    ma = [None] * n
    s = 0.0
    for i in range(n):
        s += closes[i]
        if i >= 60:
            s -= closes[i - 60]
        if i >= 59:
            ma[i] = s / 60

    for i in range(60, n - 1):
        u0 = ud.get(fk[i - 1]['date'])
        u1 = ud.get(fk[i]['date'])
        if not u0 or not u1 or u0['close'] <= 0:
            continue
        is10 = mt(u1['close'], lp(u0['close'], 0.9))
        is5 = mt(u1['close'], lp(u0['close'], 0.95))
        if not (is10 or is5):
            continue
        d = fk[i]['date']
        ld_days[d] = ld_days.get(d, 0) + 1
        if i + 1 + HOLD >= n:
            continue
        un = ud.get(fk[i + 1]['date'])
        if not un:
            continue
        if un['open'] >= lp(u1['close'], 1.1 if is10 else 1.05) - EPS:
            continue
        if ma[i] is None or closes[i] > ma[i]:
            continue
        bi, si = i + 1, i + 1 + HOLD
        bpx, spx = fk[bi]['open'], fk[si]['close']
        if bpx <= 0 or spx <= 0:
            continue
        events.append((d, fk[bi]['date'], fk[si]['date'], spx / bpx - 1, is5))

cal = sorted(cal_set)
ci = {d: i for i, d in enumerate(cal)}
mkt = {d: v[0] / v[1] for d, v in mkt_acc.items() if v[1] >= 500}
print(f'事件 {len(events)}   有跌停的交易日 {len(ld_days)}')

# 市场窗口收益
def mret5(bd, sd):
    jb, js = ci.get(bd), ci.get(sd)
    if jb is None or js is None:
        return None
    acc, ok = 1.0, True
    for k in range(jb, js + 1):
        v = mkt.get(cal[k])
        if v is None:
            ok = False
            break
        acc *= 1 + v
    return acc - 1 if ok else None


# 滚动 250 日分位
seq = [ld_days.get(d, 0) for d in cal]
def pct_of(j, win=250):
    lo = max(0, j - win)
    hist = seq[lo:j]
    if len(hist) < 120:
        return None
    cur = seq[j]
    return sum(1 for x in hist if x < cur) / len(hist) * 100


rows = []
for d, bd, sd, r, is_st in events:
    mr = mret5(bd, sd)
    p = pct_of(ci[d])
    if mr is None or p is None:
        continue
    rows.append((r * 100, (r - mr) * 100, p, is_st))

print(f'\n=== ① 策略A 不复权新样本：同日市场调整 ===')
print(f"{'口径':<16}{'n':>7}{'均值':>9}{'胜率':>8}{'t(naive)':>10}")
for lab, idx in (('原始', 0), ('减全市场等权', 1)):
    R = [x[idx] for x in rows]
    t = st.mean(R) / st.stdev(R) * (len(R) ** 0.5)
    print(f'  {lab:<14}{len(R):>7}{st.mean(R):>+8.2f}%'
          f'{sum(1 for x in R if x>0)/len(R)*100:>7.1f}%{t:>10.2f}')

print(f'\n=== ② 按当日跌停家数滚动分位分档（验证加权悖论）===')
print(f"{'分位档':<12}{'n':>7}{'原始':>9}{'超额':>9}{'胜率':>8}")
bands = [(0, 20), (20, 40), (40, 60), (60, 75), (75, 90), (90, 95), (95, 100.1)]
for lo, hi in bands:
    sub = [x for x in rows if lo <= x[2] < hi]
    if len(sub) < 30:
        print(f'  {f"{lo}-{hi:g}":<10}{len(sub):>7}  样本不足')
        continue
    R = [x[0] for x in sub]
    E = [x[1] for x in sub]
    print(f'  {f"{lo}-{hi:g}":<10}{len(sub):>7}{st.mean(R):>+8.2f}%{st.mean(E):>+8.2f}%'
          f'{sum(1 for x in R if x>0)/len(R)*100:>7.1f}%')

print(f'\n=== ③ ST(5%档) vs 主板10%档 ===')
for lab, flag in (('10% 档', False), ('ST 5% 档', True)):
    sub = [x for x in rows if x[3] is flag]
    if len(sub) < 30:
        continue
    R = [x[0] for x in sub]
    E = [x[1] for x in sub]
    print(f'  {lab:<10}{len(sub):>7}{st.mean(R):>+8.2f}%{st.mean(E):>+8.2f}%'
          f'{sum(1 for x in R if x>0)/len(R)*100:>7.1f}%')
