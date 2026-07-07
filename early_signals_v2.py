#!/usr/bin/env python3
"""扫描「突然逆市」信号 v2 — 放宽条件"""
import json, urllib.request, ssl, time

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def get_data(sina):
    url = f'http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={sina}&scale=240&ma=no&datalen=90'
    req = urllib.request.Request(url, headers={'Referer':'https://finance.sina.com.cn'})
    resp = urllib.request.urlopen(req, context=ctx, timeout=12)
    return json.loads(resp.read().decode('utf-8'))

def get_shanghai():
    return get_data('sh000001')

import glob, sys
pool_files = sorted(glob.glob('/opt/data/fenjue/pool_*.json'))
if pool_files:
    with open(pool_files[-1]) as f:
        pool = json.load(f)['results']
    codes = []
    for s in pool:
        c = str(s['code'])
        sina = ('sh' if c[0]=='6' else 'sz') + c
        codes.append((sina, s['name'], s.get('sector',''), c))
else:
    print("No pool file!")
    sys.exit(1)

print('拉上证日K...')
sh = get_shanghai()
sh_changes = {}  # date -> daily change
sh_close = {}
prev = None
for d in sh:
    c = float(d['close'])
    sh_close[d['day']] = c
    if prev:
        sh_changes[d['day']] = (c - prev) / prev * 100
    prev = c

print(f'扫描 {len(codes)} 只池票（放宽版）...')

results = []

for i, (sina, name, sector, code) in enumerate(codes):
    try:
        data = get_data(sina)
        if len(data) < 30:
            continue
        data = [d for d in data if d['day'] >= '2026-04-01']
        if len(data) < 30:
            continue
        
        closes = {}
        for d in data:
            closes[d['day']] = float(d['close'])
        dates = sorted(closes.keys())
        
        # 对每10天窗口，算逆涨率
        for idx in range(10, len(dates) - 8):
            sig_date = dates[idx]
            
            # 前10天逆涨率
            prev_up = 0
            prev_total = 0
            for j in range(max(idx-10, 0), idx):
                d_date = dates[j]
                if d_date in sh_changes:
                    sh_chg = sh_changes[d_date]
                    stk_chg = (closes[dates[j+1]] - closes[d_date]) / closes[d_date] * 100 if j+1 < len(closes) else 0
                    if sh_chg < 0:  # 大盘跌的日子
                        prev_total += 1
                        if stk_chg > 0:
                            prev_up += 1
            
            if prev_total < 3:
                continue
            prev_rate = prev_up / prev_total * 100
            
            # 后5天逆涨率
            next_up = 0
            next_total = 0
            end = min(idx + 6, len(dates) - 1)
            for j in range(idx, end):
                d_date = dates[j]
                if d_date in sh_changes:
                    sh_chg = sh_changes[d_date]
                    stk_chg = (closes[dates[j+1]] - closes[d_date]) / closes[d_date] * 100 if j+1 < len(closes) else 0
                    if sh_chg < 0:
                        next_total += 1
                        if stk_chg > 0:
                            next_up += 1
            
            if next_total < 1:
                continue
            next_rate = next_up / next_total * 100
            
            # 放宽：前<40% → 后>50%
            if prev_rate < 40 and next_rate > 50 and next_rate - prev_rate > 20:
                sig_close = closes[sig_date]
                latest_close = closes[dates[-1]]
                days_since = len(dates) - idx - 1
                ret = (latest_close - sig_close) / sig_close * 100
                
                results.append({
                    'name': name, 'code': code, 'sector': sector,
                    'sig_date': sig_date,
                    'prev_rate': round(prev_rate, 1),
                    'next_rate': round(next_rate, 1),
                    'days_since': days_since,
                    'ret': round(ret, 1),
                    'latest_price': latest_close,
                    'sig_price': sig_close,
                })
        
        if (i+1) % 25 == 0:
            print(f'  [{i+1}/{len(codes)}] 已发现 {len(results)} 个信号')
        
        time.sleep(0.15)
    except Exception as e:
        time.sleep(0.15)

# 去重（只保留每个code的最新信号）
seen = {}
for r in sorted(results, key=lambda x: x['sig_date'], reverse=True):
    if r['code'] not in seen:
        seen[r['code']] = r
results = list(seen.values())
results.sort(key=lambda x: x['sig_date'], reverse=True)

print(f'\n{"="*70}')
print(f'🔔 突然逆市信号（放宽版: 前<40%→后>50%, 差>20%）')
print(f'总信号: {len(results)}个 (来自 {len(codes)} 只池票)')
print(f'{"="*70}')
print(f'{"票":<10} {"行业":<10} {"信号日":<12} {"已过T":<6} {"涨%":<8} {"现价":<8}')
print('-'*54)

for r in results[:40]:
    tag = '🔥' if r['ret'] > 20 else ('🟢' if r['ret'] > 5 else '🟡')
    print(f'{tag} {r["name"]:<10} {r["sector"]:<10} {r["sig_date"]:<12} {r["days_since"]:<5}T {r["ret"]:<+8.1f}% {r["latest_price"]:<8.2f}')

print()
print('=' * 70)
print('🎯 早期信号 (≤3T + 涨<15%):')

early = [r for r in results if r['days_since'] <= 3 and r['ret'] < 15]
early2 = [r for r in results if r['days_since'] <= 5 and r['ret'] < 20]

if early:
    for r in sorted(early, key=lambda x: x['ret']):
        print(f'  🟢 [{r["sig_date"]}] {r["name"]} {r["sector"]} 才{r["days_since"]}T 涨{r["ret"]:+.1f}% 现{r["latest_price"]:.2f}')
elif early2:
    print(f'  无≤3T信号，放宽到≤5T:')
    for r in sorted(early2, key=lambda x: x['ret']):
        print(f'  🟡 [{r["sig_date"]}] {r["name"]} {r["sector"]} {r["days_since"]}T 涨{r["ret"]:+.1f}% 现{r["latest_price"]:.2f}')
else:
    print('  无早期信号')
