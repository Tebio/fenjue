"""#80③ 中继管理实测：浮盈≥10%后，移动止损 vs 梯度减仓 vs 死拿
事件：10日内涨幅≥10%（浮盈状态达成日T0）。
规则臂：
  A 死拿到 T+20
  B 回撤5%即走（自T0后最高价回撤5%，之后不再进场）
  C 回撤10%即走
  D 破MA10即走（减仓梯度代理）
口径：T0收盘为成本基准，净-0.15%每笔（B/C/D只收一次）
"""
import json
from pathlib import Path
from collections import defaultdict

KC = Path('/opt/data/fenjue/data/big_kcache')
paths = [p for p in KC.glob('*.json') if p.stem[:2] in ('60', '00')]
FEE = 0.0015

G = defaultdict(list)
for fp in paths:
    try: ks = json.load(open(str(fp)))
    except Exception: continue
    c = [k['close'] for k in ks]
    h = [k['high'] for k in ks]
    for t in range(70, len(ks) - 25):
        if c[t-11] <= 0: continue
        if c[t] / c[t-11] - 1 < 0.10: continue  # 10日+10%浮盈态
        base = c[t]
        # A: 死拿T+20
        rA = c[t+20] / base - 1 - FEE
        # B/C: 移动止损
        rB = rC = rD = None
        peak = base
        ma10w = sum(c[max(0, t-9):t+1]) / 10
        for u in range(t+1, t+21):
            peak = max(peak, h[u])
            if rB is None and c[u] / peak - 1 <= -0.05: rB = c[u] / base - 1 - FEE
            if rC is None and c[u] / peak - 1 <= -0.10: rC = c[u] / base - 1 - FEE
            ma10w = sum(c[u-9:u+1]) / 10 if u >= 9 else ma10w
            if rD is None and c[u] < ma10w: rD = c[u] / base - 1 - FEE
        rB = rB if rB is not None else c[t+20] / base - 1 - FEE
        rC = rC if rC is not None else c[t+20] / base - 1 - FEE
        rD = rD if rD is not None else c[t+20] / base - 1 - FEE
        G['A 死拿T+20'].append(rA)
        G['B 回撤5%走'].append(rB)
        G['C 回撤10%走'].append(rC)
        G['D 破MA10走'].append(rD)

print(f'{"规则臂":16s}{"n":>8s}{"胜率":>8s}{"均收益":>9s}{"中位":>8s}')
for k, v in G.items():
    v2 = sorted(v)
    n = len(v2)
    win = sum(1 for r in v2 if r > 0) / n * 100
    mean = sum(v2) / n * 100
    med = v2[n//2] * 100
    print(f'{k:16s}{n:>8d}{win:>7.1f}%{mean:>+8.2f}%{med:>+7.2f}%')
