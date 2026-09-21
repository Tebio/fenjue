"""第三轮：G4 指数对照（修复属性名）+ G6 选票方向反转（跌最浅优先，抗刀）。
G6 假设：容量约束下每次都接到"跌最深"的飞刀；若选"跌最浅"（更接近企稳）是否反败为胜。
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
GATED = {'跌停底座', 'TD9输家', 'TD9超跌'}
FEE = 0.003
WIN0, WIN1 = '2018-01-01', '2026-09-18'
IDX = json.loads(open('data/index_sh000001.json').read())
IDXCAL = [k['date'] for k in IDX]
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
    CANDS.append({'entry_d': entry_d, 'pos60': r['pos60'], 'claim': r['claim'],
                  'code': r['code'], 'rg': r['rg'], 'ep': ep,
                  'xi5': min(ei + 5, d['n'] - 1)})


def sim(families, day_cap, shallow=False):
    cands = sorted(CANDS, key=lambda x: (x['entry_d'], -x['pos60'] if shallow else x['pos60']))
    cash = 50000.0
    positions, trades, eq = [], [], []
    p = 0
    for day in CAL:
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


print('== G6 选票方向对照（恐慌族，T+5，日限3）==')
for nm, sh in (('跌最深优先（现口径）', False), ('跌最浅优先（抗刀）', True)):
    r = sim(PANIC_ONLY, 3, shallow=sh)
    print(f'{nm}: {r["n"]}笔 胜率{r["wr"]:.0f}% 均{r["avg"]:+.2f}% 期末{r["final"]:,.0f}（{100*(r["final"]/50000-1):+.1f}%）回撤{100*r["mdd"]:.1f}%')
    print(f'   逐年: {dict((y, f"{v:+,.0f}") for y, v in r["ypnl"].items())}')

print('\n== G4 复活门日（ldc≥50）次日开盘买指数 T+20，全仓滚动 ==')
res4 = []
last_exit = ''
for i in range(1, len(IDX) - 1):
    dt = IDX[i]['date']
    if not (WIN0 <= dt <= WIN1):
        continue
    if lp._XLDC.get(dt, 0) >= 50 and dt > last_exit:
        ei = i + 1
        if ei >= len(IDX):
            break
        xi = min(ei + 20, len(IDX) - 1)
        ret = IDX[xi]['close'] / IDX[ei]['open'] - 1 - FEE
        res4.append((dt, ret))
        last_exit = IDX[xi]['date']
eq4 = 50000.0
for dt, r in res4:
    eq4 *= (1 + r)
    print(f'  {dt} → {100*r:+.2f}%')
wins = sum(1 for _, r in res4 if r > 0)
if res4:
    print(f'全仓滚动：{eq4:,.0f} 元（{100*(eq4/50000-1):+.1f}%）胜率 {100*wins/len(res4):.0f}%（{len(res4)} 次）')

# G4b：妖股期每 20 日买指数拿着不动（buy&hold 基准）
r0 = IDX[[k['date'] for k in IDX].index(WIN0 if WIN0 in IDXCAL else CAL[0])]
rN = IDX[-1]
bh = IDX[[k['date'] for k in IDX].index(CAL[0])]['close']
print(f'\n基准：指数区间 {100*(rN["close"]/bh-1):+.1f}%（{CAL[0]}→{CAL[-1]}）')