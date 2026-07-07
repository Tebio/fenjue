import akshare as ak
import numpy as np

df_min = ak.stock_zh_a_minute(symbol='sz002384', period='1')
df_min['date'] = df_min['day'].astype(str).str[:10]
dates = sorted(df_min['date'].unique())
print(f"分钟K覆盖 {len(dates)} 天: {dates[0]} ~ {dates[-1]}")

time_buckets = {
    '09:31-09:40': 0, '09:41-10:00': 0, '10:01-10:30': 0,
    '10:31-11:00': 0, '11:01-11:30': 0, '13:01-13:30': 0,
    '13:31-14:00': 0, '14:01-14:30': 0, '14:31-15:00': 0,
}

results = []
for d in dates:
    df = df_min[df_min['date'] == d]
    if len(df) < 30:
        continue
    df = df.reset_index(drop=True)
    
    o = float(df['open'].iloc[0])
    c = float(df['close'].iloc[-1])
    
    # 找最高点
    high_vals = df['high'].astype(float)
    h = high_vals.max()
    high_idx = high_vals.idxmax()
    high_time = df.loc[high_idx, 'day']
    time_str = str(high_time).split(' ')[-1]
    hh = int(time_str.split(':')[0])
    mm = int(time_str.split(':')[1])
    
    # 时段归类
    if hh == 9 or (hh == 10 and mm <= 0):
        bucket = '09:31-09:40' if mm <= 40 else '09:41-10:00'
    elif hh == 10 and mm <= 30:
        bucket = '10:01-10:30'
    elif hh == 10 or (hh == 11 and mm <= 0):
        bucket = '10:31-11:00'
    elif hh == 11:
        bucket = '11:01-11:30'
    elif hh == 13 and mm <= 30:
        bucket = '13:01-13:30'
    elif hh == 13 or (hh == 14 and mm <= 0):
        bucket = '13:31-14:00'
    elif hh == 14 and mm <= 30:
        bucket = '14:01-14:30'
    else:
        bucket = '14:31-15:00'
    time_buckets[bucket] += 1
    
    # 找早盘（到11:00前）vs 午盘
    # 按时间拆分
    morning_end = None
    for i, row in df.iterrows():
        t = str(row['day']).split(' ')[-1]
        if t >= '11:00:00':
            morning_end = i
            break
    if morning_end is None:
        morning_end = len(df) // 2
    
    morning_high_idx = df['high'].astype(float).iloc[:morning_end].idxmax()
    afternoon_high_idx = df['high'].astype(float).iloc[morning_end:].idxmax()
    
    morning_high = float(df.loc[morning_high_idx, 'high'])
    afternoon_high = float(df.loc[afternoon_high_idx, 'high'])
    
    morning_chg = (morning_high / o - 1) * 100
    afternoon_chg = (float(df['close'].iloc[-1]) / o - 1) * 100
    
    results.append({
        'date': d, '开': o, '高': h, '收': c,
        '最高时间': time_str, 'bucket': bucket,
        '早盘高': f"{morning_high:.1f}({morning_chg:+.1f}%)",
        '从高回落': f"{(1-c/h)*100:.1f}%",
    })

print("\n=== 日内最高点时段分布（9天）===")
for k in time_buckets:
    v = time_buckets[k]
    bar = '█' * v if v > 0 else ''
    print(f"  {k}: {v}次 {bar}")

print("\n=== 逐日明细 ===")
for r in results:
    print(f"  {r['date']} 开{r['开']:.0f} 高{r['高']:.0f}@{r['最高时间']}({r['bucket']})→收{r['收']:.0f} | 早盘高点{r['早盘高']} | 回落{r['从高回落']}")

# 10:00前见顶 vs 10:00后
before10 = sum(1 for r in results if r['bucket'] in ['09:31-09:40','09:41-10:00'])
after10 = sum(1 for r in results if r['bucket'] not in ['09:31-09:40','09:41-10:00'])
print(f"\n10:00前见顶: {before10}次, 10:00后见顶: {after10}次")

# 上午 vs 下午
am = sum(1 for r in results if r['bucket'].startswith('09') or r['bucket'].startswith('10') or r['bucket'].startswith('11'))
pm = sum(1 for r in results if r['bucket'].startswith('13') or r['bucket'].startswith('14'))
print(f"上午见顶: {am}次, 下午见顶: {pm}次")
