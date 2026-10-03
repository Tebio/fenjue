"""民间战法普查第二锅（2026-09-29，tmp 探索级）：缺口/红三兵/三只乌鸦/断头铡刀/均线多头/双底/整数关口/MA金死叉。
口径：主板，前复权，信号日收盘已知→次日开盘买，净-0.15%；对照=全部股票日同口径。
"""
import glob
import json
import statistics as st

FEE = 0.0015
R = {k: {'t1': [], 't5': []} for k in
     ['跳空上≥2%', '跳空下≥2%', '红三兵', '三只乌鸦', '断头铡刀', '均线多头',
      '双底缩量', '整数关口下方', '整数关口上方', 'MA金叉', 'MA死叉', 'base']}
ROUNDS = (5, 10, 20, 50, 100)

def ma(c, i, n):
    return sum(c[i - n + 1:i + 1]) / n

for fp in glob.glob('/opt/data/fenjue/data/big_kcache/*.json'):
    code = fp.split('/')[-1].split('.')[0]
    if code[0] not in '06' or code.startswith(('300', '301', '688')):
        continue
    bars = json.load(open(fp))
    if len(bars) < 70:
        continue
    c = [b['close'] for b in bars]
    o = [b['open'] for b in bars]
    h = [b['high'] for b in bars]
    l = [b['low'] for b in bars]
    v = [b['volume'] for b in bars]
    for i in range(65, len(bars) - 6):
        if c[i] <= 0 or o[i + 1] <= 0:
            continue
        t1 = c[i + 1] / o[i + 1] - 1 - FEE
        t5 = c[i + 5] / o[i + 1] - 1 - FEE
        R['base']['t1'].append(t1); R['base']['t5'].append(t5)
        pc, po, ph, pl = c[i - 1], o[i - 1], h[i - 1], l[i - 1]
        # 缺口（当日开 vs 昨日高/低）
        if o[i] > ph * 1.02:
            R['跳空上≥2%']['t1'].append(t1); R['跳空上≥2%']['t5'].append(t5)
        if o[i] < pl * 0.98:
            R['跳空下≥2%']['t1'].append(t1); R['跳空下≥2%']['t5'].append(t5)
        # 红三兵/三只乌鸦（三连同向，累计3~10%）
        if c[i] > c[i - 1] > c[i - 2] > c[i - 3] and 1.03 <= c[i] / c[i - 3] <= 1.10:
            R['红三兵']['t1'].append(t1); R['红三兵']['t5'].append(t5)
        if c[i] < c[i - 1] < c[i - 2] < c[i - 3] and 0.90 <= c[i] / c[i - 3] <= 0.97:
            R['三只乌鸦']['t1'].append(t1); R['三只乌鸦']['t5'].append(t5)
        # 断头铡刀：昨收在三线之上，今收跌破 MA5/10/20 且跌≥3%
        m5, m10, m20 = ma(c, i, 5), ma(c, i, 10), ma(c, i, 20)
        if pc > ma(c, i - 1, 5) and pc > ma(c, i - 1, 10) and pc > ma(c, i - 1, 20) \
                and c[i] < m5 and c[i] < m10 and c[i] < m20 and c[i] / pc - 1 <= -0.03:
            R['断头铡刀']['t1'].append(t1); R['断头铡刀']['t5'].append(t5)
        # 均线多头排列
        if m5 > m10 > m20 > ma(c, i, 60) and c[i] > m5:
            R['均线多头']['t1'].append(t1); R['均线多头']['t5'].append(t5)
        # 双底缩量：今低与10~20日前低点±2%内，量缩，收阳
        for j in range(i - 20, i - 9):
            if abs(l[i] - l[j]) / l[j] <= 0.02 and v[i] < v[j] and c[i] > o[i] and l[j] == min(l[j - 5:j + 6]):
                R['双底缩量']['t1'].append(t1); R['双底缩量']['t5'].append(t5)
                break
        # 整数关口：收在整数±2%带
        for rd in ROUNDS:
            if rd * 0.98 <= c[i] < rd:
                R['整数关口下方']['t1'].append(t1); R['整数关口下方']['t5'].append(t5)
                break
            if rd <= c[i] < rd * 1.02:
                R['整数关口上方']['t1'].append(t1); R['整数关口上方']['t5'].append(t5)
                break
        # MA金死叉（MA5×MA20）
        if m5 > m20 and ma(c, i - 1, 5) <= ma(c, i - 1, 20):
            R['MA金叉']['t1'].append(t1); R['MA金叉']['t5'].append(t5)
        if m5 < m20 and ma(c, i - 1, 5) >= ma(c, i - 1, 20):
            R['MA死叉']['t1'].append(t1); R['MA死叉']['t5'].append(t5)

b1 = st.mean(R['base']['t1']) * 100
b5 = st.mean(R['base']['t5']) * 100
w1 = sum(1 for x in R['base']['t1'] if x > 0) / len(R['base']['t1']) * 100
w5 = sum(1 for x in R['base']['t5'] if x > 0) / len(R['base']['t5']) * 100
print(f"基线: T+1 {w1:.1f}%/{b1:+.3f}%  T+5 {w5:.1f}%/{b5:+.3f}%  (n={len(R['base']['t1'])})")
print(f"{'战法':<12} {'n':>9} {'T1胜率':>7} {'T1均笔':>8} {'T5胜率':>7} {'T5均笔':>8}")
for k in R:
    if k == 'base':
        continue
    d = R[k]
    if len(d['t1']) < 500:
        print(f"{k:<12} {len(d['t1']):>9}  (样本<500 不评)")
        continue
    x1 = sum(1 for x in d['t1'] if x > 0) / len(d['t1']) * 100
    x5 = sum(1 for x in d['t5'] if x > 0) / len(d['t5']) * 100
    print(f"{k:<12} {len(d['t1']):>9} {x1:>6.1f}% {st.mean(d['t1'])*100:>+7.3f}% {x5:>6.1f}% {st.mean(d['t5'])*100:>+7.3f}%")
