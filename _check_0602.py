#!/usr/bin/env python3
"""昊华科技 600378 6/2 分钟线复盘"""
import json, urllib.request, ssl

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

url = 'http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol=sh600378&scale=5&ma=no&datalen=60'
req = urllib.request.Request(url, headers={'Referer':'https://finance.sina.com.cn'})
resp = urllib.request.urlopen(req, context=ctx, timeout=15)
data = json.loads(resp.read().decode('utf-8'))

print("="*75)
print("🔍 昊华科技 600378 6/2 5分钟K线复盘")
print("="*75)

# 找6/2的数据
target = None
for d in data:
    if d['day'].startswith('2026-06-02'):
        target = d['day']
        break

if not target:
    print("无6/2分钟数据（Sina只提供最近几天）")
    exit()

day_data = [d for d in data if d['day'].startswith('2026-06-02')]
if not day_data:
    print("无6/2数据")
    exit()

o = float(day_data[0]['open'])
c = float(day_data[-1]['close'])
highs = [float(d['high']) for d in day_data]
lows = [float(d['low']) for d in day_data]
h = max(highs)
l = min(lows)
amp = (h - l) / l * 100
final_pos = (c - l) / (h - l) * 100

print(f"\n📊 6/2 日K概览:")
print(f"  开{o:.2f} 高{h:.2f} 低{l:.2f} 收{c:.2f}")
print(f"  振幅{amp:.2f}%  收盘位{final_pos:.0f}%")
print(f"  (回测策略D位68% — 现在精确计算={final_pos:.0f}%)")

# 逐根分钟线找位>70%的时刻
print(f"\n⏱️  逐5分钟K线 — 寻找盘中位>70%的时刻:")
print(f"  {'时间':<8} {'价':<7} {'高':<7} {'低':<7} {'位%':<6} {'状态'}")
print(f"  {'-'*50}")

ever_above_70 = False
max_pos = 0
max_pos_time = ""

for d in day_data:
    t = d['day'].split(' ')[-1][:5]
    price = float(d['close'])
    high_sofar = max(float(x['high']) for x in day_data[:day_data.index(d)+1])
    low_sofar = min(float(x['low']) for x in day_data[:day_data.index(d)+1])
    
    # 当时日内位（基于当时已出现的高低点）
    if high_sofar > low_sofar:
        pos_now = (price - low_sofar) / (high_sofar - low_sofar) * 100
    else:
        pos_now = 50
    
    if pos_now > max_pos:
        max_pos = pos_now
        max_pos_time = t
    
    marker = ""
    if pos_now > 70:
        ever_above_70 = True
        marker = "🔥 >70%"
    
    # 也计算最终日内位（基于全天高低点）
    if h > l:
        pos_final = (price - l) / (h - l) * 100
    else:
        pos_final = 50
    
    # 只在关键时间点打印
    if t in ['09:35','09:40','09:45','09:50','10:00','10:30','11:00','11:30','13:05','13:30','14:00','14:30','14:45','15:00']:
        print(f"  {t:<8} {price:<7.2f} {high_sofar:<7.2f} {low_sofar:<7.2f} {pos_now:<6.0f} {marker}")

print(f"\n📈 结果:")
print(f"  盘中最高位: {max_pos:.0f}% ({max_pos_time})")
print(f"  收盘位: {final_pos:.0f}%")
print(f"  盘中是否>70%: {'✅ 是' if ever_above_70 else '❌ 否'}")

if ever_above_70:
    print(f"\n⚠️ 盘中出现过>70%信号，但收盘跌到{final_pos:.0f}%")
    print(f"   → 策略D需要收盘确认位>70%，不能盘中抢跑")
    print(f"   → 如果盘中位>70%就入场，6/2会被套")
else:
    print(f"\n✅ 6/2全天位<70%，深V从未真正成形")
    print(f"   → 策略D收盘位阈值有效")
