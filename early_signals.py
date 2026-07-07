#!/usr/bin/env python3
"""扫描「突然逆市」信号刚刚触发的票（最近3天）"""
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

# 加载焚诀池票
import glob
pool_files = sorted(glob.glob('/opt/data/fenjue/pool_*.json'))
if pool_files:
    with open(pool_files[-1]) as f:
        pool = json.load(f)['results']
    codes = []
    for s in pool:
        c = str(s['code'])
        sina = ('sh' if c[0]=='6' else 'sz') + c
        codes.append((sina, s['name'], s.get('sector','')))
else:
    codes = [
        ('sh600367','红星发展','化学原料'),
        ('sh600378','昊华科技','化学制品'),
        ('sh000636','风华高科','元件'),
        ('sh600726','华电能源','电力'),
        ('sh603011','合锻智能','专用设备'),
        ('sh603678','火炬电子','军工电子'),
    ]

# 拉上证
print('拉上证日K...')
sh = get_shanghai()
sh_dates = {}
for d in sh:
    sh_dates[d['day']] = float(d['close'])

print(f'扫描 {len(codes)} 只池票...')
results = []
recent_dates = ['2026-06-08','2026-06-05','2026-06-04','2026-06-03','2026-06-02']

for i, (sina, name, sector) in enumerate(codes):
    try:
        data = get_data(sina)
        if len(data) < 40:
            continue
        
        # 只取2026年
        data = [d for d in data if d['day'] >= '2026-01-01']
        if len(data) < 40:
            continue
        
        # 计算每日涨跌 vs 上证
        closes = {}
        for d in data:
            closes[d['day']] = float(d['close'])
        
        dates = sorted(closes.keys())
        
        # 找最近的「突然逆市」信号
        # 前10日逆涨率<30%, 后几日逆涨率>50%
        for idx in range(len(dates) - 15):
            sig_date = dates[idx]
            
            # 只看最近信号
            if sig_date < '2026-06-01':
                continue
            
            # 前10日
            prev_start = max(idx - 10, 0)
            prev_dates = dates[prev_start:idx]
            prev_up = 0
            prev_total = 0
            for pd_date in prev_dates:
                if pd_date in sh_dates and idx > 0:
                    pidx = dates.index(pd_date)
                    if pidx + 1 < len(dates):
                        stk_chg = (closes[dates[pidx+1]] - closes[pd_date]) / closes[pd_date] * 100
                        sh_chg = (sh_dates.get(dates[pidx+1], 0) - sh_dates.get(pd_date, 0)) / sh_dates.get(pd_date, 1) * 100
                        if sh_chg < 0 and stk_chg > 0:
                            prev_up += 1
                        if sh_chg < 0:
                            prev_total += 1
            
            if prev_total < 3:
                continue
            prev_rate = prev_up / prev_total * 100
            
            # 后5日或后10日
            next_end = min(idx + 6, len(dates))
            next_dates = dates[idx:next_end]
            next_up = 0
            next_total = 0
            for nd_date in next_dates:
                nd_idx = dates.index(nd_date)
                if nd_idx + 1 < len(dates):
                    stk_chg = (closes[dates[nd_idx+1]] - closes[nd_date]) / closes[nd_date] * 100
                    sh_chg = (sh_dates.get(dates[nd_idx+1], 0) - sh_dates.get(nd_date, 0)) / sh_dates.get(nd_date, 1) * 100
                    if sh_chg < 0 and stk_chg > 0:
                        next_up += 1
                    if sh_chg < 0:
                        next_total += 1
            
            if next_total < 1:
                continue
            next_rate = next_up / next_total * 100
            
            if prev_rate < 30 and next_rate > 50:
                # 计算从信号日到最新的涨幅
                sig_close = closes[sig_date]
                latest_close = closes[dates[-1]]
                days_since = len(dates) - idx - 1
                ret = (latest_close - sig_close) / sig_close * 100
                
                results.append({
                    'name': name, 'code': sina[2:], 'sector': sector,
                    'sig_date': sig_date,
                    'prev_rate': prev_rate, 'next_rate': next_rate,
                    'days_since': days_since,
                    'ret': ret,
                    'latest_price': latest_close,
                    'sig_price': sig_close,
                })
        
        if (i+1) % 20 == 0:
            print(f'  [{i+1}/{len(codes)}] ...')
        
        time.sleep(0.15)
    except Exception as e:
        time.sleep(0.15)
        pass

# 按信号日期排序
results.sort(key=lambda x: x['sig_date'], reverse=True)

print(f'\n{"="*70}')
print(f'🔔 最近「突然逆市」信号（按触发日期降序）')
print(f'{"="*70}')
print(f'{"票":<10} {"行业":<10} {"信号日":<12} {"天数":<6} {"累计%":<8} {"现价":<8}')
print('-'*54)

for r in results[:30]:
    print(f'{r["name"]:<10} {r["sector"]:<10} {r["sig_date"]:<12} {r["days_since"]:<5}T {r["ret"]:<+8.1f}% {r["latest_price"]:<8.2f}')

print(f'\n总信号: {len(results)}个')
print()
print('🔍 信号刚触发(≤3天) + 累计涨幅<15% = 还在甜蜜点的:')
print()

early = [r for r in results if r['days_since'] <= 3 and r['ret'] < 15]
if early:
    for r in sorted(early, key=lambda x: x['ret']):
        print(f'  🟢 {r["name"]:<10} {r["sector"]:<10} {r["sig_date"]} 才{r["days_since"]}T 涨{r["ret"]:+.1f}% 现{r["latest_price"]:.2f}')
else:
    print('  ⚠️ 没有刚触发的票。所有信号都已运行了若干天。')
    # 放宽条件
    early2 = [r for r in results if r['days_since'] <= 5 and r['ret'] < 20]
    if early2:
        print(f'\n  放宽到 ≤5T + 涨<20%:')
        for r in sorted(early2, key=lambda x: x['ret']):
            print(f'  🟡 {r["name"]:<10} {r["sector"]:<10} {r["sig_date"]} {r["days_since"]}T 涨{r["ret"]:+.1f}% 现{r["latest_price"]:.2f}')
