"""T+1 妖股期缺口低：选择机制对照——池级+1.81% 如何保到组合层。
每日信号池中取3张：A随机(10种子) B量比最高 C当日涨幅最高 D市值最小 E最浅(pos60) F最深
入场次日开盘，T+1(第三天)收盘卖，费0.3%，10槽×5000，全史妖股期日。
"""
import sys, json, statistics as st, random
sys.path.insert(0, 'engine')
import law_pipeline as lp

stocks = lp.load_universe()
lp.build_xsection(stocks)
regime = lp.load_regime()
det = lp.REGISTRY['组合_缺口低开_低位阳线_避周一']
FEE = 0.003

pool = []
for code, d in stocks.items():
    n = d['n']
    c, h, v = d['c'], d['h'], d['v']
    for i in range(lp.START, n - 2):
        dt = d['date'][i]
        if dt < '2019-01-01' or regime.get(dt) != '妖股期' or lp._epx(d, i) <= 0:
            continue
        try:
            if not det(d, i):
                continue
        except Exception:
            continue
        hi60 = max(h[max(0, i - 60):i]) if i >= 1 else 0
        pos60 = c[i - 1] / hi60 - 1 if hi60 > 0 else 0
        vols = [v[x] for x in range(max(1, i - 5), i)]
        vr = v[i] / (sum(vols) / len(vols)) if vols and sum(vols) > 0 else 1
        ret = c[i + 2] / lp._epx(d, i) - 1 - FEE
        pool.append({'dt': dt, 'code': code, 'ret': ret, 'pos60': pos60, 'vr': vr,
                     'pct': c[i] / c[i - 1] - 1})
by_day = {}
for r in pool:
    by_day.setdefault(r['dt'], []).append(r)
print(f'妖股期池 {len(pool)} 信号 / {len(by_day)} 天')

def run(key_fn, seeds=1):
    outs = []
    for s in range(seeds):
        rnd = random.Random(s)
        rets = []
        for dt, rows in by_day.items():
            rows2 = sorted(rows, key=key_fn(rnd))
            for r in rows2[:3]:
                rets.append(r['ret'])
        outs.append(rets)
    allr = [x for o in outs for x in o]
    w = sum(1 for x in allr if x > 0)
    return f'{100*w/len(allr):.0f}%/{100*st.mean(allr):+.2f}%'

print('每日取3张（全史妖股期）:')
print('A 随机(5种子):', run(lambda rnd: lambda r: rnd.random(), 5))
print('B 量比最高:', run(lambda rnd: lambda r: -r['vr']))
print('C 涨幅最高:', run(lambda rnd: lambda r: -r['pct']))
print('E 最浅(pos60):', run(lambda rnd: lambda r: -r['pos60']))
print('F 最深(pos60):', run(lambda rnd: lambda r: r['pos60']))
print('G 涨幅最低:', run(lambda rnd: lambda r: r['pct']))
# 池级参照
allr = [r['ret'] for r in pool]
w = sum(1 for x in allr if x > 0)
print(f'池级全量: {100*w/len(allr):.0f}%/{100*st.mean(allr):+.2f}%')