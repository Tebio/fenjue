#!/usr/bin/env python3
"""焚訣策略回测 v3 — 严格无未来函数
只能用 T-1 日K(MA/乖离) + T日竞价(开盘涨跌)
验证：→ T日收盘涨跌
"""
import json, urllib.request, ssl, time, glob, os

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def get_daily(sina):
    url = f'http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={sina}&scale=240&ma=no&datalen=90'
    req = urllib.request.Request(url, headers={'Referer':'https://finance.sina.com.cn'})
    resp = urllib.request.urlopen(req, context=ctx, timeout=12)
    return json.loads(resp.read().decode('utf-8'))

# 加载最新池票
pool_files = sorted(glob.glob('/opt/data/fenjue/pool_*.json'))
with open(pool_files[-1]) as f:
    pool = json.load(f)['results']

codes = []
for s in pool:
    c = str(s['code'])
    codes.append((('sh' if c[0]=='6' else 'sz') + c, s['name'], c, s.get('sector','')))

print(f'回测 {len(codes)} 只池票 | 策略: T-1日K → T日竞价 → T日收盘')
print('='*70)

# ========================================
# 策略定义（只用T日9:25已知数据）
# ========================================

# 策略A: T-1 快金叉(MA5/MA20差 -8→+3%) + T日高开>1%
# 策略B: T-1 快金叉 + T日低开<-1%
# 策略C: T-1 MA站上MA5/MA20 + T日高开1-6%
# 策略D: T-1 MA5乖离<10% + T日竞价平开(-1→+1%)

strategy_results = {
    'A 快金叉+高开': [],
    'B 快金叉+低开': [],
    'C MA站上+健康高开': [],
    'D 贴均线+平开': [],
}

all_days = 0
total_signals = 0

for i, (sina, name, code, sector) in enumerate(codes):
    try:
        data = get_daily(sina)
        if len(data) < 25:
            continue
        
        closes = []
        opens = []
        highs = []
        lows = []
        dates = []
        for d in data:
            if d['day'] < '2026-04-01':
                continue
            closes.append(float(d['close']))
            opens.append(float(d['open']))
            highs.append(float(d['high']))
            lows.append(float(d['low']))
            dates.append(d['day'])
        
        if len(closes) < 25:
            continue
        
        # 对每个可回测的交易日
        for day_idx in range(20, len(closes)-1):
            # T-1 数据
            t1_close = closes[day_idx - 1]
            
            # 算T-1的MA5和MA20
            if day_idx >= 5:
                t1_ma5 = sum(closes[day_idx-5:day_idx]) / 5
            else:
                t1_ma5 = t1_close
            if day_idx >= 20:
                t1_ma20 = sum(closes[day_idx-20:day_idx]) / 20
            else:
                t1_ma20 = t1_close
            
            t1_ma5_gap = (t1_close - t1_ma5) / t1_ma5 * 100  # T-1 MA5乖离
            t1_ma20_gap = (t1_close - t1_ma20) / t1_ma20 * 100  # T-1 MA20乖离
            t1_ma_diff = (t1_ma5 - t1_ma20) / t1_ma20 * 100  # T-1 MA5/MA20差
            
            # T日竞价
            t_open = opens[day_idx]
            t_bid_gap = (t_open - t1_close) / t1_close * 100  # 竞价涨跌
            
            # T日收盘（用来验证，不是用来筛选！）
            t_close = closes[day_idx]
            t_ret = (t_close - t_open) / t_open * 100  # 从开盘到收盘
            t_day_ret = (t_close - t1_close) / t1_close * 100  # 从昨收到今收
            
            all_days += 1
            
            # === 策略A: T-1快金叉 + T日高开>1% ===
            if -8 <= t1_ma_diff <= 3 and t_bid_gap > 1:
                strategy_results['A 快金叉+高开'].append({
                    'name': name, 'code': code, 'date': dates[day_idx],
                    'bid_gap': round(t_bid_gap, 1), 'ret': round(t_ret, 1),
                    'day_ret': round(t_day_ret, 1),
                    'ma_diff': round(t1_ma_diff, 1)
                })
                total_signals += 1
            
            # === 策略B: T-1快金叉 + T日低开<-1% ===
            if -8 <= t1_ma_diff <= 3 and t_bid_gap < -1:
                strategy_results['B 快金叉+低开'].append({
                    'name': name, 'code': code, 'date': dates[day_idx],
                    'bid_gap': round(t_bid_gap, 1), 'ret': round(t_ret, 1),
                    'day_ret': round(t_day_ret, 1),
                    'ma_diff': round(t1_ma_diff, 1)
                })
                total_signals += 1
            
            # === 策略C: T-1 MA站上 + T日健康高开(1-6%) ===
            if t1_close > t1_ma5 and 1 <= t_bid_gap <= 6:
                strategy_results['C MA站上+健康高开'].append({
                    'name': name, 'code': code, 'date': dates[day_idx],
                    'bid_gap': round(t_bid_gap, 1), 'ret': round(t_ret, 1),
                    'day_ret': round(t_day_ret, 1),
                })
                total_signals += 1
            
            # === 策略D: T-1 MA5乖离<10% + T日平开(-1~+1%) ===
            if -10 <= t1_ma5_gap <= 10 and -1 <= t_bid_gap <= 1:
                strategy_results['D 贴均线+平开'].append({
                    'name': name, 'code': code, 'date': dates[day_idx],
                    'bid_gap': round(t_bid_gap, 1), 'ret': round(t_ret, 1),
                    'day_ret': round(t_day_ret, 1),
                    'ma5_gap': round(t1_ma5_gap, 1)
                })
                total_signals += 1
        
        if (i+1) % 20 == 0:
            print(f'  [{i+1}/{len(codes)}] 已扫描 {total_signals} 个信号...')
        
        time.sleep(0.15)
    except Exception as e:
        time.sleep(0.15)
        pass

