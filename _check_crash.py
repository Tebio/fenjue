import akshare as ak
import pandas as pd

ds = ak.stock_zh_a_daily(symbol='sz002384', start_date='20260301', end_date='20260512', adjust='qfq')
sh = ak.stock_zh_a_daily(symbol='sh000001', start_date='20260301', end_date='20260512', adjust='')

df = ds[['date','close']].copy()
df.columns = ['date','ds_close']
df2 = sh[['date','close']].copy()
df2.columns = ['date','sh_close']
m = df.merge(df2, on='date')
m['ds_chg'] = m['ds_close'].pct_change() * 100
m['sh_chg'] = m['sh_close'].pct_change() * 100

print("=== 上证跌超-0.5% 且 东山上涨 ===")
cu = m[(m['sh_chg'] < -0.5) & (m['ds_chg'] > 0)]
print(f"共{len(cu)}次")
for _, r in cu.iterrows():
    print(f"  {r['date']} 东山{r['ds_chg']:+.2f}% 上证{r['sh_chg']:+.2f}%")

print("\n=== 上证跌超-0.5% 且 东山涨超2% ===")
cs = m[(m['sh_chg'] < -0.5) & (m['ds_chg'] > 2)]
print(f"共{len(cs)}次")
for _, r in cs.iterrows():
    print(f"  {r['date']} 东山{r['ds_chg']:+.2f}% 上证{r['sh_chg']:+.2f}%")

print()
ac = m[m['sh_chg'] < -0.5]
cd = m[(m['sh_chg'] < -0.5) & (m['ds_chg'] < 0)]
if len(ac) > 0:
    print(f"上证跌超-0.5%共{len(ac)}天, 东山逆涨{len(cu)}次({len(cu)/len(ac)*100:.0f}%), 跟跌{len(cd)}次({len(cd)/len(ac)*100:.0f}%)")
else:
    print("近2.5月无上证跌超-0.5%的日子")

# 放宽到-0.3%
print("\n=== 上证跌超-0.3% 全部 ===")
ac3 = m[m['sh_chg'] < -0.3]
cu3 = m[(m['sh_chg'] < -0.3) & (m['ds_chg'] > 0)]
print(f"上证跌超-0.3%共{len(ac3)}天, 东山逆涨{len(cu3)}次")
for _, r in ac3.iterrows():
    ds_c = r['ds_chg']
    tag = "🔥 逆涨" if ds_c > 0 else ""
    print(f"  {r['date']} 东山{ds_c:+.2f}% 上证{r['sh_chg']:+.2f}% {tag}")
