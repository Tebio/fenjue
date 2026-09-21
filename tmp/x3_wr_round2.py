"""X3 胜率二轮优化矩阵（全部在 X3 底座上加一个杠杆）：
Y1 保本止损：持有≥2天且曾浮盈≥+2%，止损线上移到成本价（救回擦边亏损单）
Y2 跳空过滤：入场日开盘相对信号日收盘低开≤-1.5% 则放弃（不接延续下杀）
Y3 新低过滤：信号日创20日新低=还在自由落体，放弃
Y4 企稳确认：信号日近3日累计跌幅 >-5% 才接
Y5 Y1+Y2 组合
Y6 Y1+Y3 组合
Y7 Y1+Y2+Y3 全上
底座=X3：只恐慌期+恐慌第2天+大簇日+跳周一+浅跌+日限3+T+5/-12%止损
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
        c, h, lo = d['c'], d['h'], d['l']
        for i in range(lp.START, n - 1):
            if lp._epx(d, i) <= 0:
                continue
            try:
                if not det(d, i):
                    continue
            except Exception:
                continue
            hi60 = max(h[max(0, i - 60):i]) if i >= 1 else 0
            gap = lp._epx(d, i) / c[i] - 1   # 入场开盘 vs 信号收盘
            new20 = lo[i] <= min(lo[max(0, i - 20):i + 1])  # 信号日创20日新低
            r3 = c[i] / c[i - 3] - 1 if i >= 3 else 0       # 近3日涨跌
            raw.append({'dt': d['date'][i], 'code': code, 'i': i, 'claim': cname,
                        'rg': regime.get(d['date'][i], '?'),
                        'pos60': c[i - 1] / hi60 - 1 if hi60 > 0 else 0,
                        'gap': gap, 'new20': new20, 'r3': r3})
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
    if not (WIN0 <= entry_d <= WIN1):
        continue
    CANDS.append({'entry_d': entry_d, 'pos60': r['pos60'], 'claim': r['claim'],
                  'code': r['code'], 'rg': r['rg'], 'ep': lp._epx(d, r['i']),
                  'ei': ei, 'sig_d': r['dt'], 'gap': r['gap'],
                  'new20': r['new20'], 'r3': r['r3']})
CANDS.sort(key=lambda x: (x['entry_d'], -x['pos60']))


def wd(ds):
    return date(int(ds[:4]), int(ds[5:7]), int(ds[8:10])).weekday()


def sim(breakeven=False, gap_f=False, new20_f=False, stab_f=False):
    cash = 50000.0
    positions, trades, eq = [], [], []
    p = 0
    for day in CAL:
        entered = 0
        while p < len(CANDS) and CANDS[p]['entry_d'] == day:
            cd = CANDS[p]
            p += 1
            if entered >= 3 or cd['rg'] != '恐慌期':
                continue
            if streak.get(cd['sig_d'], 0) < 2 or not big(cd['sig_d']) or wd(day) == 0:
                continue
            if gap_f and cd['gap'] <= -0.015:
                continue
            if new20_f and cd['new20']:
                continue
            if stab_f and cd['r3'] <= -0.05:
                continue
            if len(positions) < 10 and cash >= 5000:
                d = stocks[cd['code']]
                xi = min(cd['ei'] + 5, d['n'] - 1)
                cash -= 5000
                positions.append({'code': cd['code'], 'ep': cd['ep'], 'xi': xi,
                                  'exit_d': d['date'][xi], 'entry_d': day, 'be': False})
                entered += 1
        for pos in [x for x in positions if x['exit_d'] != day]:
            d = stocks[pos['code']]
            try:
                j = d['date'].index(day)
            except ValueError:
                continue
            r_now = d['c'][j] / pos['ep'] - 1
            # 保本线激活：曾浮盈≥+2% 后，跌破成本即走
            if breakeven and r_now >= 0.02:
                pos['be'] = True
            stop_line = -0.12 if not (breakeven and pos['be']) else -0.003
            if r_now <= stop_line:
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


print(f'{"配置":<22}{"笔数":>6}{"胜率":>6}{"盈亏比":>6}{"均笔":>8}{"期末":>10}{"收益":>8}{"回撤":>8}{"最惨":>8}')
for name, kw in [
    ('X3 底座', dict()),
    ('Y1 保本止损', dict(breakeven=True)),
    ('Y2 跳空过滤', dict(gap_f=True)),
    ('Y3 新低过滤', dict(new20_f=True)),
    ('Y4 企稳确认', dict(stab_f=True)),
    ('Y5 Y1+Y2', dict(breakeven=True, gap_f=True)),
    ('Y6 Y1+Y3', dict(breakeven=True, new20_f=True)),
    ('Y7 全上', dict(breakeven=True, gap_f=True, new20_f=True)),
]:
    r = sim(**kw)
    print(f'{name:<22}{r["n"]:>6}{r["wr"]:>5.0f}%{r["pf"]:>6.2f}{r["avg"]:>+7.2f}%{r["final"]:>9,.0f}{100*(r["final"]/50000-1):>+7.1f}%{100*r["mdd"]:>7.1f}%{r["worst"]:>+7.1f}%')