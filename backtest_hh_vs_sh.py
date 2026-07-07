#!/usr/bin/env python3
"""昊华科技 vs 上证指数 2026年表现对比"""
import json, urllib.request, ssl, time

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

# 拉昊华日K
def get_daily(symbol):
    url = f'http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={symbol}&scale=240&ma=no&datalen=200'
    req = urllib.request.Request(url, headers={'Referer':'https://finance.sina.com.cn'})
    resp = urllib.request.urlopen(req, context=ctx, timeout=15)
    return json.loads(resp.read().decode('utf-8'))

print("拉取昊华 + 上证日K...")
haohua = get_daily('sh600378')
sh = get_daily('sh000001')

# Build maps
hh_close = {d['day']: float(d['close']) for d in haohua}
sh_close = {d['day']: float(d['close']) for d in sh}

common_dates = sorted(set(hh_close.keys()) & set(sh_close.keys()))
# Only 2026
common_dates = [d for d in common_dates if d >= '2026-01-01']

# Calculate daily returns
results = []
for i in range(1, len(common_dates)):
    d = common_dates[i]
    prev_d = common_dates[i-1]
    hh_ret = (hh_close[d] - hh_close[prev_d]) / hh_close[prev_d] * 100
    sh_ret = (sh_close[d] - sh_close[prev_d]) / sh_close[prev_d] * 100
    results.append({'date': d, 'hh': round(hh_ret,2), 'sh': round(sh_ret,2)})

# Stats
green = [r for r in results if r['sh'] < 0]      # 大盘跌
red = [r for r in results if r['sh'] > 0]         # 大盘涨
crash = [r for r in results if r['sh'] < -0.5]    # 大盘跌>0.5%
micro = [r for r in results if -0.5 <= r['sh'] < 0]  # 微跌
big_red = [r for r in results if r['sh'] > 1]     # 大涨>1%

print("="*60)
print("🔥 昊华科技 600378 vs 上证指数 (2026年)")
print("="*60)

print(f"\n总交易日: {len(results)}天")

print(f"\n📊 大盘跌时 昊华表现:")
print(f"  大盘跌共 {len(green)}天")
if green:
    hh_up = [r for r in green if r['hh'] > 0]
    hh_down = [r for r in green if r['hh'] <= 0]
    print(f"  昊华逆涨: {len(hh_up)}次 ({len(hh_up)/len(green)*100:.0f}%)")
    print(f"  昊华跟跌: {len(hh_down)}次 ({len(hh_down)/len(green)*100:.0f}%)")
    print(f"  昊华均值: {sum(r['hh'] for r in green)/len(green):+.2f}%")

print(f"\n📊 大盘涨时 昊华表现:")
print(f"  大盘涨共 {len(red)}天")
if red:
    hh_up = [r for r in red if r['hh'] > 0]
    print(f"  昊华跟涨: {len(hh_up)}次 ({len(hh_up)/len(red)*100:.0f}%)")
    print(f"  昊华均值: {sum(r['hh'] for r in red)/len(red):+.2f}%")

# By severity
print(f"\n📐 按大盘跌幅分组:")
for lo, hi, label in [(-10, -1.5, '暴跌>-1.5%'), (-1.5, -1.0, '大跌-1~-1.5%'),
                       (-1.0, -0.5, '小跌-0.5~-1%'), (-0.5, 0, '微跌0~-0.5%')]:
    seg = [r for r in results if lo < r['sh'] <= hi]
    if seg:
        up = [r for r in seg if r['hh'] > 0]
        print(f"  {label}: {len(seg)}天, 逆涨{len(up)}次({len(up)/len(seg)*100:.0f}%), 均值{sum(r['hh'] for r in seg)/len(seg):+.2f}%")

# Big red days
print(f"\n📐 大盘大涨时:")
for lo, hi, label in [(0, 0.5, '微涨0~0.5%'), (0.5, 1, '小涨0.5~1%'), (1, 5, '大涨>1%')]:
    seg = [r for r in results if lo < r['sh'] <= hi]
    if seg:
        up = [r for r in seg if r['hh'] > 0]
        print(f"  {label}: {len(seg)}天, 跟涨{len(up)}次({len(up)/len(seg)*100:.0f}%), 均值{sum(r['hh'] for r in seg)/len(seg):+.2f}%")

# Crash days detail
print(f"\n🔴 大盘跌>0.5% 的日子 (共{len(crash)}天):")
if crash:
    for r in sorted(crash, key=lambda x: x['sh']):
        tag = '🔥 逆涨' if r['hh'] > 0 else ''
        print(f"  {r['date']} 上证{r['sh']:+.2f}%  昊华{r['hh']:+.2f}% {tag}")

# Micro dip detail
print(f"\n🟡 大盘微跌0~-0.5% 的日子 (共{len(micro)}天):")
if micro:
    for r in sorted(micro, key=lambda x: x['hh'], reverse=True):
        tag = '✅' if r['hh'] > 0 else '❌'
        print(f"  {tag} {r['date']} 上证{r['sh']:+.2f}%  昊华{r['hh']:+.2f}%")

print("\n" + "="*60)
print("✅ 分析完成")
