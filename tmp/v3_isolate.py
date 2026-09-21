"""隔离实验：全史 v3 的选票规则是毒药吗？pos60最深 vs 随机（5种子）。
同样口径只改选票。"""
import sys, json, statistics as st, bisect, random
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
IDXCAL = [k['date'] for k in json.loads(open('data/index_sh000001.json').read())]

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


def run(pick, seed=0):
    win0, win1 = '2018-01-01', '2026-09-18'
    rnd = random.Random(seed)
    positions, cash, trades, missed = [], 50000.0, [], 0
    cands = []
    for r in kept:
        d = stocks[r['code']]
        ei = r['i'] + 1
        if ei >= d['n']:
            continue
        entry_d = d['date'][ei]
        if not (win0 <= entry_d <= win1):
            continue
        r1 = d['c'][ei] / lp._epx(d, r['i']) - 1
        tgt = 20 if r1 >= 0.03 else 10
        xi = min(ei + tgt, d['n'] - 1)
        key = r['pos60'] if pick == 'pos60' else rnd.random()
        cands.append((entry_d, key, r, ei, xi))
    cands.sort(key=lambda x: (x[0], x[1]))
    p = 0
    cal = [d for d in IDXCAL if win0 <= d <= win1]
    for day in cal:
        for pos in [x for x in positions if x['exit_d'] == day]:
            d = stocks[pos['code']]
            cash += 5000 * (d['c'][pos['exit_i']] / pos['ep']) * (1 - FEE)
            trades.append(d['c'][pos['exit_i']] / pos['ep'] - 1 - FEE)
        positions = [x for x in positions if x['exit_d'] != day]
        while p < len(cands) and cands[p][0] == day:
            _, _, r, ei, xi = cands[p]
            p += 1
            if len(positions) < 10 and cash >= 5000:
                d = stocks[r['code']]
                ep = lp._epx(d, r['i'])
                cash -= 5000
                positions.append({'code': r['code'], 'ep': ep, 'exit_i': xi,
                                  'exit_d': d['date'][xi]})
            else:
                missed += 1
    for pos in positions:
        d = stocks[pos['code']]
        cash += 5000 * (d['c'][-1] / pos['ep']) * (1 - FEE)
        trades.append(d['c'][-1] / pos['ep'] - 1 - FEE)
    return cash, trades

# 全信号等权基准（无容量约束的上限参照）
allrets = []
for r in kept:
    d = stocks[r['code']]
    ei = r['i'] + 1
    if ei >= d['n']:
        continue
    r1 = d['c'][ei] / lp._epx(d, r['i']) - 1
    tgt = 20 if r1 >= 0.03 else 10
    xi = min(ei + tgt, d['n'] - 1)
    allrets.append(d['c'][xi] / lp._epx(d, r['i']) - 1 - FEE)
print(f'全信号等权（无容量约束）: {len(allrets)} 笔 胜率{100*sum(1 for x in allrets if x>0)/len(allrets):.1f}% 均{100*st.mean(allrets):+.3f}%')

cash, trades = run('pos60')
print(f'\n超跌最深选票: 期末 {cash:,.0f} 元 | {len(trades)} 笔 胜率{100*sum(1 for x in trades if x>0)/len(trades):.1f}% 均{100*st.mean(trades):+.2f}%')
res = [run('random', s) for s in (1, 2, 3, 4, 5)]
cs = [r[0] for r in res]
ts = [x for r in res for x in r[1]]
print(f'随机票（5种子合计）: 期末均值 {st.mean(cs):,.0f} 元 | 胜率{100*sum(1 for x in ts if x>0)/len(ts):.1f}% 均{100*st.mean(ts):+.2f}%')