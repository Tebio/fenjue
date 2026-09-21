import json
ks = json.load(open('/opt/data/fenjue/data/big_kcache/001299.json'))
for k in ks[-12:]:
    print(k['date'], f"开{k['open']:.2f} 高{k['high']:.2f} 低{k['low']:.2f} 收{k['close']:.2f} 量{k['volume']/1e4:.0f}万")
c = [k['close'] for k in ks]
ma20 = sum(c[-20:]) / 20
ma60 = sum(c[-60:]) / 60
print(f'MA20={ma20:.2f} MA60={ma60:.2f} 现价={c[-1]:.2f} 成本9.675 浮盈{(c[-1]/9.675-1)*100:+.1f}%')
lo20 = min(k['low'] for k in ks[-20:])
print(f'20日最低={lo20:.2f}')