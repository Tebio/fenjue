"""J5 保守时序（修复版）：止损只移除它实际触发的仓，自然到期的走正常出场。
先入场后出场 = 当日收盘才释放的槽/现金当日不可用（无微观前视）。"""
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


def sim(w0=WIN0, w1=WIN1):
    cash = 50000.0
    positions, trades, eq = [], [], []
    by_year = {}
    p = 0
    while p < len(CANDS) and CANDS[p]['entry_d'] < w0:
        p += 1  # 切片起点前移指针（防停滞）
    for day in [d for d in CAL if w0 <= d <= w1]:
        # 1) 开盘入场（只用昨日已空的槽/现金）
        entered = 0
        while p < len(CANDS) and CANDS[p]['entry_d'] == day:
            cd = CANDS[p]
            p += 1
            if entered >= 3 or cd['rg'] not in ('妖股期', '恐慌期'):
                continue
            if cd['rg'] == '恐慌期' and streak.get(cd['sig_d'], 0) < 2:
                continue
            if len(positions) < 10 and cash >= 5000:
                d = stocks[cd['code']]
                cash -= 5000
                positions.append({'code': cd['code'], 'ep': cd['ep'], 'xi': cd['xi5'],
                                  'exit_d': d['date'][cd['xi5']], 'entry_d': day,
                                  'claim': cd['claim']})
                entered += 1
        # 2) 止损（只碰未到期的仓；到期仓走正常出场）
        for pos in [x for x in positions if x['exit_d'] != day]:
            d = stocks[pos['code']]
            try:
                j = d['date'].index(day)
            except ValueError:
                continue
            if d['c'][j] / pos['ep'] - 1 <= -0.12:
                cash += 5000 * (d['c'][j] / pos['ep']) * (1 - FEE)
                trades.append({'ret': d['c'][j] / pos['ep'] - 1 - FEE, 'year': pos['entry_d'][:4]})
                pos['stopped'] = True
        positions[:] = [x for x in positions if not x.get('stopped')]
        # 3) 正常 T+5 出场（收盘价）
        for pos in [x for x in positions if x['exit_d'] == day]:
            d = stocks[pos['code']]
            cash += 5000 * (d['c'][pos['xi']] / pos['ep']) * (1 - FEE)
            trades.append({'ret': d['c'][pos['xi']] / pos['ep'] - 1 - FEE, 'year': pos['entry_d'][:4]})
        positions[:] = [x for x in positions if x['exit_d'] != day]
        mtm = cash
        for pos in positions:
            d = stocks[pos['code']]
            try:
                j = d['date'].index(day)
                mtm += 5000 * (d['c'][j] / pos['ep'])
            except ValueError:
                mtm += 5000
        eq.append(mtm)
    for pos in positions:
        d = stocks[pos['code']]
        cash += 5000 * (d['c'][-1] / pos['ep']) * (1 - FEE)
        trades.append({'ret': d['c'][-1] / pos['ep'] - 1 - FEE, 'year': pos['entry_d'][:4]})
    pk, mdd = 50000.0, 0.0
    for e in eq:
        pk = max(pk, e)
        mdd = min(mdd, (e - pk) / pk)
    rets = [t['ret'] for t in trades]
    wins = sum(1 for x in rets if x > 0)
    gw = sum(x for x in rets if x > 0)
    gl = -sum(x for x in rets if x <= 0)
    for t in trades:
        by_year.setdefault(t['year'], []).append(t['ret'])
    return {'final': cash, 'mdd': mdd, 'n': len(trades),
            'wr': 100 * wins / len(rets) if rets else 0,
            'avg': 100 * st.mean(rets) if rets else 0,
            'worst': 100 * min(rets) if rets else 0,
            'pf': gw / gl if gl > 0 else 99,
            'ypnl': {y: sum(v) * 5000 for y, v in sorted(by_year.items())}}


r = sim()
print(f'J5 保守时序（修复版）全史: {r["n"]}笔 胜率{r["wr"]:.0f}% 盈亏比{r["pf"]:.2f} 均{r["avg"]:+.2f}%')
print(f'期末 {r["final"]:,.0f}（{100*(r["final"]/50000-1):+.1f}%）回撤 {100*r["mdd"]:.1f}% 最惨 {r["worst"]:+.1f}%')
print(f'逐年: {dict((y, f"{v:+,.0f}") for y, v in r["ypnl"].items())}')
r2 = sim('2026-02-01', '2026-09-18')
print(f'\n2-9月切片: {r2["n"]}笔 胜率{r2["wr"]:.0f}% 期末 {r2["final"]:,.0f}（{100*(r2["final"]/50000-1):+.1f}%）回撤 {100*r2["mdd"]:.1f}%')