"""第二轮：弹药只打恐慌 + 指数对照。
G1 恐慌族only（底座/TD9/摇篮/复活门，弃缺口低）T1分档 日限3
G2 G1+短持T+5
G3 G1+平时≤3仓/恐慌日放开10仓（弹药预留）
G4 复活门信号日买指数（T+20），5万一次性——无槽位问题的宽度收割对照
G5 妖股期日才允许缺口低+恐慌族全开，T+5，日限3
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
    r1 = d['c'][ei] / ep - 1
    tgt = 20 if r1 >= 0.03 else 10
    CANDS.append({'entry_d': entry_d, 'pos60': r['pos60'], 'claim': r['claim'],
                  'code': r['code'], 'rg': r['rg'], 'ep': ep,
                  'xi5': min(ei + 5, d['n'] - 1), 'xit': min(ei + tgt, d['n'] - 1)})
CANDS.sort(key=lambda x: (x['entry_d'], x['pos60']))


def sim(families, day_cap=99, exits='T1', panic_slots=None, yaogu_only=False):
    cash = 50000.0
    positions, trades = [], []
    eq = []
    p = 0
    for day in CAL:
        for pos in [x for x in positions if x['exit_d'] == day]:
            d = stocks[pos['code']]
            cash += 5000 * (d['c'][pos['xi']] / pos['ep']) * (1 - FEE)
            trades.append({'ret': d['c'][pos['xi']] / pos['ep'] - 1 - FEE,
                           'year': pos['entry_d'][:4]})
        positions = [x for x in positions if x['exit_d'] != day]
        entered = 0
        while p < len(CANDS) and CANDS[p]['entry_d'] == day:
            cd = CANDS[p]
            p += 1
            if cd['claim'] not in families:
                continue
            if yaogu_only and cd['rg'] not in ('妖股期', '恐慌期'):
                continue
            if entered >= day_cap:
                continue
            slot_cap = 10 if (panic_slots and cd['rg'] == '恐慌期') else (panic_slots or 10)
            if len(positions) < slot_cap and cash >= 5000:
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


print(f'{"配置":<28}{"笔数":>6}{"胜率":>6}{"均笔":>9}{"期末":>10}{"收益":>8}{"回撤":>8}{"最惨":>8}')
for name, kw in [
    ('G1 恐慌族only T1分档 日限3', dict(families=PANIC_ONLY, day_cap=3)),
    ('G2 G1+T+5', dict(families=PANIC_ONLY, day_cap=3, exits='T5')),
    ('G3 G1+平时3仓恐慌日10仓', dict(families=PANIC_ONLY, day_cap=3, panic_slots=3)),
    ('G5 妖股期全开 T+5 日限3', dict(families=set(CLAIMS), day_cap=3, exits='T5', yaogu_only=True)),
]:
    r = sim(**kw)
    print(f'{name:<28}{r["n"]:>6}{r["wr"]:>5.0f}%{r["avg"]:>+8.2f}%{r["final"]:>9,.0f}{100*(r["final"]/50000-1):>+7.1f}%{100*r["mdd"]:>7.1f}%{r["worst"]:>+7.1f}%')
    print(f'   逐年: {dict((y, f"{v:+,.0f}") for y, v in r["ypnl"].items())}')

# G4 复活门信号日（ldc≥50）次日买指数，T+20出场，每次全仓5万（单仓滚动）
ldc_map = {}
for r in raw:
    ldc_map.setdefault(r['dt'], 0)
# 直接复用 law_pipeline 的 xsection ldc
days50 = []
for i in range(1, len(IDX) - 1):
    dt = IDX[i]['date']
    if not (WIN0 <= dt <= WIN1):
        continue
    if lp._LDC.get(dt, 0) >= 50:
        days50.append(dt)
print(f'\nG4 复活门日（ldc≥50）次日开盘买指数 T+20：共 {len(days50)} 次')
eq4 = 50000.0
last_exit = ''
res4 = []
for dt in days50:
    i = IDXCAL.index(dt)
    if dt <= last_exit:
        continue
    ei = i + 1
    if ei >= len(IDX):
        break
    xi = min(ei + 20, len(IDX) - 1)
    ret = IDX[xi]['close'] / IDX[ei]['open'] - 1 - FEE
    res4.append((dt, ret))
    eq4 *= (1 + ret)
    last_exit = IDX[xi]['date']
wins = sum(1 for _, r in res4 if r > 0)
for dt, r in res4:
    print(f'  {dt} → {100*r:+.2f}%')
print(f'全仓滚动：{eq4:,.0f} 元（{100*(eq4/50000-1):+.1f}%）胜率 {100*wins/len(res4):.0f}%')