import sys, json
sys.path.insert(0, 'engine')
import law_pipeline as lp
stocks = lp.load_universe()
lp.build_xsection(stocks)
regime = lp.load_regime()
CLAIMS = {'跌停底座': '组合_跌停低_三连阴', '复活门': '反转族_跌停潮50', '摇篮': '妖股摇篮_成簇',
          'TD9输家': '组合_跌停低_TD9买_输家250', 'TD9超跌': '组合_跌停低_TD9买_超跌20'}
GATED = {'跌停底座', 'TD9输家', 'TD9超跌'}
FEE = 0.003
WIN0, WIN1 = '2018-01-01', '2026-09-18'
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
print(f'CANDS 总数 {len(CANDS)}，前 3 个: {[(c["entry_d"], c["code"]) for c in CANDS[:3]]}')

cash = 50000.0
positions, trades = [], []
p = 0
for day in CAL:
    # 保守序：先入后出
    entered = 0
    skipped_rg, skipped_strk, skipped_slot = 0, 0, 0
    while p < len(CANDS) and CANDS[p]['entry_d'] == day:
        cd = CANDS[p]
        p += 1
        if entered >= 3 or cd['rg'] not in ('妖股期', '恐慌期'):
            skipped_rg += 1
            continue
        if cd['rg'] == '恐慌期' and streak.get(cd['sig_d'], 0) < 2:
            skipped_strk += 1
            continue
        if len(positions) < 10 and cash >= 5000:
            d = stocks[cd['code']]
            cash -= 5000
            positions.append({'code': cd['code'], 'ep': cd['ep'], 'xi': cd['xi5'],
                              'exit_d': d['date'][cd['xi5']], 'entry_d': day})
            entered += 1
        else:
            skipped_slot += 1
    # stops
    stopped = 0
    for pos in [x for x in positions]:
        d = stocks[pos['code']]
        try:
            j = d['date'].index(day)
        except ValueError:
            continue
        if d['c'][j] / pos['ep'] - 1 <= -0.12:
            cash += 5000 * (d['c'][j] / pos['ep']) * (1 - FEE)
            trades.append(d['c'][j] / pos['ep'] - 1 - FEE)
            pos['exit_d'] = day
            stopped += 1
    positions[:] = [x for x in positions if x['exit_d'] != day]
    exited = 0
    for pos in [x for x in positions if x['exit_d'] == day]:
        d = stocks[pos['code']]
        cash += 5000 * (d['c'][pos['xi']] / pos['ep']) * (1 - FEE)
        trades.append(d['c'][pos['xi']] / pos['ep'] - 1 - FEE)
        exited += 1
    positions[:] = [x for x in positions if x['exit_d'] != day]
    if (entered or stopped or exited) and day < '2020-07-01':
        print(f'{day}: 入{entered} 停{stopped} 出{exited} | 现金{cash:,.0f} 持仓{len(positions)} 交易{len(trades)}')

# 期末强平
for pos in positions:
    d = stocks[pos['code']]
    cash += 5000 * (d['c'][-1] / pos['ep']) * (1 - FEE)
    trades.append(d['c'][-1] / pos['ep'] - 1 - FEE)
import statistics as st
wins = sum(1 for x in trades if x > 0)
print(f'\n保守序内联版全程: {len(trades)}笔 胜率{100*wins/len(trades):.0f}% 均{100*st.mean(trades):+.2f}% 期末{cash:,.0f}（{100*(cash/50000-1):+.1f}%）最惨{100*min(trades):+.1f}%')