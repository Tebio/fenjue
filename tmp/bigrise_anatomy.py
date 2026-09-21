"""大涨票逆向解剖（2019→2026/9）：20日≥+50% 的启动点，回扫启动前。
回答：①咱家探测器在启动前5日覆盖率 ②漏掉的长什么样 ③「反人性」浓度
     （启动前10日内有跌停/深跌的比例=最反人性的入场点）
"""
import sys, json, statistics as st
sys.path.insert(0, 'engine')
import law_pipeline as lp

stocks = lp.load_universe()
lp.build_xsection(stocks)
regime = lp.load_regime()

DETS = {k: lp.REGISTRY[k] for k in ('组合_跌停低_三连阴', '反转族_跌停潮50', '妖股摇篮_成簇',
                                    '组合_跌停低_TD9买_输家250', '组合_跌停低_TD9买_超跌20',
                                    '组合_缺口低开_低位阳线_避周一')}

# 找大涨启动点：T 日之后 20 日内区间最高涨幅 ≥+50%（取每段行情的第一次突破）
events = []
for code, d in stocks.items():
    c, n = d['c'], d['n']
    i = lp.START
    while i < n - 21:
        hi = max(c[i + 1:i + 21])
        if hi / c[i] - 1 >= 0.50:
            events.append({'code': code, 'i': i, 'dt': d['date'][i]})
            i += 20  # 跳过这段行情
        else:
            i += 1
print(f'大涨启动事件 {len(events)} 次（20日≥+50%）')

caught, missed = [], []
for ev in events:
    d = stocks[ev['code']]
    i = ev['i']
    hit_by = []
    for name, det in DETS.items():
        for j in range(max(lp.START, i - 5), i):
            try:
                if det(d, j):
                    hit_by.append(name)
                    break
            except Exception:
                pass
    # 启动前状态
    c, h, l = d['c'], d['h'], d['l']
    pre5 = c[i - 1] / c[i - 6] - 1 if i >= 6 else 0
    hi60 = max(h[max(0, i - 60):i]) if i >= 1 else 0
    pos60 = c[i - 1] / hi60 - 1 if hi60 > 0 else 0
    ldc10 = sum(1 for j in range(max(1, i - 10), i) if c[j] / c[j - 1] - 1 <= -0.095)
    deep10 = sum(1 for j in range(max(1, i - 10), i) if c[j] / c[j - 1] - 1 <= -0.05)
    rec = {**ev, 'hit_by': hit_by, 'pre5': pre5, 'pos60': pos60,
           'ldc10': ldc10, 'deep10': deep10, 'rg': regime.get(ev['dt'], '?')}
    (caught if hit_by else missed).append(rec)

print(f'\n启动前5日被咱家探测器覆盖: {len(caught)} ({100*len(caught)/len(events):.1f}%)')
print(f'漏掉: {len(missed)} ({100*len(missed)/len(events):.1f}%)')

def profile(rows, label):
    if not rows:
        return
    ldc = sum(1 for r in rows if r['ldc10'] > 0)
    deep = sum(1 for r in rows if r['deep10'] > 0)
    quiet = sum(1 for r in rows if abs(r['pre5']) < 0.05 and r['ldc10'] == 0 and r['deep10'] == 0)
    low = sum(1 for r in rows if r['pos60'] < -0.30)
    high = sum(1 for r in rows if r['pos60'] > -0.05)
    print(f'{label}: pre5均值{100*st.mean([r["pre5"] for r in rows]):+.1f}% | '
          f'前10日有跌停{100*ldc/len(rows):.1f}% 有深跌{100*deep/len(rows):.1f}% | '
          f'启动前完全平静{100*quiet/len(rows):.1f}% | 深位(<-30%){100*low/len(rows):.1f}% 贴高(>-5%){100*high/len(rows):.1f}%')

profile(caught, '\n被覆盖的')
profile(missed, '被漏掉的')

from collections import Counter
print('\n漏掉的事件 regime 分布:', dict(Counter(r['rg'] for r in missed)))
print('被覆盖的 regime 分布:', dict(Counter(r['rg'] for r in caught)))
print('\n反人性总量：全部大涨票中，启动前10日内出现过跌停的:')
allldc = sum(1 for r in caught + missed if r['ldc10'] > 0)
print(f'  {allldc}/{len(events)} = {100*allldc/len(events):.1f}%')
# 漏掉且前10日有跌停的=咱家恐慌族眼皮底下漏的
mldc = [r for r in missed if r['ldc10'] > 0]
print(f'其中被漏掉的: {len(mldc)} 次')
for r in mldc[:8]:
    print(f"  {r['dt']} {r['code']} pos60={r['pos60']:.2f} pre5={100*r['pre5']:+.1f}% regime={r['rg']}")