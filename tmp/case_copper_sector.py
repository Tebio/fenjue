import json
d = json.load(open('data/hithink/index_hist/885973.TI.json'))
bars = d.get('bars') or d.get('items') or d
if isinstance(bars, dict):
    for k, v in bars.items():
        if isinstance(v, list):
            bars = v; break
print('金属铜指数 bar数:', len(bars), '样例:', bars[0] if bars else None)
i0 = next((i for i, b in enumerate(bars) if b['date'] >= '2025-04-01'), None)
i7 = next((i for i, b in enumerate(bars) if b['date'] >= '2025-04-08'), None)
for label, i in [('2025-04-01', i0), ('2025-04-08(关税暴跌后)', i7)]:
    if i is None or i < 60:
        continue
    c = bars[i]['close']
    ma60 = sum(b['close'] for b in bars[i-60:i])/60
    r20 = c/bars[i-20]['close']-1
    r60 = c/bars[i-60]['close']-1
    print(f"{label}: 收{c:.2f} vs MA60 {c/ma60-1:+.1%} | 20日 {r20:+.1%} | 60日 {r60:+.1%}")
tail = bars[-1]
print(f"最新 {tail['date']} 收{tail['close']:.2f}，较2025-04-08 {tail['close']/bars[i7]['close']-1:+.1%}")
# 全年形态：4月暴跌后金属铜板块何时收复
base = next(b for i, b in enumerate(bars) if b['date'] >= '2025-04-03')
rec = next((b for b in bars if b['date'] > '2025-04-07' and b['close'] >= base['close']), None)
print(f"暴跌前(4/3)收{base['close']:.2f} → 收复日期: {rec['date'] if rec else '年内未收复'}")
