"""缺口低信号 × 行业梯队（当日同行业涨停≥3）分层：T+1/T+3 收益对照。
若梯队组显著强，v1宽清单获得可执行的排序规则（梯队优先上仓位）。
"""
import sys, json, statistics as st
from collections import defaultdict
sys.path.insert(0, 'engine')
import law_pipeline as lp

stocks = lp.load_universe()
lp.build_xsection(stocks)
regime = lp.load_regime()
mmap = json.load(open('data/industry_map.json'))
code2ind = {str(k).zfill(6): v['industry'] for k, v in mmap.items() if isinstance(v, dict) and v.get('industry')}

# 行业→日→涨停数（全史）
sec_board = defaultdict(lambda: defaultdict(int))
for code, d in stocks.items():
    ind = code2ind.get(code)
    if not ind:
        continue
    c = d['c']
    for i in range(1, d['n']):
        if c[i] / c[i - 1] - 1 >= 0.098:
            sec_board[ind][d['date'][i]] += 1

det = lp.REGISTRY['组合_缺口低开_低位阳线_避周一']
groups = defaultdict(list)
day_cl = defaultdict(int)
for code, d in stocks.items():
    n = d['n']
    c = d['c']
    for i in range(lp.START, n - 4):
        dt = d['date'][i]
        if dt < '2019-01-01' or lp._epx(d, i) <= 0:
            continue
        try:
            if not det(d, i):
                continue
        except Exception:
            continue
        day_cl[dt] += 1
        ind = code2ind.get(code, '')
        nbd = sec_board[ind].get(dt, 0) if ind else 0
        ep = lp._epx(d, i)
        r1 = c[i + 2] / ep - 1 - 0.003
        r3 = c[i + 4] / ep - 1 - 0.003
        rg = regime.get(dt, '?')
        groups[('梯队≥3', rg)].append((r1, r3)) if nbd >= 3 else groups[('梯队<3', rg)].append((r1, r3))
        groups[('梯队≥3', 'ALL')].append((r1, r3)) if nbd >= 3 else groups[('梯队<3', 'ALL')].append((r1, r3))

print(f'{"分组":<24}{"n":>7}{"T+1胜率":>8}{"T+1均":>8}{"T+3胜率":>8}{"T+3均":>8}')
for (g, rg), rows in sorted(groups.items()):
    if len(rows) < 200:
        continue
    r1 = [x[0] for x in rows]
    r3 = [x[1] for x in rows]
    w1 = sum(1 for x in r1 if x > 0)
    w3 = sum(1 for x in r3 if x > 0)
    print(f'{g}|{rg:<14}{len(rows):>7}{100*w1/len(r1):>7.0f}%{100*st.mean(r1):>+7.2f}%{100*w3/len(r3):>7.0f}%{100*st.mean(r3):>+7.2f}%')

# 巨簇日（≥20）内再分梯队——看 T1-MEGA 里能否再精选
print('\n巨簇日（簇≥20）内 梯队≥3 vs <3:')
for g, rg in (('梯队≥3', 'ALL'), ('梯队<3', 'ALL')):
    pass
mega_groups = defaultdict(list)
for code, d in stocks.items():
    n = d['n']
    c = d['c']
    for i in range(lp.START, n - 4):
        dt = d['date'][i]
        if dt < '2019-01-01' or lp._epx(d, i) <= 0:
            continue
        try:
            if not det(d, i):
                continue
        except Exception:
            continue
        # 巨簇判定需要全池——先记录，后过滤
        ind = code2ind.get(code, '')
        nbd = sec_board[ind].get(dt, 0) if ind else 0
        ep = lp._epx(d, i)
        mega_groups[dt].append({'nbd': nbd, 'r1': c[i + 2] / ep - 1 - 0.003,
                                'r3': c[i + 4] / ep - 1 - 0.003})
for th in (20,):
    a1, a3, b1, b3 = [], [], [], []
    for dt, rows in mega_groups.items():
        if len(rows) < th:
            continue
        for r in rows:
            (a1 if r['nbd'] >= 3 else b1).append(r['r1'])
            (a3 if r['nbd'] >= 3 else b3).append(r['r3'])
    for lb, v1, v3 in (('梯队≥3', a1, a3), ('梯队<3', b1, b3)):
        if v1:
            w1 = sum(1 for x in v1 if x > 0)
            w3 = sum(1 for x in v3 if x > 0)
            print(f'  {lb}: n={len(v1)} T+1 {100*w1/len(v1):.0f}%/{100*st.mean(v1):+.2f}% T+3 {100*w3/len(v3):.0f}%/{100*st.mean(v3):+.2f}%')