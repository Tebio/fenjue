#!/usr/bin/env python3
"""全市场扫描：突然逆市的票 → 2周/1月后表现"""
import os, time, json, sys, urllib.request, ssl
from collections import defaultdict

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

sys.path.insert(0, '/opt/data/fenjue')

def get_daily_with_sh(sina_code, start_date='20260101', end_date='20260609'):
    """拉个股+上证日K"""
    url = f'http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={sina_code}&scale=240&ma=no&datalen=200'
    req = urllib.request.Request(url, headers={'Referer':'https://finance.sina.com.cn'})
    try:
        resp = urllib.request.urlopen(req, context=ctx, timeout=12)
        data = json.loads(resp.read().decode('utf-8'))
        return data
    except:
        return None

# 1. 拉上证
print("拉上证指数...")
sh_data = get_daily_with_sh('sh000001')
if not sh_data:
    print("上证数据失败"); sys.exit(1)

sh_map = {}
for d in sh_data:
    sh_map[d['day']] = float(d['close'])

# 计算上证每日涨跌
sh_dates = sorted(sh_map.keys())
sh_ret = {}
for i in range(1, len(sh_dates)):
    ret = (sh_map[sh_dates[i]] - sh_map[sh_dates[i-1]]) / sh_map[sh_dates[i-1]] * 100
    sh_ret[sh_dates[i]] = ret

# 2. 股票池 — 从最近的焚诀池拉代码
pool_file = '/opt/data/fenjue/pool_20260602.json'
if not os.path.exists(pool_file):
    pool_file = '/opt/data/fenjue/pool_20260601.json'

try:
    with open(pool_file) as f:
        pool = json.load(f)['results']
except:
    print("无池文件"); sys.exit(1)

# 取前80只（不同行业覆盖）
seen_sectors = set()
test_stocks = []
for s in pool:
    sec = s.get('sector', '')
    if sec not in seen_sectors or len(test_stocks) < 80:
        test_stocks.append(s)
        seen_sectors.add(sec)
    if len(test_stocks) >= 80:
        break

print(f"测试 {len(test_stocks)} 只股票...")

# 3. 逐只分析
results = []
errors = 0

