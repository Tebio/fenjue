"""大簇日收紧测试：J5 + 只在 簇≥N 或 ldc≥M 的日子入场，胜率能否向池级 70% 回归。
K1 簇≥8（恐慌族当日信号数）；K2 ldc≥30；K3 ldc≥50（复活门级大恐慌）；K4 簇≥8或ldc≥30
"""
import sys, json, statistics as st
sys.path.insert(0, 'engine')
import law_pipeline as lp

stocks = lp.load_universe()
lp.build_xsection(stocks)
regime = lp.load_regime()
CLAIMS = {'跌停底座': '组合_跌停低_三连阴', '复活门': '反转族_跌停潮50', '摇篮': '妖股摇篮_成簇',
          'TD9输家': '组合_跌停低_TD9买_输家250', 'TD9超跌': '组合_跌停低_TD9买_超跌20'}
GATED = {'跌停底座', 'TD9输家', 'TD9超跌'}
FEE = 0.003
WIN0, WIN1 = '2019-01-01', '2026-09-18'
IDX = json.loads(open('data/index_sh000001.json').read())
IDXCAL = [k['date'] for k in IDX]
CAL = [d for d in IDXCAL if WIN0 <= d <= WIN1]
streak = {}
s = 0
for k in IDX:
    s = s + 1 if regime.get(k['date']) == '恐慌期' else 0
    streak[k['date']] = s

raw = []
for cname, dn in CLAIMS.items():
    det = lp.REGISTRY[dn]
    for code, d in stocks.items():
        n = d['n']
        c, h = d['c'], d['h']
        for i in range(lp.START, n - 1):
            if lp._epx(d, i) <= 0:
                continue
            try:
                if not det(d, i):
                    continue
            except Exception:
                continue
            hi60 = max(h[max(0, i - 60):i]) if i >= 1 else 0
            raw.append({'dt': d['date'][i], 'code': code, 'i': i, 'claim': cname,
                        'rg': regime.get(d['date'][i], '?'),
                        'pos60': c[i - 1] / hi60 - 1 if hi60 > 0 else 0})
cl = {}
for r in raw:
    if r['claim'] in GATED:
        cl.setdefault(r['dt'], set()).add(r['code'])
kept, seen = [], set()
for r in sorted(raw, key=lambda x: (x['dt'], -x['pos60'])):
    if r['claim'] in GATED and len(cl.get(r['dt'], set())) < 5 and r['rg'] != '恐慌期':
        continue
    key = (r['dt'], r['code'])
    if key not in seen:
        seen.add(key)
        kept.append(r)
CANDS = []
for r in kept:
    d = stocks[r['code']]
    ei = r['i'] + 1
    if ei >= d['n']:
        continue
    entry_d = d['date'][ei]
    if not (WIN0 <= entry_d <= WIN1):
        continue
    CANDS.append({'entry_d': entry_d, 'pos60': r['pos60'], 'claim': r['claim'],
                  'code': r['code'], 'rg': r['rg'], 'ep': lp._epx(d, r['i']),
                  'xi5': min(ei + 5, d['n'] - 1), 'sig_d': r['dt']})
CANDS.sort(key=lambda x: (x['entry_d'], -x['pos60']))
# 每日簇数（kept 口径）与 ldc
day_cl = {}
for r in kept:
    day_cl[r['dt']] = day_cl.get(r['dt'], 0) + 1


