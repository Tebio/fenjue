"""X3 2025-2026/9 逐笔全账本：每次出手买的什么、赚亏多少、空仓多久。"""
import sys, json, statistics as st
from datetime import date
sys.path.insert(0, 'engine')
import law_pipeline as lp

stocks = lp.load_universe()
lp.build_xsection(stocks)
regime = lp.load_regime()
names = {str(s['code']).zfill(6): s.get('name', '')
         for s in json.loads(open('data/main_board_codes.json').read()).get('stocks', [])}
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
day_cl = {}
for r in kept:
    day_cl[r['dt']] = day_cl.get(r['dt'], 0) + 1
LDC = lp._XLDC
big = lambda dt: day_cl.get(dt, 0) >= 8 or LDC.get(dt, 0) >= 30

CANDS = []
for r in kept:
    d = stocks[r['code']]
    ei = r['i'] + 1
    if ei >= d['n']:
        continue
    entry_d = d['date'][ei]
    if not ('2025-01-01' <= entry_d <= WIN1):
        continue
    CANDS.append({'entry_d': entry_d, 'pos60': r['pos60'], 'claim': r['claim'],
                  'code': r['code'], 'rg': r['rg'], 'ep': lp._epx(d, r['i']),
                  'ei': ei, 'sig_d': r['dt']})
CANDS.sort(key=lambda x: (x['entry_d'], -x['pos60']))


def wd(ds):
    return date(int(ds[:4]), int(ds[5:7]), int(ds[8:10])).weekday()

cash = 50000.0
positions, trades, eq = [], [], []
p = 0
for day in [d for d in CAL if '2025-01-01' <= d]:
    entered = 0
    while p < len(CANDS) and CANDS[p]['entry_d'] == day:
        cd = CANDS[p]
        p += 1
        if entered >= 3 or cd['rg'] != '恐慌期':
            continue
        if streak.get(cd['sig_d'], 0) < 2 or not big(cd['sig_d']) or wd(day) == 0:
            continue
        if len(positions) < 10 and cash >= 5000:
            d = stocks[cd['code']]
            xi = min(cd['ei'] + 5, d['n'] - 1)
            cash -= 5000
            positions.append({'code': cd['code'], 'ep': cd['ep'], 'xi': xi, 'claim': cd['claim'],
                              'exit_d': d['date'][xi], 'entry_d': day, 'sig_d': cd['sig_d']})
            entered += 1
    for pos in [x for x in positions if x['exit_d'] != day]:
        d = stocks[pos['code']]
        try:
            j = d['date'].index(day)
        except ValueError:
            continue
        if d['c'][j] / pos['ep'] - 1 <= -0.12:
            cash += 5000 * (d['c'][j] / pos['ep']) * (1 - FEE)
            trades.append({**pos, 'exit_d': day, 'xp': d['c'][j], 'how': '止损'})
            pos['stopped'] = True
    positions[:] = [x for x in positions if not x.get('stopped')]
    for pos in [x for x in positions if x['exit_d'] == day]:
        d = stocks[pos['code']]
        cash += 5000 * (d['c'][pos['xi']] / pos['ep']) * (1 - FEE)
        trades.append({**pos, 'xp': d['c'][pos['xi']], 'how': 'T+5'})
        pos['done'] = True
    positions[:] = [x for x in positions if not x.get('done')]
    eq.append((day, cash + sum(5000 for _ in positions)))
for pos in positions:
    d = stocks[pos['code']]
    cash += 5000 * (d['c'][-1] / pos['ep']) * (1 - FEE)
    trades.append({**pos, 'exit_d': d['date'][-1], 'xp': d['c'][-1], 'how': '在途'})

trades.sort(key=lambda t: t['entry_d'])
print(f'共出手 {len(trades)} 笔（2025-01-01 → 2026-09-18）\n')
last_exit = None
for t in trades:
    r = t['xp'] / t['ep'] - 1 - FEE
    nm = names.get(t['code'], '')[:6]
    gap = f'（距上次出手 {t["entry_d"]}）' if last_exit is None else ''
    print(f'{t["sig_d"]}信号 {t["entry_d"]}买 {t["exit_d"]}卖 | {t["code"]} {nm:<7} {t["claim"]:<6}'
          f'{t["ep"]:>7.2f}→{t["xp"]:>7.2f} | {100*r:>+6.1f}% {r*5000:>+6.0f}元 [{t["how"]}]')
    last_exit = t['exit_d']
rets = [t['xp'] / t['ep'] - 1 - FEE for t in trades]
wins = sum(1 for x in rets if x > 0)
total = sum(rets) * 5000
print(f'\n胜 {wins} / 负 {len(rets)-wins} = 胜率 {100*wins/len(rets):.0f}%')
print(f'总盈亏 {total:+,.0f} 元（5万 → {100*(50000+total)/50000-100:+.1f}%）')
# 空仓统计
days_in = set()
for t in trades:
    i0 = IDXCAL.index(t['entry_d'])
    i1 = IDXCAL.index(t['exit_d']) if t['exit_d'] in IDXCAL else len(IDXCAL) - 1
    days_in.update(IDXCAL[i0:i1])
span = [d for d in IDXCAL if '2025-01-01' <= d <= '2026-09-18']
print(f'区间 {len(span)} 个交易日，有仓位 {len(days_in)} 天（{100*len(days_in)/len(span):.0f}%），其余时间空仓')