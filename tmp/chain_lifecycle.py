"""连板链全样本生命周期（全部首板事件 2019→2026/9，不只看妖）。
修正三处：①进=全部首板事件口径（含不成妖的 97.5%）②出=特征对链延续的区分度（修分母）
③二次拉升=全部≥2板链（不只看 1.8x 妖）
"""
import sys, json, statistics as st
from collections import defaultdict
sys.path.insert(0, 'engine')
import law_pipeline as lp

stocks = lp.load_universe()
lp.build_xsection(stocks)
regime = lp.load_regime()
mmap = json.load(open('data/industry_map.json'))
code2ind = {str(k).zfill(6): v['industry'] for k, v in mmap.items() if isinstance(v, dict) and v.get('industry')}

# 行业→日→涨停数
sec_board = defaultdict(lambda: defaultdict(int))
for code, d in stocks.items():
    ind = code2ind.get(code)
    if not ind:
        continue
    c = d['c']
    for i in range(1, d['n']):
        if c[i] / c[i - 1] - 1 >= 0.098:
            sec_board[ind][d['date'][i]] += 1

# 全部首板事件（60日无板后首板）+ 连板链
chains = []
for code, d in stocks.items():
    c, n = d['c'], d['n']
    last_board = -999
    i = lp.START
    while i < n - 2:
        if c[i] / c[i - 1] - 1 >= 0.098:
            if i - last_board >= 60:
                boards = [i]
                j = i + 1
                while j < n and c[j] / c[j - 1] - 1 >= 0.098:
                    boards.append(j)
                    j += 1
                chains.append({'code': code, 'boards': boards})
                last_board = boards[-1]
                i = boards[-1] + 1
                continue
            last_board = i
        i += 1
print(f'首板事件 {len(chains)}，其中≥2板链 {sum(1 for c in chains if len(c["boards"]) >= 2)}')

# ── ① 进：首板收盘上车（全样本）──
r1s, r3s, r5s = [], [], []
for ch in chains:
    d = stocks[ch['code']]
    c, n = d['c'], d['n']
    b0 = ch['boards'][0]
    if b0 + 5 >= n:
        continue
    ep = c[b0]
    r1s.append(c[b0 + 1] / ep - 1)
    r3s.append(c[b0 + 3] / ep - 1)
    r5s.append(c[b0 + 5] / ep - 1)
print(f'\n== ① 首板收盘上车（全样本 n={len(r1s)}，排队成交口径）==')
for nm, v in (('T+1', r1s), ('T+3', r3s), ('T+5', r5s)):
    w = sum(1 for x in v if x > 0)
    print(f'{nm}: {100*st.mean(v):+.2f}% / 胜率{100*w/len(v):.0f}%')

# ── ② 出：板日特征 vs 链在2日内死亡（修分母：只看非末板的板日）──
feat_stats = defaultdict(lambda: [0, 0])   # key -> [死, 活]
for ch in chains:
    boards = ch['boards']
    if len(boards) < 2:
        continue
    d = stocks[ch['code']]
    c, h, l, v, n = d['c'], d['h'], d['l'], d['v'], d['n']
    ind = code2ind.get(ch['code'], '')
    peak_i = boards[-1]
    for extra in range(boards[-1] + 1, min(n, boards[-1] + 10)):
        if c[extra] > c[peak_i]:
            peak_i = extra
    for bi in boards[:-1]:
        vols = [v[x] for x in range(max(1, bi - 5), bi)]
        vr = v[bi] / (sum(vols) / len(vols)) if vols and sum(vols) > 0 else 1
        upper = (h[bi] - c[bi]) / (h[bi] - l[bi]) if h[bi] > l[bi] else 0
        nbd = sec_board[ind].get(d['date'][bi], 0) if ind else 0
        die = (peak_i - bi) <= 2   # 2日内链死
        for key, cond in (('量比≥2', vr >= 2), ('量比<2', vr < 2),
                          ('上影≥50%', upper >= 0.5), ('上影<50%', upper < 0.5),
                          ('梯队≥3板', nbd >= 3), ('梯队<3板', nbd < 3)):
            if cond:
                feat_stats[key][0 if die else 1] += 1
print('\n== ② 板日特征 vs 2日内链死率（区分度）==')
for key, (die, alive) in feat_stats.items():
    tot = die + alive
    if tot > 30:
        print(f'{key}: 链死率 {100*die/tot:.0f}% (n={tot})')

# ── ③ 二次拉升：全部≥2板链的断魂刀 ──
sec_stats = defaultdict(lambda: {'n': 0, 'reboard': 0, 'rets': []})
for ch in chains:
    boards = ch['boards']
    if len(boards) < 2:
        continue
    d = stocks[ch['code']]
    c, v, n = d['c'], d['v'], d['n']
    ind = code2ind.get(ch['code'], '')
    peak_i = boards[-1]
    for extra in range(boards[-1] + 1, min(n, boards[-1] + 10)):
        if c[extra] > c[peak_i]:
            peak_i = extra
    knife = None
    for j in range(peak_i + 1, min(n, peak_i + 10)):
        if c[j] / c[j - 1] - 1 <= -0.08:
            knife = j
            break
    if not knife or knife + 2 >= n:
        continue
    dt_k = d['date'][knife]
    vols_chain = [v[x] for x in boards]
    shrink = v[knife] < (sum(vols_chain) / len(vols_chain)) if vols_chain else False
    nbd_k = sec_board[ind].get(dt_k, 0) if ind else 0
    rg = regime.get(dt_k, '?')
    reboard = any(c[j] / c[j - 1] - 1 >= 0.098 for j in range(knife + 1, min(n, knife + 11)))
    newhi = max(c[knife + 1:min(n, knife + 11)]) > c[peak_i] if knife + 1 < n else False
    r10 = c[min(n - 1, knife + 10)] / c[knife] - 1
    keys = {'链2-3板': len(boards) <= 3, '链≥4板': len(boards) >= 4,
            '缩量刀': shrink, '放量刀': not shrink,
            '梯队活(≥2板)': nbd_k >= 2, '梯队崩(<2板)': nbd_k < 2,
            '妖股期': rg == '妖股期', '恐慌期': rg == '恐慌期', '平淡期': rg == '平淡期'}
    for key, cond in keys.items():
        if cond:
            s = sec_stats[key]
            s['n'] += 1
            s['reboard'] += 1 if reboard else 0
            s['rets'].append(r10)
    sec_stats['全部']['n'] += 1
    sec_stats['全部']['reboard'] += 1 if reboard else 0
    sec_stats['全部']['rets'].append(r10)
print('\n== ③ 断魂刀后 10 日（全部≥2板链）==')
for key in ('全部', '链2-3板', '链≥4板', '缩量刀', '放量刀', '梯队活(≥2板)', '梯队崩(<2板)',
            '妖股期', '恐慌期', '平淡期'):
    s = sec_stats.get(key)
    if s and s['n'] >= 15:
        print(f"{key}: 再板率 {100*s['reboard']/s['n']:.0f}% | 刀后10日均 {100*st.mean(s['rets']):+.2f}% (n={s['n']})")