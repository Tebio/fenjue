"""胜率优化矩阵：J5 基础上逐杠杆测试。
W1 T+2出场 / W2 T+3 / W3 T+1
W4 +4%止盈（先到先走，否则T+5/止损）
W5 跳过周一入场（周一效应-4~-8pp实证）
W6 只留摇篮+TD9（池级胜率最高的族，弃底座/复活门）
W7 只在恐慌期入场（弃妖股期）
W8 以上最优组合
全口径：保守时序、浅跌选票、日限3、恐慌第2天、-12%止损、5万/10槽/费0.3%
"""
import sys, json, statistics as st
from datetime import date
sys.path.insert(0, 'engine')
import law_pipeline as lp

stocks = lp.load_universe()
lp.build_xsection(stocks)
regime = lp.load_regime()
CLAIMS = {'跌停底座': '组合_跌停低_三连阴', '复活门': '反转族_跌停潮50', '摇篮': '妖股摇篮_成簇',
          'TD9输家': '组合_跌停低_TD9买_输家250', 'TD9超跌': '组合_跌停低_TD9买_超跌20'}
GATED = {'跌停底座', 'TD9输家', 'TD9超跌'}
CRADLE_TD9 = {'摇篮', 'TD9输家', 'TD9超跌'}
ALL5 = set(CLAIMS)
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
                  'ei': ei, 'sig_d': r['dt']})
CANDS.sort(key=lambda x: (x['entry_d'], -x['pos60']))


def wd(ds):
    y, m, dd = int(ds[:4]), int(ds[5:7]), int(ds[8:10])
    return date(y, m, dd).weekday()  # 0=周一


def sim(families=ALL5, hold=5, target=None, skip_mon=False, yaogu=True, panic=True):
    cash = 50000.0
    positions, trades, eq = [], [], []
    p = 0
    for day in CAL:
        entered = 0
        while p < len(CANDS) and CANDS[p]['entry_d'] == day:
            cd = CANDS[p]
            p += 1
            if cd['claim'] not in families or entered >= 3:
                continue
            rgok = (yaogu and cd['rg'] == '妖股期') or (panic and cd['rg'] == '恐慌期')
            if not rgok:
                continue
            if cd['rg'] == '恐慌期' and streak.get(cd['sig_d'], 0) < 2:
                continue
            if skip_mon and wd(day) == 0:
                continue
            if len(positions) < 10 and cash >= 5000:
                d = stocks[cd['code']]
                xi = min(cd['ei'] + hold, d['n'] - 1)
                cash -= 5000
                positions.append({'code': cd['code'], 'ep': cd['ep'], 'xi': xi,
                                  'exit_d': d['date'][xi], 'entry_d': day})
                entered += 1
        # 止损+止盈（未到期的仓）
        for pos in [x for x in positions if x['exit_d'] != day]:
            d = stocks[pos['code']]
            try:
                j = d['date'].index(day)
            except ValueError:
                continue
            r_now = d['c'][j] / pos['ep'] - 1
            if r_now <= -0.12 or (target and r_now >= target):
                cash += 5000 * (d['c'][j] / pos['ep']) * (1 - FEE)
                trades.append(d['c'][j] / pos['ep'] - 1 - FEE)
                pos['stopped'] = True
        positions[:] = [x for x in positions if not x.get('stopped')]
        for pos in [x for x in positions if x['exit_d'] == day]:
            d = stocks[pos['code']]
            cash += 5000 * (d['c'][pos['xi']] / pos['ep']) * (1 - FEE)
            trades.append(d['c'][pos['xi']] / pos['ep'] - 1 - FEE)
        positions[:] = [x for x in positions if x['exit_d'] != day]
        eq.append(cash + sum(5000 for _ in positions))
    for pos in positions:
        d = stocks[pos['code']]
        cash += 5000 * (d['c'][-1] / pos['ep']) * (1 - FEE)
        trades.append(d['c'][-1] / pos['ep'] - 1 - FEE)
    pk, mdd = 50000.0, 0.0
    for e in eq:
        pk = max(pk, e)
        mdd = min(mdd, (e - pk) / pk)
    wins = sum(1 for x in trades if x > 0)
    gw = sum(x for x in trades if x > 0)
    gl = -sum(x for x in trades if x <= 0)
    return {'final': cash, 'mdd': mdd, 'n': len(trades),
            'wr': 100 * wins / len(trades) if trades else 0,
            'avg': 100 * st.mean(trades) if trades else 0,
            'worst': 100 * min(trades) if trades else 0,
            'pf': gw / gl if gl > 0 else 99}


