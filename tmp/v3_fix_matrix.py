"""容量死亡螺旋修复矩阵：全史 2018→2026/9，逐修复隔离+组合。
修复方向（AGENTS#122）：
  F1 危机日限槽：每日最多新入场 K 笔（防首日填满锁仓）
  F2 regime 启停：信号日 regime ∈ {妖股期, 恐慌期} 才允许入场（平淡期空仓）
  F3 短持轮转：T+5 固定出场（资本回收快 2-4 倍）
配置矩阵：BASE(v3) / F3 / F1 / F1+F3 / F2 / F2+F3 / F1+F2+F3 / F1(5)+F3
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
PANIC_FAM = {'跌停底座', 'TD9输家', 'TD9超跌'}
FEE = 0.003
WIN0, WIN1 = '2018-01-01', '2026-09-18'
IDXCAL = [k['date'] for k in json.loads(open('data/index_sh000001.json').read())]
CAL = [d for d in IDXCAL if WIN0 <= d <= WIN1]

# ── 信号收集 + 双出场预计算（只跑一遍探测）──
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
    if r['claim'] in PANIC_FAM:
        cl.setdefault(r['dt'], set()).add(r['code'])
kept, seen = [], set()
for r in sorted(raw, key=lambda x: (x['dt'], x['pos60'])):
    if r['claim'] in PANIC_FAM and len(cl.get(r['dt'], set())) < 5 and r['rg'] != '恐慌期':
        continue
    key = (r['dt'], r['code'])
    if key not in seen:
        seen.add(key)
        kept.append(r)

# 预计算候选：入场日、pos60、T+5出场、T1分档出场
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
    xi5 = min(ei + 5, d['n'] - 1)
    r1 = d['c'][ei] / ep - 1
    tgt = 20 if r1 >= 0.03 else 10
    xit = min(ei + tgt, d['n'] - 1)
    CANDS.append({'entry_d': entry_d, 'pos60': r['pos60'], 'claim': r['claim'],
                  'code': r['code'], 'rg': r['rg'],
                  'ep': ep, 'xi5': xi5, 'xit': xit})
CANDS.sort(key=lambda x: (x['entry_d'], x['pos60']))
print(f'候选 {len(CANDS)} 笔')


def sim(day_cap=None, regime_gate=False, exits='T1'):
    cash = 50000.0
    positions = []
    trades = []
    p = 0
    eq_curve = []
    for day in CAL:
        for pos in [x for x in positions if x['exit_d'] == day]:
            d = stocks[pos['code']]
            cash += 5000 * (d['c'][pos['xi']] / pos['ep']) * (1 - FEE)
            trades.append({'ret': d['c'][pos['xi']] / pos['ep'] - 1 - FEE,
                           'claim': pos['claim'], 'year': pos['entry_d'][:4]})
        positions = [x for x in positions if x['exit_d'] != day]
        entered = 0
        while p < len(CANDS) and CANDS[p]['entry_d'] == day:
            cd = CANDS[p]
            p += 1
            if regime_gate and cd['rg'] not in ('妖股期', '恐慌期'):
                continue
            if day_cap and entered >= day_cap:
                continue
            if len(positions) < 10 and cash >= 5000:
                d = stocks[cd['code']]
                xi = cd['xi5'] if exits == 'T5' else cd['xit']
                cash -= 5000
                positions.append({'code': cd['code'], 'ep': cd['ep'], 'xi': xi,
                                  'exit_d': d['date'][xi], 'claim': cd['claim'],
                                  'entry_d': day})
                entered += 1
        mtm = cash
        for pos in positions:
            d = stocks[pos['code']]
            j = d['date'].index(day) if day in d['date'] else None
            mtm += 5000 * (d['c'][j] / pos['ep']) if j else 5000
        eq_curve.append(mtm)
    for pos in positions:
        d = stocks[pos['code']]
        cash += 5000 * (d['c'][-1] / pos['ep']) * (1 - FEE)
        trades.append({'ret': d['c'][-1] / pos['ep'] - 1 - FEE,
                       'claim': pos['claim'], 'year': pos['entry_d'][:4]})
    peak, mdd = 50000.0, 0.0
    for e in eq_curve:
        peak = max(peak, e)
        mdd = min(mdd, (e - peak) / peak)
    rets = [t['ret'] for t in trades]
    wins = sum(1 for x in rets if x > 0)
    by_year = {}
    for t in trades:
        by_year.setdefault(t['year'], []).append(t['ret'])
    ypnl = {y: sum(v) * 5000 for y, v in sorted(by_year.items())}
    return {'final': cash, 'mdd': mdd, 'n': len(trades),
            'wr': 100 * wins / len(rets) if rets else 0,
            'avg': 100 * st.mean(rets) if rets else 0,
            'worst': 100 * min(rets) if rets else 0, 'ypnl': ypnl,
            'trades': trades}


CONFIGS = [
    ('BASE=v3（T1分档/无限制）', dict()),
    ('F3 短持T+5', dict(exits='T5')),
    ('F1 日限3槽', dict(day_cap=3)),
    ('F1+F3', dict(day_cap=3, exits='T5')),
    ('F2 regime启停', dict(regime_gate=True)),
    ('F2+F3', dict(regime_gate=True, exits='T5')),
    ('F1+F2+F3 全套', dict(day_cap=3, regime_gate=True, exits='T5')),
    ('F1(5)+F2+F3', dict(day_cap=5, regime_gate=True, exits='T5')),
]
print(f'\n{"配置":<24}{"笔数":>6}{"胜率":>7}{"均笔":>9}{"期末权益":>12}{"收益率":>9}{"最大回撤":>9}{"单笔最惨":>9}')
for name, kw in CONFIGS:
    r = sim(**kw)
    print(f'{name:<24}{r["n"]:>6}{r["wr"]:>6.0f}%{r["avg"]:>+8.2f}%{r["final"]:>11,.0f}{100*(r["final"]/50000-1):>+8.1f}%{100*r["mdd"]:>8.1f}%{r["worst"]:>+8.1f}%')
    print(f'   逐年: {dict((y, f"{p:+,.0f}") for y, p in r["ypnl"].items())}')