import sys
sys.path.insert(0, 'engine')
import law_pipeline as lp
stocks = lp.load_universe()
lp.build_xsection(stocks)
regime = lp.load_regime()
det = lp.REGISTRY['组合_缺口低开_低位阳线_避周一']
from collections import Counter
cnt = Counter()
for code, d in stocks.items():
    n = d['n']
    for i in range(lp.START, n - 1):
        dt = d['date'][i]
        if dt < '2026-07-01':
            continue
        try:
            if det(d, i):
                cnt[dt] += 1
        except Exception:
            pass
print('7月以来缺口低日簇（近30个交易日）:')
for dt in sorted(cnt)[-30:]:
    mark = '🔥MEGA' if cnt[dt] >= 20 else ''
    print(f'  {dt}: {cnt[dt]} {mark} regime={regime.get(dt, "?")}')
mega7 = [dt for dt in cnt if cnt[dt] >= 20]
print(f'\n7月以来巨簇日 {len(mega7)} 个:', mega7)