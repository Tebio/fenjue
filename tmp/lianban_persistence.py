"""连板持续性分组研究：什么样的票连红/连板概率高？新龙vs老龙？
探索性分析（未注册主张，不进管线——回答用户提问用）
事件=主板日收盘涨停(pct>=9.8)；结局=T+1再涨停/收红/≥+5%/≤-5%
分组：连板数(1/2/3+)、新龙vs老龙(前120日有过>=2连板 或 前60日涨幅>=50% 且非本次启动)、MA60位置
"""
import json, sys
from pathlib import Path
from collections import defaultdict

ROOT = Path('/opt/data/fenjue')
KC = ROOT / 'data/big_kcache'
codes = [str(s['code']).zfill(6) for s in json.load(open(ROOT / 'data/main_board_codes.json'))['stocks']]
codes += [c.replace('.json', '') for c in __import__('os').listdir(KC) if c.endswith('.json')]
codes = sorted(set(c for c in codes if c[:2] in ('60', '00')))  # 主板口径

def stat_cell():
    return {'n': 0, 'board': 0, 'red': 0, 'up5': 0, 'dn5': 0, 'ret': 0.0}

cells = defaultdict(stat_cell)   # (连板档, 龙型, ma60位) → cell
dragon_cells = defaultdict(stat_cell)  # (龙型,) 单独看
total_events = 0

for i, c in enumerate(codes):
    fp = KC / f'{c}.json'
    if not fp.exists(): continue
    try: ks = json.load(open(fp))
    except Exception: continue
    if len(ks) < 130: continue
    closes = [k['close'] for k in ks]
    dates = [k['date'] for k in ks]
    # 涨停标记
    is_lu = [False] * len(ks)
    for t in range(1, len(ks)):
        if closes[t - 1] > 0 and (closes[t] / closes[t - 1] - 1) >= 0.098:
            is_lu[t] = True
    for t in range(130, len(ks) - 1):
        if not is_lu[t]: continue
        total_events += 1
        # 连板数（含t）
        streak = 1
        while t - streak >= 0 and is_lu[t - streak]:
            streak += 1
        sg = '1板' if streak == 1 else '2板' if streak == 2 else '3板+'
        # 新龙/老龙：t之前120日内（不含本次streak起点后）是否有>=2连板，或启动点前60日涨幅>=50%
        start = t - streak + 1
        prev_dragon = False
        run = 0
        for u in range(max(1, start - 120), start):
            if is_lu[u]:
                run += 1
                if run >= 2: prev_dragon = True; break
            else:
                run = 0
        r60 = closes[start - 1] / closes[max(0, start - 61)] - 1 if start >= 61 else 0
        dragon = '老龙' if (prev_dragon or r60 >= 0.5) else '新龙'
        # MA60位置
        ma60 = sum(closes[t - 59:t + 1]) / 60
        pos = 'MA60上' if closes[t] >= ma60 else 'MA60下'
        # T+1 结局
        pct1 = closes[t + 1] / closes[t] - 1
        key = (sg, dragon, pos)
        for k2 in (cells[key], dragon_cells[(dragon,)]):
            k2['n'] += 1
            k2['board'] += pct1 >= 0.098
            k2['red'] += pct1 > 0
            k2['up5'] += pct1 >= 0.05
            k2['dn5'] += pct1 <= -0.05
            k2['ret'] += pct1
    if i % 800 == 0: print(f'[{i}/{len(codes)}] events={total_events}', file=sys.stderr)

def fmt(cell):
    n = cell['n']
    if not n: return None
    return {'n': n, 'T1再板%': round(100 * cell['board'] / n, 1),
            'T1收红%': round(100 * cell['red'] / n, 1),
            'T1≥+5%%': round(100 * cell['up5'] / n, 1),
            'T1≤-5%%(大面)': round(100 * cell['dn5'] / n, 1),
            'T1均收%': round(100 * cell['ret'] / n, 2)}

out = {'total_events': total_events, 'universe': len(codes),
       'by_streak_dragon_pos': {f'{a}|{b}|{c2}': fmt(v) for (a, b, c2), v in sorted(cells.items()) if fmt(v)},
       'by_dragon': {k[0]: fmt(v) for k, v in dragon_cells.items() if fmt(v)}}
json.dump(out, open(ROOT / 'data/lianban_persistence_20260914.json', 'w'), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False, indent=1))
