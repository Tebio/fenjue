import akshare as ak
import pandas as pd

ds = ak.stock_zh_a_daily(symbol='sz002384', start_date='20260301', end_date='20260512', adjust='qfq')
sh = ak.stock_zh_a_daily(symbol='sh000001', start_date='20260301', end_date='20260512', adjust='')

m = ds[['date','close']].copy(); m.columns=['date','ds_close']
s = sh[['date','close']].copy(); s.columns=['date','sh_close']
merged = m.merge(s, on='date')
merged['ds_chg'] = merged['ds_close'].pct_change() * 100
merged['sh_chg'] = merged['sh_close'].pct_change() * 100

# 分组统计
red = merged[merged['sh_chg'] > 0]
green = merged[merged['sh_chg'] < 0]

print(f"=== 大盘红 vs 绿，东山平均涨幅 ===")
print(f"大盘红（{len(red)}天）：东山平均涨幅 {red['ds_chg'].mean():+.2f}%")
print(f"大盘绿（{len(green)}天）：东山平均涨幅 {green['ds_chg'].mean():+.2f}%")

# 细分
print(f"\n=== 按大盘级别细分 ===")
for (lo, hi, label) in [(-10, -1, '暴跌-1%以上'), (-1, -0.5, '小跌-0.5~-1%'), (-0.5, 0, '微跌0~-0.5%'),
                          (0, 0.5, '微涨0~+0.5%'), (0.5, 1, '小涨+0.5~+1%'), (1, 10, '大涨+1%以上')]:
    seg = merged[(merged['sh_chg'] > lo) & (merged['sh_chg'] <= hi)]
    if len(seg) > 0:
        print(f"  上证{label}: {len(seg)}天, 东山均值{seg['ds_chg'].mean():+.2f}%, 中位{seg['ds_chg'].median():+.2f}%")
