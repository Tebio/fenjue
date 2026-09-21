"""第四轮：胜者组合 —— 浅跌选票 + 各杠杆交叉。
H1 G6原样（恐慌族/浅跌/T+5/日限3）
H2 +T1分档出场
H3 +regime启停（妖股/恐慌才入场）
H4 +日限5
H5 +缺口低族并入（全6主张浅跌）
全部报 2026 2-9月切片。
"""
import sys, json, statistics as st
sys.path.insert(0, 'engine')
import law_pipeline as lp

stocks = lp.load_universe()
lp.build_xsection(stocks)
regime = lp.load_regime()
CLAIMS = {
    '跌停底座': '组合_跌停低_三连阴', '复活门': '反转族_跌停潮50', '摇篮': '妖股摇篮_成簇',
    '缺口低': '组合_缺口低开_低位阳线_避周一',
    'TD9输家': '组合_跌停低_TD9买_输家250', 'TD9超跌': '组合_跌停低_TD9买_超跌20',
}
PANIC_ONLY = {'跌停底座', '复活门', '摇篮', 'TD9输家', 'TD9超跌'}
ALL = set(CLAIMS)
GATED = {'跌停底座', 'TD9输家', 'TD9超跌'}
FEE = 0.003
WIN0, WIN1 = '2018-01-01', '2026-09-18'
IDXCAL = [k['date'] for k in json.loads(open('data/index_sh000001.json').read())]
CAL = [d for d in IDXCAL if WIN0 <= d <= WIN1]

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
for r in sorted(raw, key=lambda x: (x['dt'], x['pos60'])):
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
    ep = lp._epx(d, r['i'])
    r1 = d['c'][ei] / ep - 1
    tgt = 20 if r1 >= 0.03 else 10
    CANDS.append({'entry_d': entry_d, 'pos60': r['pos60'], 'claim': r['claim'],
                  'code': r['code'], 'rg': r['rg'], 'ep': ep,
                  'xi5': min(ei + 5, d['n'] - 1), 'xit': min(ei + tgt, d['n'] - 1)})


def sim(families, day_cap, exits, regime_gate, w0=WIN0, w1=WIN1):
    cands = sorted((c for c in CANDS if w0 <= c['entry_d'] <= w1),
                   key=lambda x: (x['entry_d'], -x['pos60']))  # 浅跌优先
    cash = 50000.0
    positions, trades, eq = [], [], []
    p = 0
    cal = [d for d in CAL if w0 <= d <= w1]
    for day in cal:
        for pos in [x for x in positions if x['exit_d'] == day]:
            d = stocks[pos['code']]
            cash += 5000 * (d['c'][pos['xi']] / pos['ep']) * (1 - FEE)
            trades.append({'ret': d['c'][pos['xi']] / pos['ep'] - 1 - FEE, 'year': pos['entry_d'][:4]})
        positions = [x for x in positions if x['exit_d'] != day]
        entered = 0
        while p < len(cands) and cands[p]['entry_d'] == day:
            cd = cands[p]
            p += 1
            if cd['claim'] not in families or entered >= day_cap:
                continue
            if regime_gate and cd['rg'] not in ('妖股期', '恐慌期'):
                continue
            if len(positions) < 10 and cash >= 5000:
                d = stocks[cd['code']]
                xi = cd['xi5'] if exits == 'T5' else cd['xit']
                cash -= 5000
                positions.append({'code': cd['code'], 'ep': cd['ep'], 'xi': xi,
                                  'exit_d': d['date'][xi], 'entry_d': day})
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
    peak, mdd = 50000.0, 0.0
    for e in eq:
        peak = max(peak, e)
        mdd = min(mdd, (e - peak) / peak)
    rets = [t['ret'] for t in trades]
    wins = sum(1 for x in rets if x > 0)
    by_year = {}
    for t in trades:
        by_year.setdefault(t['year'], []).append(t['ret'])
    return {'final': cash, 'mdd': mdd, 'n': len(trades),
            'wr': 100 * wins / len(rets) if rets else 0,
            'avg': 100 * st.mean(rets) if rets else 0,
            'worst': 100 * min(rets) if rets else 0,
            'ypnl': {y: sum(v) * 5000 for y, v in sorted(by_year.items())}}


print(f'{"配置":<26}{"笔数":>6}{"胜率":>6}{"均笔":>9}{"期末":>10}{"收益":>8}{"回撤":>8}{"最惨":>8}')
best = {}
for name, kw in [
    ('H1 G6原样', dict(families=PANIC_ONLY, day_cap=3, exits='T5', regime_gate=False)),
    ('H2 +T1分档', dict(families=PANIC_ONLY, day_cap=3, exits='T1', regime_gate=False)),
    ('H3 +regime启停', dict(families=PANIC_ONLY, day_cap=3, exits='T5', regime_gate=True)),
    ('H4 +日限5', dict(families=PANIC_ONLY, day_cap=5, exits='T5', regime_gate=False)),
    ('H5 +缺口低并入', dict(families=ALL, day_cap=3, exits='T5', regime_gate=False)),
]:
    r = sim(**kw)
    best[name] = (kw, r)
    print(f'{name:<26}{r["n"]:>6}{r["wr"]:>5.0f}%{r["avg"]:>+8.2f}%{r["final"]:>9,.0f}{100*(r["final"]/50000-1):>+7.1f}%{100*r["mdd"]:>7.1f}%{r["worst"]:>+7.1f}%')
    print(f'   逐年: {dict((y, f"{v:+,.0f}") for y, v in r["ypnl"].items())}')

print('\n== 胜者们的 2026 2-9月切片 ==')
for name, (kw, _) in best.items():
    r = sim(w0='2026-02-01', w1='2026-09-18', **kw)
    print(f'{name}: {r["n"]}笔 胜率{r["wr"]:.0f}% 均{r["avg"]:+.2f}% 期末{r["final"]:,.0f}（{100*(r["final"]/50000-1):+.1f}%）回撤{100*r["mdd"]:.1f}%')