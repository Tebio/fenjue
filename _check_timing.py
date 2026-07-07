import akshare as ak
import pandas as pd
import numpy as np

df_min = ak.stock_zh_a_minute(symbol='sz002384', period='1')

# 可用交易日
days = df_min['day'].astype(str).unique()
print(f"分钟K覆盖 {len(days)} 个交易日: {days[0]} ~ {days[-1]}")

# 对每个交易日分析
results = []
time_buckets = {
    '09:31-09:40': 0,   # 开盘10分钟
    '09:41-10:00': 0,   # 9:41-10:00
    '10:01-10:30': 0,
    '10:31-11:00': 0,
    '11:01-11:30': 0,
    '13:01-13:30': 0,
    '13:31-14:00': 0,
    '14:01-14:30': 0,
    '14:31-15:00': 0,
}

for d in days:
    df = df_min[df_min['day'].astype(str).str.startswith(d)]
    if len(df) < 30:
        continue
    
    o = float(df['open'].iloc[0])
    h = float(df['high'].astype(float).max())
    c = float(df['close'].astype(float).iloc[-1])
    
    # 找到最高点的分钟
    high_idx = df['high'].astype(float).idxmax()
    high_time = df.loc[high_idx, 'day']
    
    # 提取时间部分
    time_str = str(high_time).split(' ')[-1] if ' ' in str(high_time) else str(high_time)
    hour = int(time_str.split(':')[0])
    minute = int(time_str.split(':')[1])
    
    # 时段分类
    if hour == 9 or (hour == 10 and minute <= 0):
        if minute <= 40:
            bucket = '09:31-09:40'
        else:
            bucket = '09:41-10:00'
    elif hour == 10 and minute <= 30:
        bucket = '10:01-10:30'
    elif hour == 10 or (hour == 11 and minute <= 0):
        bucket = '10:31-11:00'
    elif hour == 11:
        bucket = '11:01-11:30'
    elif hour == 13 and minute <= 30:
        bucket = '13:01-13:30'
    elif hour == 13 or (hour == 14 and minute <= 0):
        bucket = '13:31-14:00'
    elif hour == 14 and minute <= 30:
        bucket = '14:01-14:30'
    else:
        bucket = '14:31-15:00'
    
    time_buckets[bucket] += 1
    
    # 早盘涨幅 vs 下午涨幅
    mid = len(df) // 2
    morning_close = float(df['close'].iloc[mid])
    morning_chg = (morning_close / o - 1) * 100
    afternoon_chg = (c / morning_close - 1) * 100
    
    results.append({
        'date': d.split(' ')[0],
        '开': o,
        '高': h,
        '收': c,
        '最高时间': time_str,
        '早盘涨': f"{morning_chg:+.1f}%",
        '下午涨': f"{afternoon_chg:+.1f}%",
        '冲高回落': f"{(1-c/h)*100:.1f}%",
    })

print("\n=== 日内最高点时间段分布 ===")
total = sum(time_buckets.values())
for k, v in time_buckets.items():
    bar = '█' * v
    print(f"  {k}: {v}次 {bar}")

print("\n=== 逐日明细 ===")
for r in results:
    print(f"  {r['date']} 开{r['开']:.0f}→高{r['高']:.0f}({r['最高时间']})→收{r['收']:.0f} | 早盘{r['早盘涨']} 下午{r['下午涨']} | 从高回落{r['冲高回落']}")

# 统计冲高后的走势
print("\n=== 关键时段统计 ===")
# 9:31-9:40 冲高后：如果高点在开盘10分钟内，之后怎么走
early_high_dates = [r for r in results if r['最高时间'].startswith('09:3')]
if early_high_dates:
    print(f"开盘10分钟内见顶: {len(early_high_dates)}次")
    for r in early_high_dates:
        print(f"  {r['date']} 高{r['高']:.0f}→收{r['收']:.0f} 回落{r['冲高回落']}")

# 早盘 vs 下午统计
morning_vals = [float(r['早盘涨'].replace('%','')) for r in results]
afternoon_vals = [float(r['下午涨'].replace('%','')) for r in results]
print(f"\n早盘平均涨幅: {np.mean(morning_vals):+.1f}%")
print(f"下午平均涨幅: {np.mean(afternoon_vals):+.1f}%")
