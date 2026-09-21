import json
for code, nm in [('600127', '金健米业'), ('601086', '国芳集团')]:
    ks = json.load(open(f'/opt/data/fenjue/data/big_kcache/{code}.json'))
    print(f'== {nm} {code} 近3个月 ==')
    for i in range(1, len(ks)):
        k = ks[i]
        if k['date'] < '2026-06-01':
            continue
        pct = (k['close'] / ks[i - 1]['close'] - 1) * 100
        if abs(pct) >= 5:
            print(f"  {k['date']} {pct:+.1f}% 收{k['close']:.2f}")