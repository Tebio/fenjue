"""金健米业/国芳集团：全家注册探测器在 2026-08-01→09-18 逐日扫，看哪些哪天开火。"""
import sys
sys.path.insert(0, 'engine')
import law_pipeline as lp

stocks = lp.load_universe()
lp.build_xsection(stocks)

for code in ('600127', '601086'):
    d = stocks.get(code)
    if not d:
        continue
    print(f'\n== {code} ==')
    for name, det in lp.REGISTRY.items():
        hits = []
        for i in range(lp.START, d['n'] - 1):
            dt = d['date'][i]
            if dt < '2026-08-01' or dt > '2026-09-18':
                continue
            try:
                if det(d, i):
                    hits.append(dt)
            except Exception:
                pass
        if hits:
            print(f'  {name}: {hits}')