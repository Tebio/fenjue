import akshare as ak
import pandas as pd

df_daily = ak.stock_zh_a_daily(symbol='sh601677', start_date='20251101', end_date='20260522', adjust='qfq')
df_daily['date_str'] = df_daily['date'].astype(str)

df_min = ak.stock_zh_a_minute(symbol='sh601677', period='1')
for col in ['open','close','high','low','volume']:
    df_min[col] = pd.to_numeric(df_min[col], errors='coerce')
df_min['date'] = df_min['day'].astype(str).str[:10]

dates = sorted(df_min['date'].unique())
print("分钟K日期:", dates)
print("日K日期数:", len(df_daily))

records = []
for d in dates:
    day = df_min[df_min['date']==d].dropna(subset=['open','close','high','low'])
    if len(day) < 60: continue
    open_p = float(day['open'].iloc[0])
    close_p = float(day['close'].iloc[-1])
    high = float(day['high'].max())
    low = float(day['low'].min())
    pct = (close_p - open_p) / open_p * 100
    high_pct = (high - open_p) / open_p * 100
    fade = (close_p - high) / high * 100
    records.append({'date':d,'open':open_p,'close':close_p,'high':high,
                    'high_pct':high_pct,'pct':pct,'fade':fade})

df_rec = pd.DataFrame(records)

print()
for _, r in df_rec.iterrows():
    print("{} | open:{:.2f} high:{:.2f} close:{:.2f} | high_pct:{:+.1f}% pct:{:+.1f}% fade:{:+.1f}%".format(
        r['date'], r['open'], r['high'], r['close'], r['high_pct'], r['pct'], r['fade']))

# Match: high > 4%, fade < -1.5%, pct > 0.5%
similar = df_rec[(df_rec['high_pct'] > 4) & (df_rec['fade'] < -1.5) & (df_rec['pct'] > 0.5)]
print("\n匹配(冲高>4%+回落>1.5%+收阳):", len(similar), "天")

daily = df_daily.set_index('date_str')['close'].to_dict()
dates_sorted = sorted(daily.keys())

for _, row in similar.iterrows():
    d = row['date']
    idx = None
    for i, dd in enumerate(dates_sorted):
        if dd == d: idx = i; break
    if idx is not None and idx + 1 < len(dates_sorted):
        today_close = daily[dates_sorted[idx]]
        next_close = daily[dates_sorted[idx + 1]]
        next_pct = (next_close - today_close) / today_close * 100
        c = 'RED' if next_pct > 0 else 'GREEN'
        print("{}  high:{:+.1f}%  close:{:+.1f}%  fade:{:+.1f}%  -> next:{:+.1f}%  {}".format(
            d, row['high_pct'], row['pct'], row['fade'], next_pct, c))

# All fade < -2%
print("\n=== 所有fade<-2% ===")
fade_all = df_rec[df_rec['fade'] < -2]
red = green = 0
for _, row in fade_all.iterrows():
    d = row['date']
    idx = None
    for i, dd in enumerate(dates_sorted):
        if dd == d: idx = i; break
    if idx is not None and idx + 1 < len(dates_sorted):
        today_close = daily[dates_sorted[idx]]
        next_close = daily[dates_sorted[idx + 1]]
        next_pct = (next_close - today_close) / today_close * 100
        c = 'RED' if next_pct > 0 else 'GREEN'
        if next_pct > 0: red += 1
        else: green += 1
        print("{} fade:{:+.1f}% -> next:{:+.1f}% {}".format(d, row['fade'], next_pct, c))

if red + green > 0:
    print("红:", red, "绿:", green, "红率:", round(red/(red+green)*100), "%")
