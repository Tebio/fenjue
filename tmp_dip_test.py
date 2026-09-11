import json, glob, os, statistics as st

events = []
limit_up_days = 0
files = glob.glob('/opt/data/fenjue/data/big_kcache/*.json')
for fp in files:
    try:
        ks = json.load(open(fp))
    except Exception:
        continue
    if len(ks) < 10:
        continue
    closes = [float(k['close']) for k in ks]
    for i in range(2, len(ks)):
        cc1 = closes[i-1] / closes[i-2] - 1   # T-1 日涨幅
        cc0 = closes[i-2] / closes[i-3] - 1 if i >= 3 else 0  # T-2 日涨幅
        if cc1 >= 0.098:
            limit_up_days += 1
        if cc1 < 0.098 or cc0 < 0.098:
            continue  # 需要 T-2、T-1 连续两板
        today = ks[i]
        pc = closes[i-1]
        o, lo, hi, cl = float(today['open']), float(today['low']), float(today['high']), float(today['close'])
        dip_entry = pc * 0.97
        if lo <= dip_entry:  # 盘中触及水下 3%
            rec = {
                'date': today['date'],
                'dip_to_close': (cl / dip_entry - 1) * 100,
                'close_vs_prev': (cl / pc - 1) * 100,
                'still_limit_up': cl >= pc * 1.098,
                'next_cc': None,
            }
            if i + 1 < len(ks):
                rec['next_cc'] = (closes[i+1] / cl - 1) * 100
            events.append(rec)

print(f'全市场连板(≥2板)日总数: {limit_up_days}')
n = len(events)
print(f'连板后分歧日盘中触及-3%水下: n={n}')
if n:
    rets = [e['dip_to_close'] for e in events]
    wins = sum(1 for r in rets if r > 0)
    print(f'低吸(-3%挂单价)→当日尾盘: 胜率 {wins/n*100:.1f}%  均值 {st.mean(rets):+.2f}%  中位 {st.median(rets):+.2f}%')
    still = [e for e in events if e['still_limit_up']]
    print(f'当日深V回封板: {len(still)} ({len(still)/n*100:.1f}%)')
    dead = [e for e in events if e['close_vs_prev'] <= -5]
    print(f'当日收跌超-5%: {len(dead)} ({len(dead)/n*100:.1f}%)')
    nxts = [e['next_cc'] for e in events if e['next_cc'] is not None]
    wn = sum(1 for r in nxts if r > 0)
    print(f'低吸后持有到次日收盘: 胜率 {wn/len(nxts)*100:.1f}%  均值 {st.mean(nxts):+.2f}%')
    # 分年看稳定性
    from collections import defaultdict
    by_year = defaultdict(list)
    for e in events:
        by_year[e['date'][:4]].append(e['dip_to_close'])
    for y in sorted(by_year):
        r = by_year[y]
        print(f'  {y}: n={len(r)} 胜率{sum(1 for x in r if x>0)/len(r)*100:.0f}% 均值{st.mean(r):+.2f}%')
