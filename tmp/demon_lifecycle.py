"""妖股全生命周期研究（612 妖 2019→2026/9）。
妖定义=demon_anatomy 口径（25日内曾涨至1.8x的首板事件）。
三问：
 进：第1/2/3/4板收盘上车，后续收益分布（fill 警示另注）
 出：哪些特征预示「明天是顶」——量比/上影/断板/板块梯队崩
 二次拉升：首次断魂刀（≤-8%或跌停）后 10 日内再板/新高概率与条件
"""
import sys, json, statistics as st
from collections import defaultdict, Counter
sys.path.insert(0, 'engine')
import law_pipeline as lp

stocks = lp.load_universe()
lp.build_xsection(stocks)
regime = lp.load_regime()
mmap = json.load(open('data/industry_map.json'))
code2ind = {str(k).zfill(6): v['industry'] for k, v in mmap.items() if isinstance(v, dict) and v.get('industry')}
capd = {f.stem: json.loads(f.read_text()) for f in []}  # 市值用 lp.cap_at_date 口径略（速度优先略）

# ── 找妖事件（复刻 demon 口径：60日无板后首板，25日内曾 1.8x）──
events = []
for code, d in stocks.items():
    c, n = d['c'], d['n']
    last_board = -999
    for i in range(lp.START, n - 26):
        if c[i] / c[i - 1] - 1 >= 0.098:
            if i - last_board >= 60:
                # 首板事件；是否成妖
                if max(c[i + 1:i + 26]) / c[i] >= 1.8:
                    events.append({'code': code, 'i': i})
                last_board = i
            else:
                last_board = i
print(f'妖事件 {len(events)}')

# 预计算：行业→日→涨停数（O(全市场) 一次，避免内层循环）
sec_board = defaultdict(lambda: defaultdict(int))
for code, d in stocks.items():
    ind = code2ind.get(code)
    if not ind:
        continue
    c = d['c']
    for i in range(1, d['n']):
        if c[i] / c[i - 1] - 1 >= 0.098:
            sec_board[ind][d['date'][i]] += 1

# ── 逐妖生命周期提取 ──
entry_at = defaultdict(list)   # k板 -> [(fwd_T1, fwd_T3, fwd_max)]
top_feat = {'量比高': [0, 0], '量比低': [0, 0], '长上影': [0, 0], '短上影': [0, 0],
            '梯队崩': [0, 0], '梯队活': [0, 0]}   # [顶, 非顶]
second = defaultdict(list)     # 条件 -> [10日内再板? 1/0]
second_ret = defaultdict(list)

for ev in events:
    d = stocks[ev['code']]
    c, h, l, o, v = d['c'], d['h'], d['l'], d['o'], d['v']
    n = d['n']
    i0 = ev['i']
    ind = code2ind.get(ev['code'], '')
    # 连板序列
    boards = [i0]
    j = i0 + 1
    while j < n and c[j] / c[j - 1] - 1 >= 0.098:
        boards.append(j)
        j += 1
    chain_peak_i = boards[-1]
    for extra in range(boards[-1] + 1, min(n, boards[-1] + 15)):
        if c[extra] > c[chain_peak_i]:
            chain_peak_i = extra
    # 进：第 k 板收盘上车
    for k, bi in enumerate(boards[:4], 1):
        if bi + 1 >= n:
            continue
        ep = c[bi]
        r1 = c[bi + 1] / ep - 1 if bi + 1 < n else None
        r3 = c[min(bi + 3, n - 1)] / ep - 1
        rmax = max(c[bi + 1:min(n, bi + 21)]) / ep - 1 if bi + 1 < n else 0
        entry_at[k].append((r1, r3, rmax))
    # 出：链中每日特征 vs 次日是否见顶（峰前3日内）
    for bi in boards:
        if bi >= chain_peak_i or bi + 1 >= n:
            continue
        is_top_next = (bi + 1 >= chain_peak_i - 1)
        vols = [v[x] for x in range(max(1, bi - 5), bi)]
        vr = v[bi] / (sum(vols) / len(vols)) if vols and sum(vols) > 0 else 1
        upper = (h[bi] - c[bi]) / (h[bi] - l[bi]) if h[bi] > l[bi] else 0
        # 板块梯队：当日同行业涨停数（预计算表）
        nbd = sec_board[ind].get(d['date'][bi], 0) if ind else 0
        top_feat['量比高' if vr >= 2 else '量比低'][is_top_next] += 1
        top_feat['长上影' if upper >= 0.5 else '短上影'][is_top_next] += 1
        top_feat['梯队崩' if nbd <= 1 else '梯队活'][is_top_next] += 1
    # 二次拉升：链后首个 ≤-8% 日
    k0 = boards[-1] + 1
    knife = None
    for j in range(k0, min(n, k0 + 10)):
        if c[j] / c[j - 1] - 1 <= -0.08:
            knife = j
            break
    if knife and knife + 2 < n:
        vols_chain = [v[x] for x in boards]
        shrink = v[knife] < (sum(vols_chain) / len(vols_chain)) if vols_chain else False
        # 断魂日板块梯队（预计算表）
        dt_k = d['date'][knife]
        nbd_k = sec_board[ind].get(dt_k, 0) if ind else 0
        rg = regime.get(dt_k, '?')
        long_chain = len(boards) >= 4
        reboard = any(c[j] / c[j - 1] - 1 >= 0.098 for j in range(knife + 1, min(n, knife + 11)))
        newhi = max(c[knife + 1:min(n, knife + 11)]) > c[chain_peak_i] if knife + 1 < n else False
        r10 = c[min(n - 1, knife + 10)] / c[knife] - 1
        for key, val in (('缩量刀', shrink), ('放量刀', not shrink),
                         ('梯队活(≥2板)', nbd_k >= 2), ('梯队崩(<2板)', nbd_k < 2),
                         ('长链≥4板', long_chain), ('短链2-3板', not long_chain),
                         (rg, True)):
            if val:
                second[key].append(1 if reboard else 0)
                second_ret[key].append(r10)

print(f'\n== 进：第 k 板收盘上车（n={len(events)}，fill 警示：封死板买不进，实际为排队成交口径）==')
for k in sorted(entry_at):
    rows = entry_at[k]
    r1 = [x[0] for x in rows if x[0] is not None]
    r3 = [x[1] for x in rows]
    rmax = [x[2] for x in rows]
    print(f'第{k}板(n={len(rows)}): T+1 {100*st.mean(r1):+.2f}%/{100*sum(1 for x in r1 if x>0)/len(r1):.0f}% | '
          f'T+3 {100*st.mean(r3):+.2f}% | 后续最大 {100*st.mean(rmax):+.2f}%')

print('\n== 出：特征 vs 次日见顶概率 ==')
for key, (top, notop) in top_feat.items():
    tot = top + notop
    if tot:
        print(f'{key}: 见顶率 {100*top/tot:.0f}% (n={tot})')

print('\n== 二次拉升：断魂刀后 10 日 ==')
for key in ('缩量刀', '放量刀', '梯队活(≥2板)', '梯队崩(<2板)', '长链≥4板', '短链2-3板',
            '妖股期', '恐慌期', '平淡期', '主线期'):
    v = second.get(key, [])
    r = second_ret.get(key, [])
    if len(v) >= 15:
        print(f'{key}: 再板率 {100*sum(v)/len(v):.0f}% | 刀后10日均 {100*st.mean(r):+.2f}% (n={len(v)})')