import akshare as ak
import numpy as np

df_min = ak.stock_zh_a_minute(symbol='sz002384', period='1')
df_min['date'] = df_min['day'].astype(str).str[:10]
dates = sorted(df_min['date'].unique())

time_buckets = {
    '09:31-09:40': [], '09:41-10:00': [], '10:01-10:30': [],
    '10:31-11:00': [], '11:01-11:30': [], '13:01-13:30': [],
    '13:31-14:00': [], '14:01-14:30': [], '14:31-15:00': [],
}

for d in dates:
    df = df_min[df_min['date'] == d].reset_index(drop=True)
    if len(df) < 50:  # 需要完整交易日
        continue
    
    o = float(df['open'].iloc[0])
    c = float(df['close'].iloc[-1])
    high_vals = df['high'].astype(float)
    h = high_vals.max()
    high_idx = high_vals.idxmax()
    high_time = str(df.loc[high_idx, 'day']).split(' ')[-1]
    hh, mm = int(high_time.split(':')[0]), int(high_time.split(':')[1])
    
    # 归类到时段
    if hh == 9:
        bucket = '09:31-09:40'
    elif hh == 10 and mm <= 0:
        bucket = '09:41-10:00'
    elif hh == 10 and mm <= 30:
        bucket = '10:01-10:30'
    elif hh <= 11:
        bucket = '10:31-11:00' if hh == 10 else '11:01-11:30'
    elif hh == 13 and mm <= 30:
        bucket = '13:01-13:30'
    elif hh == 13:
        bucket = '13:31-14:00'
    elif hh == 14 and mm <= 30:
        bucket = '14:01-14:30'
    else:
        bucket = '14:31-15:00'
    
    time_buckets[bucket].append((d, f"{h:.0f}", high_time, f"{c:.0f}", f"{(1-c/h)*100:.1f}%"))

print("=== 东山精密 日内最高点时段分布（4/28-5/12 共8个完整日）===\n")
for k in time_buckets:
    items = time_buckets[k]
    if items:
        print(f"【{k}】 {len(items)}次")
        for d, h_val, t, c_val, fall in items:
            print(f"  {d} {t} 高{h_val} → 收{c_val} 回落{fall}")
    else:
        print(f"【{k}】 0次")

# 统计
all_items = [(k, v) for k, lst in time_buckets.items() for v in lst]
print(f"\n=== 关键统计 ===")
before10 = sum(1 for k, _ in all_items if k in ['09:31-09:40','09:41-10:00'])
between10_11 = sum(1 for k, _ in all_items if k in ['10:01-10:30','10:31-11:00','11:01-11:30'])
afternoon = sum(1 for k, _ in all_items if k.startswith('13') or k.startswith('14'))
print(f"10:00前见顶: {before10}次")
print(f"10:01-11:30见顶: {between10_11}次")
print(f"13:00后见顶: {afternoon}次")

# 计算回落
falls = [float(v[3].replace('%','')) for _, v in all_items]
print(f"平均从高点回落: {np.mean(falls):.1f}%")
