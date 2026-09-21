"""回撤避法矩阵：全史口径，测哪种过滤能砍回撤且保收益。
A 指数>MA60 才入场（熊市滤网）
B 指数>MA200 才入场
C 恐慌 streak 第2天才入场（首日不接刀）
D 组合熔断：权益回撤>10% 停新仓，直到指数重回 MA20
E 个股-12%硬止损
F A+C 组合
G A+C+D 全组合
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
FEE = 0.003
WIN0, WIN1 = '2018-01-01', '2026-09-18'
IDX = json.loads(open('data/index_sh000001.json').read())
IDXCAL = [k['date'] for k in IDX]
CAL = [d for d in IDXCAL if WIN0 <= d <= WIN1]
# 指数均线（PIT：只用当日及以前）
ixc = [k['close'] for k in IDX]
ixma = {}
for i, k in enumerate(IDX):
    if i >= 59:
        ixma[(k['date'], 60)] = sum(ixc[i - 59:i + 1]) / 60
    if i >= 199:
        ixma[(k['date'], 200)] = sum(ixc[i - 199:i + 1]) / 200
    if i >= 19:
        ixma[(k['date'], 20)] = sum(ixc[i - 19:i + 1]) / 20
# 恐慌 streak 编号
streak = {}
s = 0
for k in IDX:
    if regime.get(k['date']) == '恐慌期':
        s += 1
    else:
        s = 0
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
    ep = lp._epx(d, r['i'])
    CANDS.append({'entry_d': entry_d, 'pos60': r['pos60'], 'claim': r['claim'],
                  'code': r['code'], 'rg': r['rg'], 'ep': ep, 'xi5': min(ei + 5, d['n'] - 1),
                  'sig_d': r['dt']})
CANDS.sort(key=lambda x: (x['entry_d'], -x['pos60']))


def sim(ma_filter=None, panic_day2=False, breaker=False, stop=None):
    cash = 50000.0
    positions, trades, eq = [], [], []
    p = 0
    peak_eq = 50000.0
    paused = False
    for day in CAL:
        idxx = IDX[IDXCAL.index(day)]
        for pos in [x for x in positions if x['exit_d'] == day]:
            d = stocks[pos['code']]
            cash += 5000 * (d['c'][pos['xi']] / pos['ep']) * (1 - FEE)
            trades.append(d['c'][pos['xi']] / pos['ep'] - 1 - FEE)
        positions = [x for x in positions if x['exit_d'] != day]
        # 硬止损：当日收盘跌破 -stop 即出
        if stop:
            for pos in [x for x in positions]:
                d = stocks[pos['code']]
                try:
                    j = d['date'].index(day)
                except ValueError:
                    continue
                if d['c'][j] / pos['ep'] - 1 <= -stop:
                    cash += 5000 * (d['c'][j] / pos['ep']) * (1 - FEE)
                    trades.append(d['c'][j] / pos['ep'] - 1 - FEE)
                    pos['xi'] = j
                    pos['exit_d'] = day
            positions = [x for x in positions if x['exit_d'] != day]
        # 熔断器状态
        cur_eq = cash + sum(5000 for _ in positions)
        peak_eq = max(peak_eq, cur_eq)
        if breaker:
            if not paused and cur_eq < peak_eq * 0.90:
                paused = True
            elif paused and ixma.get((day, 20)) and idxx['close'] > ixma[(day, 20)]:
                paused = False
        entered = 0
        while p < len(CANDS) and CANDS[p]['entry_d'] == day:
            cd = CANDS[p]
            p += 1
            if entered >= 3 or cd['rg'] not in ('妖股期', '恐慌期'):
                continue
            if breaker and paused:
                continue
            if ma_filter and ixma.get((cd['sig_d'], ma_filter)):
                if IDX[IDXCAL.index(cd['sig_d'])]['close'] <= ixma[(cd['sig_d'], ma_filter)]:
                    continue
            if panic_day2 and cd['rg'] == '恐慌期' and streak.get(cd['sig_d'], 0) < 2:
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
        trades.append(d['c'][-1] / pos['ep'] - 1 - FEE)
    pk, mdd = 50000.0, 0.0
    for e in eq:
        pk = max(pk, e)
        mdd = min(mdd, (e - pk) / pk)
    wins = sum(1 for x in trades if x > 0)
    return cash, mdd, len(trades), 100 * wins / len(trades) if trades else 0, \
        100 * st.mean(trades) if trades else 0, 100 * min(trades) if trades else 0


print(f'{"配置":<22}{"笔数":>6}{"胜率":>6}{"均笔":>9}{"期末":>10}{"收益":>8}{"最大回撤":>9}{"最惨":>8}')
base = sim()
print(f'{"H3 基准":<22}{base[2]:>6}{base[3]:>5.0f}%{base[4]:>+8.2f}%{base[0]:>9,.0f}{100*(base[0]/50000-1):>+7.1f}%{100*base[1]:>8.1f}%{base[5]:>+7.1f}%')
for name, kw in [
    ('A 指数>MA60', dict(ma_filter=60)),
    ('B 指数>MA200', dict(ma_filter=200)),
    ('C 恐慌第2天才接', dict(panic_day2=True)),
    ('D 权益熔断90%', dict(breaker=True)),
    ('E 个股-12%止损', dict(stop=0.12)),
    ('F A+C', dict(ma_filter=60, panic_day2=True)),
    ('G A+C+D', dict(ma_filter=60, panic_day2=True, breaker=True)),
]:
    r = sim(**kw)
    print(f'{name:<22}{r[2]:>6}{r[3]:>5.0f}%{r[4]:>+8.2f}%{r[0]:>9,.0f}{100*(r[0]/50000-1):>+7.1f}%{100*r[1]:>8.1f}%{r[5]:>+7.1f}%')