"""#79 双高格扫描：策略×位置×月份 / 策略×位置×regime
双高 = 胜率≥55% 且 盈亏比≥2（且超额>0, n≥200）
"""
import json
from pathlib import Path
from collections import defaultdict

ROOT = Path('/opt/data/fenjue')
KC = ROOT / 'data/big_kcache'
paths = [p for p in KC.glob('*.json') if p.stem[:2] in ('60', '00')]
FEE = 0.0015

reg_tl = json.load(open(ROOT / 'data/regime_timeline_hcap.json'))
reg_of = {e['date']: e['regime'] for e in reg_tl} if isinstance(reg_tl, list) else reg_tl

day_uni = defaultdict(lambda: [0, 0.0])
events = []  # (strategy, date, month, regime, pos, r)
for fp in paths:
    try: ks = json.load(open(str(fp)))
    except Exception: continue
    for t in range(61, len(ks) - 1):
        prev = ks[t-1]['close']
        if prev <= 0 or ks[t+1]['open'] <= 0: continue
        d = ks[t]['date']
        r = ks[t+1]['close'] / ks[t+1]['open'] - 1 - FEE
        day_uni[d][0] += 1; day_uni[d][1] += r
        pct1 = ks[t]['close'] / prev - 1
        ma60 = sum(k['close'] for k in ks[t-59:t+1]) / 60
        pos = '下' if ks[t]['close'] < ma60 else '上'
        rg = reg_of.get(d, '?')
        mm = d[5:7]
        if pct1 <= -0.03: events.append(('反转', d, mm, rg, pos, r))
        if pct1 <= -0.098: events.append(('跌停接', d, mm, rg, pos, r))

def agg(keyfn, label):
    G = defaultdict(list)
    for name, d, mm, rg, pos, r in events:
        G[keyfn(name, mm, rg, pos)].append((r, d))
    print(f'\n=== {label}（双高=胜率≥55%且盈亏比≥2且超额>0）===')
    print(f'{"格子":28s}{"n":>7s}{"胜率":>7s}{"盈亏比":>7s}{"均笔":>8s}{"超额":>8s}  判决')
    hits = []
    for k in sorted(G):
        rs = G[k]
        if len(rs) < 200: continue
        n = len(rs)
        win = sum(1 for r, _ in rs if r > 0) / n * 100
        aw = [r for r, _ in rs if r > 0]; al = [r for r, _ in rs if r <= 0]
        payoff = (sum(aw) / len(aw)) / abs(sum(al) / len(al)) if aw and al else 0
        mean = sum(r for r, _ in rs) / n * 100
        # 同日beta
        ub = sum(day_uni[d][1] / day_uni[d][0] for _, d in rs) / n * 100
        exc = mean - ub
        ok = win >= 55 and payoff >= 2 and exc > 0
        tag = '🏆双高' if ok else ''
        if ok: hits.append((k, n, win, payoff, mean, exc))
        print(f'{str(k):28s}{n:>7d}{win:>6.1f}%{payoff:>7.2f}{mean:>+7.2f}%{exc:>+7.2f}%  {tag}')
    return hits

h1 = agg(lambda n, m, r, p: f'{n}|MA60{p}|{m}月', '策略×位置×月份')
h2 = agg(lambda n, m, r, p: f'{n}|MA60{p}|{r}', '策略×位置×regime')
print(f'\n双高格(月维度): {[h[0] for h in h1]}')
print(f'双高格(regime维度): {[h[0] for h in h2]}')