for i, stock in enumerate(test_stocks):
    code = str(stock['code'])
    sina = ('sh' if code[0]=='6' else 'sz') + code
    
    try:
        data = get_daily_with_sh(sina)
        if not data or len(data) < 80:
            errors += 1
            continue
        
        # 构建每日涨跌
        closes = {}
        for d in data:
            closes[d['day']] = float(d['close'])
        
        dates = sorted(closes.keys())
        stock_ret = {}
        for j in range(1, len(dates)):
            ret = (closes[dates[j]] - closes[dates[j-1]]) / closes[dates[j-1]] * 100
            stock_ret[dates[j]] = ret
        
        # 找「突然逆市」信号：
        # 定义逆市 = 大盘跌但个股涨
        # 用滚动10日窗口，计算逆涨率
        # 找窗口A(逆涨率<30%) → 窗口B(逆涨率>60%) 的转变
        
        common_dates = sorted(set(stock_ret.keys()) & set(sh_ret.keys()))
        if len(common_dates) < 60:
            errors += 1
            continue
        
        # 计算每日是否逆涨
        anti_days = []
        for d in common_dates:
            if sh_ret[d] < -0.1 and stock_ret[d] > 0:
                anti_days.append(1)
            else:
                anti_days.append(0)
        
        # 滚动10日逆涨率
        window = 10
        anti_rates = []
        for j in range(window-1, len(anti_days)):
            rate = sum(anti_days[j-window+1:j+1]) / window
            anti_rates.append(rate)
        
        # 找转变点：前10日逆涨率<0.3 → 后10日逆涨率>0.5
        regime_shifts = []
        for j in range(window, len(anti_rates)):
            prev_rate = anti_rates[j-window]
            curr_rate = anti_rates[j]
            prev_dates = common_dates[j-window:j+1]
            
            # 需要大盘在这段时间有足够的跌日来验证
            down_days_prev = sum(1 for d in prev_dates if sh_ret.get(d, 0) < -0.1)
            down_days_curr = sum(1 for d in common_dates[j-window+1:j+window+1] if sh_ret.get(d, 0) < -0.1)
            
            if down_days_prev < 3 or down_days_curr < 3:
                continue  # 大盘跌日太少，逆涨率不可靠
            
            if prev_rate <= 0.3 and curr_rate >= 0.5:
                shift_date = common_dates[j]
                
                # 计算转变后 5、10、20日的表现
                shift_idx = common_dates.index(shift_date)
                for horizon, label in [(5, '5日'), (10, '10日'), (20, '20日')]:
                    if shift_idx + horizon < len(common_dates):
                        start_price = closes.get(shift_date, closes[common_dates[shift_idx]])
                        end_price = closes[common_dates[shift_idx + horizon]]
                        fwd_ret = (end_price - start_price) / start_price * 100
                        regime_shifts.append({
                            'stock': stock['name'], 'code': code, 'sector': stock.get('sector', ''),
                            'shift_date': shift_date,
                            'prev_rate': round(prev_rate*100), 'curr_rate': round(curr_rate*100),
                            'horizon': label,
                            'fwd_ret': round(fwd_ret, 1),
                            'days': horizon
                        })
        
        if regime_shifts:
            results.extend(regime_shifts)
            # 每只票只取最近一次转变
            latest = max(regime_shifts, key=lambda x: x['shift_date'])
            print(f"  [{i+1}/{len(test_stocks)}] {stock['name']:<8} {stock.get('sector',''):<10} "
                  f"{latest['shift_date']} 逆涨{latest['prev_rate']}%→{latest['curr_rate']}% "
                  f"5日{next((r['fwd_ret'] for r in regime_shifts if r['horizon']=='5日'), '?'):>6} "
                  f"10日{next((r['fwd_ret'] for r in regime_shifts if r['horizon']=='10日'), '?'):>6} "
                  f"20日{next((r['fwd_ret'] for r in regime_shifts if r['horizon']=='20日'), '?'):>6}")
    except Exception as e:
        errors += 1
    time.sleep(0.15)

if errors:
    print(f"\n错误: {errors}只")

# 4. 汇总
if not results:
    print("\n无匹配的「突然逆市」信号")
    sys.exit(0)

print(f"\n{'='*70}")
print(f"📊 汇总：「突然逆市」信号后表现")
print(f"总信号数: {len(results)} (来自 {len(set(r['code'] for r in results))} 只票)")
print(f"{'='*70}")

for horizon in ['5日', '10日', '20日']:
    h_results = [r for r in results if r['horizon'] == horizon]
    if not h_results:
        continue
    up = [r for r in h_results if r['fwd_ret'] > 0]
    avg_ret = sum(r['fwd_ret'] for r in h_results) / len(h_results)
    median_ret = sorted(h_results, key=lambda x: x['fwd_ret'])[len(h_results)//2]['fwd_ret']
    print(f"\n{horizon}后 (共{len(h_results)}次):")
    print(f"  胜率: {len(up)}/{len(h_results)} = {len(up)/len(h_results)*100:.0f}%")
    print(f"  均值: {avg_ret:+.1f}%  中位: {median_ret:+.1f}%")
    
    # 前10
    top = sorted(h_results, key=lambda x: x['fwd_ret'], reverse=True)[:10]
    bottom = sorted(h_results, key=lambda x: x['fwd_ret'])[:5]
    print(f"\n  🔥 最佳:")
    for r in top:
        print(f"    {r['stock']:<8} {r['shift_date']} → {r['fwd_ret']:+.1f}%")
    print(f"  ❌ 最差:")
    for r in bottom:
        print(f"    {r['stock']:<8} {r['shift_date']} → {r['fwd_ret']:+.1f}%")

print(f"\n{'='*70}")
print("✅ 完成")