print(f'{"配置":<26}{"笔数":>6}{"胜率":>6}{"盈亏比":>6}{"均笔":>8}{"期末":>10}{"收益":>8}{"回撤":>8}{"最惨":>8}')
for name, kw in [
    ('J5 基准(T+5)', dict()),
    ('W1 T+2', dict(hold=2)),
    ('W2 T+3', dict(hold=3)),
    ('W3 T+1', dict(hold=1)),
    ('W4 +4%止盈/T+5', dict(target=0.04)),
    ('W5 跳周一', dict(skip_mon=True)),
    ('W6 只摇篮+TD9', dict(families=CRADLE_TD9)),
    ('W7 只恐慌期', dict(yaogu=False)),
    ('W8 W6+T+3+跳周一', dict(families=CRADLE_TD9, hold=3, skip_mon=True)),
    ('W9 W8+只恐慌期', dict(families=CRADLE_TD9, hold=3, skip_mon=True, yaogu=False)),
]:
    r = sim(**kw)
    print(f'{name:<26}{r["n"]:>6}{r["wr"]:>5.0f}%{r["pf"]:>6.2f}{r["avg"]:>+7.2f}%{r["final"]:>9,.0f}{100*(r["final"]/50000-1):>+7.1f}%{100*r["mdd"]:>7.1f}%{r["worst"]:>+7.1f}%')

print('\n== 决赛：头部杠杆组合 ==')
day_cl = {}
for r in kept:
    day_cl[r['dt']] = day_cl.get(r['dt'], 0) + 1
LDC = lp._XLDC
big = lambda dt: day_cl.get(dt, 0) >= 8 or LDC.get(dt, 0) >= 30


def sim2(day_ok, w0=WIN0, **kw):
    cash = 50000.0
    positions, trades, eq = [], [], []
    p = 0
    while p < len(CANDS) and CANDS[p]['entry_d'] < w0:
        p += 1
    for day in [d for d in CAL if w0 <= d]:
        entered = 0
        while p < len(CANDS) and CANDS[p]['entry_d'] == day:
            cd = CANDS[p]
            p += 1
            if entered >= 3 or cd['claim'] not in kw.get('families', ALL5):
                continue
            rgok = (kw.get('yaogu', True) and cd['rg'] == '妖股期') or (kw.get('panic', True) and cd['rg'] == '恐慌期')
            if not rgok or not day_ok(cd['sig_d']):
                continue
            if cd['rg'] == '恐慌期' and streak.get(cd['sig_d'], 0) < 2:
                continue
            if kw.get('skip_mon') and wd(day) == 0:
                continue
            if len(positions) < 10 and cash >= 5000:
                d = stocks[cd['code']]
                xi = min(cd['ei'] + kw.get('hold', 5), d['n'] - 1)
                cash -= 5000
                positions.append({'code': cd['code'], 'ep': cd['ep'], 'xi': xi,
                                  'exit_d': d['date'][xi], 'entry_d': day})
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
        eq.append(cash + sum(5000 for _ in positions))
    for pos in positions:
        d = stocks[pos['code']]
        cash += 5000 * (d['c'][-1] / pos['ep']) * (1 - FEE)
        trades.append(d['c'][-1] / pos['ep'] - 1 - FEE)
    pk, mdd = 50000.0, 0.0
    for e in eq:
        pk = max(pk, e)
        mdd = min(mdd, (e - pk) / pk)
    wins = sum(1 for x in trades if x > 0)
    gw = sum(x for x in trades if x > 0)
    gl = -sum(x for x in trades if x <= 0)
    return {'final': cash, 'mdd': mdd, 'n': len(trades),
            'wr': 100 * wins / len(trades) if trades else 0,
            'avg': 100 * st.mean(trades) if trades else 0,
            'worst': 100 * min(trades) if trades else 0,
            'pf': gw / gl if gl > 0 else 99}


for name, dok, kw in [
    ('X1 跳周一+只恐慌', False, dict(skip_mon=True, yaogu=False)),
    ('X2 跳周一+大簇日', True, dict(skip_mon=True)),
    ('X3 跳周一+只恐慌+大簇日', True, dict(skip_mon=True, yaogu=False)),
]:
    f = big if dok else (lambda dt: True)
    r = sim2(f, **kw)
    print(f'{name:<26}{r["n"]:>6}{r["wr"]:>5.0f}%{r["pf"]:>6.2f}{r["avg"]:>+7.2f}%{r["final"]:>9,.0f}{100*(r["final"]/50000-1):>+7.1f}%{100*r["mdd"]:>7.1f}%{r["worst"]:>+7.1f}%')
    r26 = sim2(f, w0='2026-01-01', **kw)
    print(f'   2026: {r26["n"]}笔 胜率{r26["wr"]:.0f}% 均{r26["avg"]:+.2f}% 期末{r26["final"]:,.0f}（{100*(r26["final"]/50000-1):+.1f}%）回撤{100*r26["mdd"]:.1f}%')