# ========================================
# 汇总
# ========================================
print(f'\n总数: {len(codes)}只票 | 扫描 {all_days} 个交易日 | 信号 {total_signals} 个\n')

for strat_name in ['A 快金叉+高开', 'B 快金叉+低开', 'C MA站上+健康高开', 'D 贴均线+平开']:
    results = strategy_results[strat_name]
    if not results:
        print(f'📊 策略{strat_name}: 0个信号')
        continue
    
    up = [r for r in results if r['ret'] > 0]
    wr = len(up) / len(results) * 100
    avg_ret = sum(r['ret'] for r in results) / len(results)
    avg_day = sum(r['day_ret'] for r in results) / len(results)
    
    print(f'📊 策略{strat_name}')
    print(f'   信号: {len(results)}个 | 当日涨(开盘→收盘): {len(up)}个 | 胜率: {wr:.0f}%')
    print(f'   均值(开盘→收盘): {avg_ret:+.2f}% | 均值(昨收→今收): {avg_day:+.2f}%')
    
    # Top/Bottom 5
    top = sorted(results, key=lambda x: x['ret'], reverse=True)[:5]
    bot = sorted(results, key=lambda x: x['ret'])[:5]
    
    print(f'   🔥 最佳:')
    for r in top:
        print(f'      {r["code"]} {r["name"]:<8} {r["date"]} 竞{r["bid_gap"]:+.1f}% → 收{r["ret"]:+.1f}%')
    print(f'   💀 最差:')
    for r in bot:
        print(f'      {r["code"]} {r["name"]:<8} {r["date"]} 竞{r["bid_gap"]:+.1f}% → 收{r["ret"]:+.1f}%')
    print()

print('='*70)
print('✅ 无未来函数回测完成')
print('   决策数据: T-1 MA + T日9:25竞价')
print('   验证数据: T日15:00收盘')
print('='*70)
