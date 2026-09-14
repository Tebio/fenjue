"""#80⑥ 反T补测：高股息锚股 2年 m60，先卖后买（镜像 #36 正T口径）
规则：开盘持仓 → 冲高 +S% 卖出 → 回落 -B% 接回；卖不出/接不回的收尾规则同 #36：
  未触发卖=当日不操作(0)；卖了接不回=尾盘收盘价接回（这是反T的亏损源：被迫高位/尾盘接）
  同bar双触=保守不成交。费用 0.1%/往返（同 #36）。
"""
import json
from pathlib import Path
from collections import defaultdict

KC = Path('/opt/data/fenjue/data/m60_cache')
STOCKS = {'601838': '成都银行', '600919': '江苏银行', '601229': '上海银行',
          '601077': '渝农商行', '600926': '杭州银行', '000333': '美的集团'}
FEE = 0.001  # 往返

def sim_day(bars, S, B):
    """bars: 当日m60 bar列表（时间序）。返回当日反T净收益(相对持仓不动)"""
    if len(bars) < 2:
        return 0.0
    base = float(bars[0]['open'])
    sold = None
    for bar in bars:
        hi, lo, cl = float(bar['high']), float(bar['low']), float(bar['close'])
        if sold is None:
            if hi >= base * (1 + S):
                if lo <= base * (1 + S) and lo <= base * (1 - B):
                    return 0.0  # 同bar双触=不成交（保守）
                sold = base * (1 + S)
        else:
            if lo <= sold * (1 - B):
                if hi >= sold * (1 - B) and hi >= sold * (1 + 0.005):
                    pass
                gain = (sold - sold * (1 - B)) / base - FEE
                return gain
    if sold is not None:
        # 接不回：尾盘收盘接回（反T亏损源）
        gain = (sold - float(bars[-1]['close'])) / base - FEE
        return gain
    return 0.0

# 按日切 bar
def days_of(code):
    ks = json.load(open(KC / f'{code}.json'))
    by = defaultdict(list)
    for k in ks:
        by[k['day'][:10]].append(k)
    return by

print(f'{"规则":16s}' + ''.join(f'{nm:>9s}' for nm in STOCKS.values()) + f'{"组合均值":>10s}')
for S, B in [(0.01, 0.005), (0.01, 0.01), (0.015, 0.01), (0.015, 0.015), (0.02, 0.01), (0.02, 0.02)]:
    row = f'卖+{S*100:.1f}/接-{B*100:.1f} '
    all_g = []
    for code in STOCKS:
        by = days_of(code)
        gs = [sim_day(bars, S, B) for bars in by.values()]
        g = sum(gs) / len(gs) * 100 if gs else 0
        all_g.append(g)
        row += f'{g:>+8.3f}%'
    row += f'{sum(all_g)/len(all_g):>+9.3f}%'
    print(row)
print('\n（读法：相对"持仓不动"的日超额。正=反T增利，负=磨损。#36正T口径为-0.06~-0.20%）')
