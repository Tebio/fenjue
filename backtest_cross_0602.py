#!/usr/bin/env python3
"""6/2 跨策略交集 → 5日(→6/9) 回测"""
import json, urllib.request, ssl, time, glob

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

# 1. 加载 6/2 池，计算跨策略交集
with open('/opt/data/fenjue/pool_20260602.json') as f:
    pool = json.load(f)['results']

golden = set()
low_golden = set()
dark = set()
multi = set()
bottom = set()

hot_sectors = {'半导体','消费电子','元件','光学光电','通信设备','其他电源','军工电子','煤炭开采','证券Ⅱ'}

for s in pool:
    code = str(s['code'])
    pct = s.get('pct', 0) or 0
    amt = s.get('amount_yi', 0) or 0
    ma5 = s.get('ma5')
    ma20 = s.get('ma20')
    sec = s.get('sector', '')
    price = s.get('price', 0)
    
    if ma5 and ma20:
        gap = (ma5 - ma20)/ma20*100
        real_gap = (price/ma20 - 1)*100
        
        if -8 <= gap <= 3 and amt > 1:
            golden.add(code)
        if -8 <= gap <= 3 and -3 <= pct <= 3 and amt > 3:
            low_golden.add(code)
        if 2 <= pct <= 7 and amt > 5 and real_gap < 25:
            multi.add(code)
    
    if amt > 15 and pct < 5:
        dark.add(code)
    if pct < 5 and 3 <= amt <= 15 and not any(h in sec for h in hot_sectors):
        bottom.add(code)

# 2. 找出≥2策略命中
cross = {}
for s in pool:
    code = str(s['code'])
    count = 0
    strats = []
    if code in golden: count += 1; strats.append('快金叉')
    if code in low_golden: count += 1; strats.append('低位金叉')
    if code in dark: count += 1; strats.append('大成交')
    if code in multi: count += 1; strats.append('多因子')
    if code in bottom: count += 1; strats.append('底部潜伏')
    if count >= 2:
        cross[code] = {'name': s['name'], 'count': count, 'strats': strats,
                       'pct': s.get('pct',0), 'amt': s.get('amount_yi',0),
                       'sector': s.get('sector',''), 'price_0602': s.get('price',0)}

print(f"6/2 跨策略≥2: {len(cross)}只")
print()

# 3. 按策略数排序，逐个拉6/9收盘价
sorted_codes = sorted(cross.items(), key=lambda x: x[1]['count'], reverse=True)

# 先试 Sina 日K
def get_daily(sina):
    url = f'http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={sina}&scale=240&ma=no&datalen=10'
    req = urllib.request.Request(url, headers={'Referer':'https://finance.sina.com.cn'})
    resp = urllib.request.urlopen(req, context=ctx, timeout=10)
    return json.loads(resp.read().decode('utf-8'))

results = []
errors = 0

for code, info in sorted_codes:
    sina = ('sh' if code[0]=='6' else 'sz') + code
    try:
        data = get_daily(sina)
        closes = {d['day']: float(d['close']) for d in data}
        
        # 找6/2和6/9
        c0602 = closes.get('2026-06-02')
        c0609 = closes.get('2026-06-09')
        
        if c0602 and c0609:
            ret = (c0609 - c0602) / c0602 * 100
            results.append({**info, 'price_0609': c0609, 'ret': round(ret, 2)})
            print(f"  {code} {info['name']:<8} [{info['count']}策] 6/2:{c0602:.2f}→6/9:{c0609:.2f} {ret:+.1f}%")
        else:
            print(f"  {code} {info['name']:<8} [{info['count']}策] 缺数据")
            errors += 1
    except Exception as e:
        print(f"  {code} {info['name']:<8} [{info['count']}策] err: {str(e)[:40]}")
        errors += 1
    time.sleep(0.15)

# 4. 汇总
print(f'\n{"="*60}')
print(f'📊 6/2跨策略回测: {len(cross)}只 → {len(results)}只有效 → 5日→6/9')
print(f'{"="*60}')

if results:
    up = [r for r in results if r['ret'] > 0]
    down = [r for r in results if r['ret'] <= 0]
    print(f'上涨: {len(up)}只 | 下跌: {len(down)}只')
    print(f'胜率: {len(up)/len(results)*100:.0f}%')
    print(f'平均: {sum(r["ret"] for r in results)/len(results):+.2f}%')
    if up:
        print(f'上涨均值: {sum(r["ret"] for r in up)/len(up):+.2f}%')
    if down:
        print(f'下跌均值: {sum(r["ret"] for r in down)/len(down):+.2f}%')
    
    print(f'\n按策略数分组:')
    for n in [4,3,2]:
        group = [r for r in results if r['count'] == n]
        if group:
            g_up = [r for r in group if r['ret'] > 0]
            print(f'  [{n}策] {len(group)}只 胜率{len(g_up)/len(group)*100:.0f}% 均值{sum(r["ret"] for r in group)/len(group):+.2f}%')
    
    print(f'\n明细:')
    for r in sorted(results, key=lambda x: x['ret'], reverse=True):
        t = '🔥' if r['ret'] > 10 else ('✅' if r['ret'] > 0 else '❌')
        print(f'  {t} {r["code"]} {r["name"]:<8} [{r["count"]}策] {r["ret"]:+.1f}% {r["sector"]}')
