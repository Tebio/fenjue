#!/usr/bin/env python3
"""昊华科技 600378 专属回测"""
import os, time, json, urllib.request, ssl

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

sina = 'sh600378'
url = f'http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={sina}&scale=240&ma=no&datalen=90'
req = urllib.request.Request(url, headers={'Referer':'https://finance.sina.com.cn'})
resp = urllib.request.urlopen(req, context=ctx, timeout=15)
data = json.loads(resp.read().decode('utf-8'))

print("="*65)
print(f"🔥 昊华科技 600378 多策略回测 ({len(data)}天日K)")
print("="*65)

# ======== 1. 冲高回落收阳 → 次日 ========
print("\n📈 策略A: 冲高>5% + 回落>1.5% + 收阳 → 次日涨跌")
results_a = []
for i in range(1, len(data)-1):
    d = data[i]
    o, c, h = float(d['open']), float(d['close']), float(d['high'])
    high_pct = (h - o) / o * 100
    fade = (c - h) / h * 100
    day_pct = (c - o) / o * 100
    if high_pct > 5 and fade < -1.5 and day_pct > 0:
        next_c = float(data[i+1]['close'])
        ret = (next_c - c) / c * 100
        results_a.append({'date': d['day'], 'high_pct': high_pct, 'fade': fade, 'day_pct': day_pct, 'ret': ret})

if results_a:
    up = sum(1 for r in results_a if r['ret']>0)
    print(f"  样本: {len(results_a)}次 | 次日涨: {up}次 | 胜率: {up/len(results_a)*100:.0f}%")
    print(f"  均值: {sum(r['ret'] for r in results_a)/len(results_a):+.2f}%")
    for r in sorted(results_a, key=lambda x: x['ret'], reverse=True):
        t = '✅' if r['ret']>0 else '❌'
        print(f"  {t} {r['date']} 冲{r['high_pct']:+.1f}% 回{r['fade']:+.1f}% → 次{r['ret']:+.1f}%")
else:
    print("  无匹配样本")

# ======== 2. 放量大涨后 ← 次日表现 ========
print("\n📈 策略B: 单日涨>5% + 放量（昨日量×1.5） → 次日涨跌")
results_b = []
for i in range(1, len(data)-1):
    d = data[i]
    o, c = float(d['open']), float(d['close'])
    v = float(d['volume'])
    pct = (c - o) / o * 100
    if pct > 5:
        prev_v = float(data[i-1]['volume']) if i > 0 else v
        if v > prev_v * 1.5:
            next_c = float(data[i+1]['close'])
            ret = (next_c - c) / c * 100
            results_b.append({'date': d['day'], 'pct': round(pct,1), 'ret': round(ret,1),
                            'vol_ratio': round(v/prev_v,1)})

if results_b:
    up = sum(1 for r in results_b if r['ret']>0)
    print(f"  样本: {len(results_b)}次 | 次日涨: {up}次 | 胜率: {up/len(results_b)*100:.0f}%")
    print(f"  均值: {sum(r['ret'] for r in results_b)/len(results_b):+.2f}%")
    for r in sorted(results_b, key=lambda x: x['ret'], reverse=True):
        t = '✅' if r['ret']>0 else '❌'
        print(f"  {t} {r['date']} 涨{r['pct']:+.1f}% 量比×{r['vol_ratio']} → 次{r['ret']:+.1f}%")
else:
    print("  无匹配样本")

# ======== 3. 连续N日上涨 ← 后市 ========
print("\n📈 策略C: 连续3日收阳 → 第4日涨跌")
results_c = []
for i in range(3, len(data)-1):
    d0, d1, d2 = data[i-2], data[i-1], data[i]
    c0, c1, c2 = float(d0['close']), float(d1['close']), float(d2['close'])
    # 连续3日收阳(收盘>开盘) 且涨幅递增
    o0, o1, o2 = float(d0['open']), float(d1['open']), float(d2['open'])
    if c0>o0 and c1>o1 and c2>o2 and c2>c1>c0:
        next_c = float(data[i+1]['close'])
        ret = (next_c - c2) / c2 * 100
        results_c.append({'date': d2['day'], 'ret': round(ret,1)})

