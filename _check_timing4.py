import akshare as ak
import numpy as np

df_min = ak.stock_zh_a_minute(symbol='sz002384', period='1')
df_min['date'] = df_min['day'].astype(str).str[:10]
dates = sorted(df_min['date'].unique())

time_buckets = {
    '09:31-09:40': [],    # 竞价后抢筹
    '09:41-10:00': [],    # 首次冲高
    '10:01-10:30': [],    # 冲板/回封段
    '10:31-11:00': [],    # 二次冲高
    '11:01-11:30': [],    # 早盘收尾
    '13:01-13:30': [],    # 午后开盘
    '13:31-14:00': [],    # 午后延续
    '14:01-15:00': [],    # 尾盘
}

for d in dates:
    df = df_min[df_min['date'] == d].reset_index(drop=True)
    if len(df) < 50:
        continue
    
    o = float(df['open'].iloc[0])
    c = float(df['close'].iloc[-1])
    high_vals = df['high'].astype(float)
    h = high_vals.max()
    high_idx = high_vals.idxmax()
    high_time = str(df.loc[high_idx, 'day']).split(' ')[-1]
    hh, mm = int(high_time.split(':')[0]), int(high_time.split(':')[1])
    total_min = hh * 60 + mm
    
    # 归类
    if total_min <= 580:    # <= 9:40
        bucket = '09:31-09:40'
    elif total_min <= 600:  # <= 10:00
        bucket = '09:41-10:00'
    elif total_min <= 630:  # <= 10:30
        bucket = '10:01-10:30'
    elif total_min <= 660:  # <= 11:00
        bucket = '10:31-11:00'
    elif total_min <= 690:  # <= 11:30
        bucket = '11:01-11:30'
    elif total_min <= 810:  # <= 13:30
        bucket = '13:01-13:30'
    elif total_min <= 840:  # <= 14:00
        bucket = '13:31-14:00'
    else:
        bucket = '14:01-15:00'
    
    fall = (1 - c/h) * 100
    time_buckets[bucket].append({
        'date': d, 'high': h, 'close': c, 'time': high_time, 'fall': fall,
        'open': o,
    })

print("=== 东山精密 日内最高点时段分布（8个完整交易日）===\n")

total = sum(len(v) for v in time_buckets.values())
for k in time_buckets:
    items = time_buckets[k]
    if items:
        avg_fall = np.mean([it['fall'] for it in items])
        print(f"【{k}】 {len(items)}次  平均回落{avg_fall:.1f}%")
        for it in items:
            d, t, hi, cl, fa = it['date'], it['time'], it['high'], it['close'], it['fall']
            print(f"  {d} {t} 高{hi:.0f}→收{cl:.0f}  回落{fa:.1f}%")
        print()

# 分组统计
print("=== 汇总 ===")
morning = sum(len(v) for k, v in time_buckets.items() if k.startswith('09') or k.startswith('10') or k.startswith('11'))
afternoon = sum(len(v) for k, v in time_buckets.items() if k.startswith('13') or k.startswith('14'))
print(f"上午见顶: {morning}次 ({morning/total*100:.0f}%)")
print(f"下午见顶: {afternoon}次 ({afternoon/total*100:.0f}%)")

# 冲高回落统计
all_falls = [it['fall'] for lst in time_buckets.values() for it in lst]
print(f"平均回落: {np.mean(all_falls):.1f}%, 最大: {max(all_falls):.1f}%, 最小: {min(all_falls):.1f}%")

# 涨停日特殊
for lst in time_buckets.values():
    for it in lst:
        if it['fall'] < 0.5:
            print(f"\n  涨停/近涨停: {it['date']} 高{it['high']:.0f}→收{it['close']:.0f}")
