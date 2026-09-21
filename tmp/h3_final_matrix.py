"""最终选型矩阵：三目标（胜率/回撤/收益）联合优化。
J1 弃复活门（只留底座/摇篮/TD9，池均+6~9%的高质量族）
J2 J1+恐慌第2天
J3 J1+硬止损-12%
J4 J1+第2天+止损
J5 H3+第2天+止损（复活门保留）
J6 J1+只妖股期（恐慌日完全不接）
J7 J1+日限2（更精选）
J8 J4+日限2
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
NO_DOOR = {'跌停底座', '摇篮', 'TD9输家', 'TD9超跌'}
ALL5 = set(CLAIMS)
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


def sim(families, day_cap=3, day2=False, stop=None, yaogu_only=False):
    cash = 50000.0
    positions, trades, eq = [], [], []
    p = 0
    for day in CAL:
        for pos in [x for x in positions if x['exit_d'] == day]:
            d = stocks[pos['code']]
            cash += 5000 * (d['c'][pos['xi']] / pos['ep']) * (1 - FEE)
            trades.append({'ret': d['c'][pos['xi']] / pos['ep'] - 1 - FEE, 'year': pos['entry_d'][:4]})
        positions = [x for x in positions if x['exit_d'] != day]
        if stop:
            for pos in [x for x in positions]:
                d = stocks[pos['code']]
                try:
                    j = d['date'].index(day)
                except ValueError:
                    continue
                if d['c'][j] / pos['ep'] - 1 <= -stop:
                    cash += 5000 * (d['c'][j] / pos['ep']) * (1 - FEE)
                    trades.append({'ret': d['c'][j] / pos['ep'] - 1 - FEE, 'year': pos['entry_d'][:4]})
                    pos['exit_d'] = day
            positions = [x for x in positions if x['exit_d'] != day]
        entered = 0
        while p < len(CANDS) and CANDS[p]['entry_d'] == day:
            cd = CANDS[p]
            p += 1
            if cd['claim'] not in families or entered >= day_cap:
                continue
            if cd['rg'] not in ('妖股期', '恐慌期'):
                continue
            if yaogu_only and cd['rg'] != '妖股期':
                continue
            if day2 and cd['rg'] == '恐慌期' and streak.get(cd['sig_d'], 0) < 2:
                continue
            if len(positions) < 10 and cash >= 5000:
                d = stocks[cd['code']]
                cash -= 5000
                positions.append({'code': cd['code'], 'ep': cd['ep'], 'xi': cd['xi5'],
                                  'exit_d': d['date'][cd['xi5']], 'entry_d': day})
                entered += 1
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
    by_year = {}
    for t in trades:
        by_year.setdefault(t['year'], []).append(t['ret'])
    return {'final': cash, 'mdd': mdd, 'n': len(trades),
            'wr': 100 * wins / len(rets) if rets else 0,
            'avg': 100 * st.mean(rets) if rets else 0,
            'worst': 100 * min(rets) if rets else 0,
            'pf': gw / gl if gl > 0 else 99,
            'ypnl': {y: sum(v) * 5000 for y, v in sorted(by_year.items())}}


print(f'{"配置":<24}{"笔数":>6}{"胜率":>6}{"盈亏比":>6}{"均笔":>8}{"期末":>10}{"收益":>8}{"回撤":>8}{"最惨":>8}')
for name, kw in [
    ('J1 弃复活门', dict(families=NO_DOOR)),
    ('J2 J1+恐慌第2天', dict(families=NO_DOOR, day2=True)),
    ('J3 J1+止损12%', dict(families=NO_DOOR, stop=0.12)),
    ('J4 J1+第2天+止损', dict(families=NO_DOOR, day2=True, stop=0.12)),
    ('J5 H3+第2天+止损', dict(families=ALL5, day2=True, stop=0.12)),
    ('J6 J1只妖股期', dict(families=NO_DOOR, yaogu_only=True)),
    ('J7 J1+日限2', dict(families=NO_DOOR, day_cap=2)),
    ('J8 J4+日限2', dict(families=NO_DOOR, day2=True, stop=0.12, day_cap=2)),
]:
    r = sim(**kw)
    print(f'{name:<24}{r["n"]:>6}{r["wr"]:>5.0f}%{r["pf"]:>6.2f}{r["avg"]:>+7.2f}%{r["final"]:>9,.0f}{100*(r["final"]/50000-1):>+7.1f}%{100*r["mdd"]:>7.1f}%{r["worst"]:>+7.1f}%')
    print(f'   逐年: {dict((y, f"{v:+,.0f}") for y, v in r["ypnl"].items())}')