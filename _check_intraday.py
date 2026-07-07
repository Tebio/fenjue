import akshare as ak
import pandas as pd

ds = ak.stock_zh_a_daily(symbol='sz002384', start_date='20260301', end_date='20260512', adjust='qfq')
sh = ak.stock_zh_a_daily(symbol='sh000001', start_date='20260301', end_date='20260512', adjust='')

m = ds[['date','open','high','low','close']].copy()
s = sh[['date','close']].copy()
s.columns = ['date','sh_close']
merged = m.merge(s, on='date')
merged['sh_chg'] = merged['sh_close'].pct_change() * 100
merged['ds_chg'] = merged['close'].pct_change() * 100
merged['open_to_close'] = (merged['close'] / merged['open'] - 1) * 100
merged['open_to_high'] = (merged['high'] / merged['open'] - 1) * 100
merged['high_to_close'] = (merged['close'] / merged['high'] - 1) * 100

green = merged[merged['sh_chg'] < 0].dropna()
red = merged[merged['sh_chg'] > 0].dropna()

print("=== 大盘绿时，东山分时特征 ===")
print(f"共{len(green)}天")
print(f"开盘到收盘均值: {green['open_to_close'].mean():+.2f}%")
print(f"开盘到最高均值: {green['open_to_high'].mean():+.2f}%")
print(f"最高到收盘回落均值: {green['high_to_close'].mean():+.2f}%")
print()

print("=== 大盘红时，东山分时特征 ===")
print(f"共{len(red)}天")
print(f"开盘到收盘均值: {red['open_to_close'].mean():+.2f}%")
print(f"开盘到最高均值: {red['open_to_high'].mean():+.2f}%")
print(f"最高到收盘回落均值: {red['high_to_close'].mean():+.2f}%")
print()

# 微跌区间
micro = merged[(merged['sh_chg'] > -0.5) & (merged['sh_chg'] < 0)].dropna()
print(f"=== 大盘微跌0~-0.5% (东山最强) ===")
print(f"共{len(micro)}天, 东山均值{micro['ds_chg'].mean():+.2f}%")
for _, r in micro.iterrows():
    tag = '+++' if r['ds_chg'] > 2 else ''
    print(f"  {r['date']} 开{r['open']:.0f} 收{r['close']:.0f} ({r['open_to_close']:+.1f}%) 高{r['high']:.0f} 上证{r['sh_chg']:+.2f}% {tag}")