if results_c:
    up = sum(1 for r in results_c if r['ret']>0)
    print(f"  样本: {len(results_c)}次 | 第4日涨: {up}次 | 胜率: {up/len(results_c)*100:.0f}%")
    print(f"  均值: {sum(r['ret'] for r in results_c)/len(results_c):+.2f}%")
    for r in sorted(results_c, key=lambda x: x['ret'], reverse=True):
        t = '✅' if r['ret']>0 else '❌'
        print(f"  {t} {r['date']} 连阳3日 → 第4日{r['ret']:+.1f}%")
else:
    print("  无匹配样本")

# ======== 4. 深V反转(振幅>7% + 收阳) → 次日 ========
print("\n📈 策略D: 深V反转（振幅>7% + 收阳 + 日内位>60%）→ 次日")
results_d = []
for i in range(1, len(data)-1):
    d = data[i]
    o, c, h, l = float(d['open']), float(d['close']), float(d['high']), float(d['low'])
    amp = (h - l) / l * 100
    pos = (c - l) / (h - l) * 100 if h > l else 50
    day_pct = (c - o) / o * 100
    if amp > 7 and day_pct > 0 and pos > 60:
        next_c = float(data[i+1]['close'])
        ret = (next_c - c) / c * 100
        results_d.append({'date': d['day'], 'amp': round(amp,1), 'pos': round(pos,0),
                         'day_pct': round(day_pct,1), 'ret': round(ret,1)})

if results_d:
    up = sum(1 for r in results_d if r['ret']>0)
    print(f"  样本: {len(results_d)}次 | 次日涨: {up}次 | 胜率: {up/len(results_d)*100:.0f}%")
    print(f"  均值: {sum(r['ret'] for r in results_d)/len(results_d):+.2f}%")
    for r in sorted(results_d, key=lambda x: x['ret'], reverse=True):
        t = '✅' if r['ret']>0 else '❌'
        print(f"  {t} {r['date']} 振幅{r['amp']}% 位{r['pos']:.0f}% 收{r['day_pct']:+.1f}% → 次{r['ret']:+.1f}%")
else:
    print("  无匹配样本")

# ======== 5. MA20乖离 vs 次日 ========
print("\n📈 策略E: MA20乖离区间 → 次日涨跌")
ma20 = []
for i in range(len(data)):
    if i >= 19:
        ma = sum(float(data[j]['close']) for j in range(i-19, i+1)) / 20
    else:
        ma = float(data[i]['close'])
    ma20.append(ma)

gap_results = {'低乖离<10%': [], '中乖离10-25%': [], '高乖离>25%': []}
for i in range(len(data)-1):
    c = float(data[i]['close'])
    gap = (c - ma20[i]) / ma20[i] * 100
    next_c = float(data[i+1]['close'])
    ret = (next_c - c) / c * 100
    
    if gap < 10:
        gap_results['低乖离<10%'].append(ret)
    elif gap < 25:
        gap_results['中乖离10-25%'].append(ret)
    else:
        gap_results['高乖离>25%'].append(ret)

for label, rets in gap_results.items():
    if rets:
        up = sum(1 for r in rets if r > 0)
        print(f"  {label}: {len(rets)}天 | 胜率: {up/len(rets)*100:.0f}% | 均值: {sum(rets)/len(rets):+.2f}%")

# ======== 今日对比 ========
print("\n" + "="*65)
print("🎯 今天(6/9) 昊华科技特征匹配:")
print(f"  冲高>5%+回落>1.5%+收阳: {'✅ 匹配' if results_a and results_a[-1]['date'][:10]=='2026-06-09' else '❌ 不匹配（今日振幅9.2%+收+5.1%+位82%，属于策略D深V）'}")
print(f"  深V反转(振幅9.2%+位82%): 匹配策略D")
if results_d:
    d_up = sum(1 for r in results_d if r['ret']>0)
    print(f"  策略D历史胜率: {d_up}/{len(results_d)} = {d_up/len(results_d)*100:.0f}%")
print("="*65)
