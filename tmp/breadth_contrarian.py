"""反向指标聚合层（2026-09-29，tmp）：个股死信号的横截面聚合=市场温度？
每日全市场「均线多头排列」占比 / 「换手率>5%」占比 → 沪深300未来5/10/20日。
如果过热占比高位=未来负收益 → 反向指标成立（做空侧做不了，但可作减仓/暂停信号）。
"""
import glob
import json
import sqlite3
import statistics as st

idx_rows = json.load(open('/opt/data/fenjue/data/index_sh000001.json'))
idx = {r['date']: r['close'] for r in idx_rows}
idates = sorted(idx)

# 每日多头占比（big_kcache 全市场）
breadth = {}
for fp in glob.glob('/opt/data/fenjue/data/big_kcache/*.json'):
    code = fp.split('/')[-1].split('.')[0]
    if code[0] not in '06' or code.startswith(('300', '301', '688')):
        continue
    bars = json.load(open(fp))
    c = [b['close'] for b in bars]
    v = [b['volume'] for b in bars]
    for i in range(60, len(bars)):
        d = bars[i]['date']
        if d < '2019-06-01':
            continue
        m5 = sum(c[i - 4:i + 1]) / 5
        m10 = sum(c[i - 9:i + 1]) / 10
        m20 = sum(c[i - 19:i + 1]) / 20
        m60 = sum(c[i - 59:i + 1]) / 60
        b = breadth.setdefault(d, [0, 0, 0])
        b[0] += 1
        if m5 > m10 > m20 > m60:
            b[1] += 1
        if i >= 20 and v[i] > sum(v[i - 20:i]) / 20 * 2:  # 放量>2倍
            b[2] += 1

series = []
for d in idates:
    if d in breadth and breadth[d][0] > 1000:
        t, m, hv = breadth[d]
        series.append({'date': d, 'bull_pct': m / t, 'hivol_pct': hv / t})
print(f"温度序列 {len(series)} 日")

def fwd(d, k):
    i = idates.index(d)
    return idx[idates[i + k]] / idx[d] - 1 if i + k < len(idates) else None

for key, name in [('bull_pct', '多头排列占比'), ('hivol_pct', '放量>2倍占比')]:
    vals = sorted(s[key] for s in series)
    n = len(vals)
    print(f"\n== {name} 五分位 → 沪深300未来10日")
    bkts = [[] for _ in range(5)]
    for s in series[:-10]:
        r = fwd(s['date'], 10)
        if r is not None:
            q = min(4, sum(1 for v in vals if v < s[key]) * 5 // n)
            bkts[q].append(r)
    for i, b in enumerate(bkts):
        wr = sum(1 for x in b if x > 0) / len(b) * 100
        med = st.median(b) * 100
        tag = '最冷' if i == 0 else ('最热' if i == 4 else '')
        print(f"  Q{i+1}{tag}: n={len(b)} 胜率{wr:.0f}% 均值{st.mean(b)*100:+.2f}% 中位{med:+.2f}%")

# 当前读数
last = series[-1]
bp = sum(1 for s in series if s['bull_pct'] < last['bull_pct']) / len(series) * 100
print(f"\n当前({last['date']}): 多头占比 {last['bull_pct']*100:.1f}% (全史 {bp:.0f}% 分位)")
