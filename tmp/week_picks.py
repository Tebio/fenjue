import json, sys, statistics as st
from collections import defaultdict
sys.path.insert(0, 'engine')
import law_pipeline as lp

FEE = 0.0015
WEEK = ['2026-09-14', '2026-09-15', '2026-09-16', '2026-09-17', '2026-09-18']
STRATS = [
    ('深档低位(底座)', '跌停接_MA60下'),
    ('TD9旗舰·输家', '组合_跌停低_TD9买_输家250'),
    ('TD9旗舰·超跌', '组合_跌停低_TD9买_超跌20'),
    ('触板TD9', '组合_触板低_TD9买_剔亏ST_超跌20'),
    ('缺口四条件', '组合_缺口低_剔亏ST_超跌20_输家250'),
    ('缺口避周一', '组合_缺口低开_低位阳线_避周一'),
]
names = {}
for s in json.load(open('data/main_board_codes.json'))['stocks']:
    names[str(s['code']).zfill(6)] = s.get('name', '')

stocks = lp.load_universe()
lp.build_xsection(stocks)

def fwd(code, i, h):
    d = stocks[code]
    ei = i + 1
    if ei + h >= d['n'] or d['o'][ei] <= 0 or d['o'][ei] <= d['c'][i] * 0.905:
        return None
    return d['c'][ei + h] / d['o'][ei] - 1 - FEE

for label, detname in STRATS:
    det = lp.REGISTRY[detname]
    print(f'== {label} ==')
    for dt in WEEK:
        hits = []
        for code, d in stocks.items():
            if dt not in d['date']:
                continue
            i = d['date'].index(dt)
            if i < 61 or i + 1 >= d['n'] or d['o'][i + 1] <= 0:
                continue
            try:
                if det(d, i):
                    hits.append(code)
            except Exception:
                pass
        if not hits:
            continue
        cluster = '成簇✓' if len(hits) >= 5 else '零星✗'
        rows = []
        for code in hits:
            d = stocks[code]
            i = d['date'].index(dt)
            r1, r2, r3 = fwd(code, i, 1), fwd(code, i, 2), fwd(code, i, 3)
            def f(r):
                return f'{r*100:+.1f}%' if r is not None else '—'
            rows.append(f"{names.get(code, code)}{code}[T1{f(r1)}/T2{f(r2)}/T3{f(r3)}]")
        print(f'  {dt} {cluster} {len(hits)}只: ' + '、'.join(rows[:12]) + ('…' if len(rows) > 12 else ''))
    print()

# B5 本周（读归档）
print('== B5 半路板（归档 banlu_signals.jsonl）==')
try:
    for line in open('data/banlu_signals.jsonl'):
        r = json.loads(line)
        if r.get('date') in WEEK:
            print(f"  {r['date']} {r.get('name')}{r['code']} 触发{r.get('trigger')} 位置{r.get('pos')} regime合规={r.get('regime_ok')}")
except FileNotFoundError:
    print('  无归档')
