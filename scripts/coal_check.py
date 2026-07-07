#!/usr/bin/env python3
"""查煤炭板块成分股实时行情"""
import urllib.request, json, ssl
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

# 东财煤炭板块指数 BK0437
bk_code = 'BK0437'

# 成分股
stock_url = f'https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=50&po=1&np=1&ut=bd1d9ddb04089700cf9c27f6f7426281&fltt=2&invt=2&fid=f3&fs=b:{bk_code}+f:!50&fields=f12,f14,f2,f3,f4,f15,f16,f18,f20,f24,f8'
req = urllib.request.Request(stock_url, headers={'User-Agent':'Mozilla/5.0'})
resp = urllib.request.urlopen(req, context=ctx, timeout=8)
data = json.loads(resp.read())
stocks = data.get('data',{}).get('diff',[])

print(f"{'代码':>8} {'名称':<8} {'现价':<8} {'涨%':<8} {'额(亿)':<10} {'换手%':<8}")
print("-"*60)
for s in stocks:
    code = s.get('f12','')
    name = s.get('f14','')
    price = f"{s.get('f2',0):.2f}" if s.get('f2') else '--'
    pct = s.get('f3',0)
    amt = round((s.get('f20',0) or 0)/1e8, 2)
    turnover = f"{s.get('f24',0):.2f}" if s.get('f24') else '--'
    print(f"{code:>8} {name:<8} {price:<8} {pct:+.2f}%  {amt:<10.2f} {turnover:<8}")
PYEOF