def sim(day_ok, w0=WIN0, w1=WIN1):
    cash = 50000.0
    positions, trades, eq = [], [], []
    p = 0
    while p < len(CANDS) and CANDS[p]['entry_d'] < w0:
        p += 1
    for day in [d for d in CAL if w0 <= d <= w1]:
        entered = 0
        while p < len(CANDS) and CANDS[p]['entry_d'] == day:
            cd = CANDS[p]
            p += 1
            if entered >= 3 or cd['rg'] not in ('妖股期', '恐慌期'):
                continue
            if cd['rg'] == '恐慌期' and streak.get(cd['sig_d'], 0) < 2:
                continue
            if not day_ok(cd['sig_d']):
                continue
            if len(positions) < 10 and cash >= 5000:
                d = stocks[cd['code']]
                cash -= 5000
                positions.append({'code': cd['code'], 'ep': cd['ep'], 'xi': cd['xi5'],
                                  'exit_d': d['date'][cd['xi5']], 'entry_d': day})
                entered += 1
        for pos in [x for x in positions if x['exit_d'] != day]:
            d = stocks[pos['code']]
            try:
                j = d['date'].index(day)
            except ValueError:
                continue
            if d['c'][j] / pos['ep'] - 1 <= -0.12:
                cash += 5000 * (d['c'][j] / pos['ep']) * (1 - FEE)
                trades.append(d['c'][j] / pos['ep'] - 1 - FEE)
                pos['stopped'] = True
        positions[:] = [x for x in positions if not x.get('stopped')]
        for pos in [x for x in positions if x['exit_d'] == day]:
            d = stocks[pos['code']]
            cash += 5000 * (d['c'][pos['xi']] / pos['ep']) * (1 - FEE)
            trades.append(d['c'][pos['xi']] / pos['ep'] - 1 - FEE)
        positions[:] = [x for x in positions if x['exit_d'] != day]
        mtm = cash + sum(5000 for _ in positions)
        eq.append(mtm)
    for pos in positions:
        d = stocks[pos['code']]
        cash += 5000 * (d['c'][-1] / pos['ep']) * (1 - FEE)
        trades.append(d['c'][-1] / pos['ep'] - 1 - FEE)
    pk, mdd = 50000.0, 0.0
    for e in eq:
        pk = max(pk, e)
        mdd = min(mdd, (e - pk) / pk)
    wins = sum(1 for x in trades if x > 0)
    return {'final': cash, 'mdd': mdd, 'n': len(trades),
            'wr': 100 * wins / len(trades) if trades else 0,
            'avg': 100 * st.mean(trades) if trades else 0,
            'worst': 100 * min(trades) if trades else 0}


LDC = lp._XLDC
print(f'{"配置":<28}{"笔数":>6}{"胜率":>6}{"均笔":>9}{"期末":>10}{"收益":>8}{"回撤":>8}{"最惨":>8}')
for name, f in [
    ('J5 基准（无日级收紧）', lambda dt: True),
    ('K1 簇≥8', lambda dt: day_cl.get(dt, 0) >= 8),
    ('K2 ldc≥30', lambda dt: LDC.get(dt, 0) >= 30),
    ('K3 ldc≥50', lambda dt: LDC.get(dt, 0) >= 50),
    ('K4 簇≥8 或 ldc≥30', lambda dt: day_cl.get(dt, 0) >= 8 or LDC.get(dt, 0) >= 30),
]:
    r = sim(f)
    print(f'{name:<28}{r["n"]:>6}{r["wr"]:>5.0f}%{r["avg"]:>+8.2f}%{r["final"]:>9,.0f}{100*(r["final"]/50000-1):>+7.1f}%{100*r["mdd"]:>7.1f}%{r["worst"]:>+7.1f}%')

print('\n== 2026 年口径 ==')
for name, f, w0 in [
    ('J5 2026全年至今', (lambda dt: True), '2026-01-01'),
    ('J5 2026 2-9月', (lambda dt: True), '2026-02-01'),
    ('K4 2026全年至今', (lambda dt: day_cl.get(dt, 0) >= 8 or LDC.get(dt, 0) >= 30), '2026-01-01'),
    ('K4 2026 2-9月', (lambda dt: day_cl.get(dt, 0) >= 8 or LDC.get(dt, 0) >= 30), '2026-02-01'),
]:
    r = sim(f, w0)
    print(f'{name}: {r["n"]}笔 胜率{r["wr"]:.0f}% 均{r["avg"]:+.2f}% 期末{r["final"]:,.0f}（{100*(r["final"]/50000-1):+.1f}%）回撤{100*r["mdd"]:.1f}% 最惨{r["worst"]:+.1f}%')