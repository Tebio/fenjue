"""PEAD 高增轴终审（2026-09-29）：高增预告→次日开盘→T+20/T+60，位置匹配对照+分年。"""
import glob
import json
import random
import statistics as st

FEE = 0.0015
random.seed(7)
ev = json.load(open('/opt/data/fenjue/data/pead_events.json'))

events = []
for e in ev:
    t = str(e.get('FORECASTTYPE') or '')
    lo = e.get('INCREASEL')
    if t == '预增' and lo is not None and lo >= 50:
        events.append({'code': e['SECURITY_CODE'], 'date': e['NOTICE_DATE'][:10], 'kind': '预增≥50'})
    elif t == '扭亏':
        events.append({'code': e['SECURITY_CODE'], 'date': e['NOTICE_DATE'][:10], 'kind': '扭亏'})
print('高增事件', len(events))

bars_of = {}
for fp in glob.glob('/opt/data/fenjue/data/big_kcache/*.json'):
    code = fp.split('/')[-1].split('.')[0]
    if code[0] not in '06' or code.startswith(('300', '301', '688')):
        continue
    bars_of[code] = json.load(open(fp))

def pos_ma60(bars, i):
    if i < 60:
        return None
    ma = sum(b['close'] for b in bars[i - 60:i]) / 60
    return bars[i - 1]['close'] > ma

def fwd(bars, after_date, k):
    """after_date 之后首个交易日开盘买 → k 交易日后收盘。返回 (入场i, 收益)"""
    for i, b in enumerate(bars):
        if b['date'] > after_date and b['open'] > 0 and i + k < len(bars):
            return i, bars[i + k]['close'] / b['open'] - 1 - FEE
    return None, None

res = {'预增≥50': {20: [], 60: []}, '扭亏': {20: [], 60: []}}
ctrl = {20: [], 60: []}
yearly = {}
for e in events:
    bars = bars_of.get(e['code'])
    if not bars:
        continue
    for k in (20, 60):
        i, r = fwd(bars, e['date'], k)
        if r is None:
            continue
        res[e['kind']][k].append(r)
        yearly.setdefault((e['date'][:4], k), []).append(r)
        # 位置匹配对照：同票、同 MA60 位置、窗口不与事件窗重叠的随机日
        pos = pos_ma60(bars, i)
        cands = [j for j in range(65, len(bars) - k - 1)
                 if pos_ma60(bars, j) == pos and bars[j + 1]['open'] > 0
                 and not (i - k <= j <= i + k)]
        if cands:
            j = random.choice(cands)
            ctrl[k].append(bars[j + k]['close'] / bars[j + 1]['open'] - 1 - FEE)

for kind in res:
    for k in (20, 60):
        v = res[kind][k]
        if v:
            wr = sum(1 for x in v if x > 0) / len(v) * 100
            print(f"{kind} T+{k}: n={len(v)} 胜率{wr:.0f}% 均值{st.mean(v)*100:+.2f}%")
for k in (20, 60):
    c = ctrl[k]
    wr = sum(1 for x in c if x > 0) / len(c) * 100
    print(f"位置匹配对照 T+{k}: n={len(c)} 胜率{wr:.0f}% 均值{st.mean(c)*100:+.2f}%")
print('\n分年(高增全体 T+60):')
for (y, k) in sorted(yearly):
    if k != 60:
        continue
    v = yearly[(y, k)]
    wr = sum(1 for x in v if x > 0) / len(v) * 100
    print(f"  {y}: n={len(v)} 胜率{wr:.0f}% 均值{st.mean(v)*100:+.2f}%")
