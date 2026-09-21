"""T+1每日打法矩阵：全史验证「每天操作+高胜率」是否存在。
口径：信号日i → i+1开盘买 → i+2收盘卖（合法持有一天）。10槽×5000、费0.3%、
浅跌选票、日限3（T+1资本日转，理论上日均可3笔）。
Q1 缺口低(避周一) 纯T+1 无闸门（唯一能天天出票的族）
Q2 Q1+只妖股期
Q3 恐慌族5合1 T+1 无闸门（底座/复活门/摇篮/TD9）
Q4 缺口低+成簇门(≥5)
Q5 全6主张 T+1 无闸门
Q6 全6主张+只妖股期
Q7 全6主张+妖股期+大簇日（频率vs质量折中）
"""
import sys, json, statistics as st
from datetime import date
sys.path.insert(0, 'engine')
import law_pipeline as lp

stocks = lp.load_universe()
lp.build_xsection(stocks)
regime = lp.load_regime()
CLAIMS = {'跌停底座': '组合_跌停低_三连阴', '复活门': '反转族_跌停潮50', '摇篮': '妖股摇篮_成簇',
          '缺口低': '组合_缺口低开_低位阳线_避周一',
          'TD9输家': '组合_跌停低_TD9买_输家250', 'TD9超跌': '组合_跌停低_TD9买_超跌20'}
PANIC5 = {'跌停底座', '复活门', '摇篮', 'TD9输家', 'TD9超跌'}
ALL6 = set(CLAIMS)
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
day_cl = {}
for r in raw:
    day_cl[r['dt']] = day_cl.get(r['dt'], 0) + 1
LDC = lp._XLDC
big = lambda dt: day_cl.get(dt, 0) >= 8 or LDC.get(dt, 0) >= 30

CANDS = []
for r in raw:
    d = stocks[r['code']]
    ei = r['i'] + 1
    if ei + 1 >= d['n']:
        continue
    entry_d = d['date'][ei]
    if not (WIN0 <= entry_d <= WIN1):
        continue
    # T+1出场=i+2收盘
    CANDS.append({'entry_d': entry_d, 'pos60': r['pos60'], 'claim': r['claim'],
                  'code': r['code'], 'rg': r['rg'], 'ep': lp._epx(d, r['i']),
                  'xi': ei + 1, 'sig_d': r['dt'], 'i': r['i']})
CANDS.sort(key=lambda x: (x['entry_d'], -x['pos60']))


def wd(ds):
    return date(int(ds[:4]), int(ds[5:7]), int(ds[8:10])).weekday()


def sim(families, gate=None, cluster_gate=False, day_cap=3):
    cash = 50000.0
    positions, trades, eq = [], [], []
    p = 0
    for day in CAL:
        # 出场（昨入今出）
        for pos in [x for x in positions if x['exit_d'] == day]:
            d = stocks[pos['code']]
            cash += 5000 * (d['c'][pos['xi']] / pos['ep']) * (1 - FEE)
            trades.append({'ret': d['c'][pos['xi']] / pos['ep'] - 1 - FEE, 'year': day[:4]})
        positions[:] = [x for x in positions if x['exit_d'] != day]
        entered = 0
        while p < len(CANDS) and CANDS[p]['entry_d'] == day:
            cd = CANDS[p]
            p += 1
            if cd['claim'] not in families or entered >= day_cap:
                continue
            if gate == '妖股期' and cd['rg'] != '妖股期':
                continue
            if gate == '恐慌期' and cd['rg'] != '恐慌期':
                continue
            if gate == '大簇' and not big(cd['sig_d']):
                continue
            if cluster_gate and cd['claim'] in GATED and len(cl.get(cd['sig_d'], set())) < 5 and cd['rg'] != '恐慌期':
                continue
            if len(positions) < 10 and cash >= 5000:
                d = stocks[cd['code']]
                cash -= 5000
                positions.append({'code': cd['code'], 'ep': cd['ep'], 'xi': cd['xi'],
                                  'exit_d': d['date'][cd['xi']]})
                entered += 1
        eq.append(cash + sum(5000 for _ in positions))
    for pos in positions:
        d = stocks[pos['code']]
        cash += 5000 * (d['c'][-1] / pos['ep']) * (1 - FEE)
        trades.append({'ret': d['c'][-1] / pos['ep'] - 1 - FEE, 'year': '2026'})
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
            'per_year': len(trades) / 7.7,
            'ypnl': {y: sum(v) * 5000 for y, v in sorted(by_year.items())}}


print(f'{"配置":<24}{"笔数":>7}{"年均":>6}{"胜率":>6}{"盈亏比":>6}{"均笔":>8}{"期末":>10}{"收益":>8}{"回撤":>8}')
for name, fam, gate, cg in [
    ('Q1 缺口低 T+1 无闸门', {'缺口低'}, None, False),
    ('Q2 缺口低+只妖股期', {'缺口低'}, '妖股期', False),
    ('Q3 恐慌5族 T+1 无闸门', PANIC5, None, True),
    ('Q4 缺口低+成簇≥5', {'缺口低'}, None, True),
    ('Q5 全6主张 无闸门', ALL6, None, True),
    ('Q6 全6+只妖股期', ALL6, '妖股期', True),
    ('Q7 全6+妖股期+大簇日', ALL6, '大簇', True),
]:
    r = sim(fam, gate, cg)
    print(f'{name:<24}{r["n"]:>7}{r["per_year"]:>5.0f}{r["wr"]:>5.0f}%{r["pf"]:>6.2f}{r["avg"]:>+7.2f}%{r["final"]:>9,.0f}{100*(r["final"]/50000-1):>+7.1f}%{100*r["mdd"]:>7.1f}%')
    print(f'   逐年: {dict((y, f"{v:+,.0f}") for y, v in r["ypnl"].items())}')