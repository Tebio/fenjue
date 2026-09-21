import json
anchors = [('601838', '成都银行', 0.052), ('600919', '江苏银行', 0.048), ('601229', '上海银行', 0.055),
           ('601077', '渝农商行', 0.050), ('000333', '美的集团', 0.045)]
for code, nm, dy in anchors:
    ks = json.load(open(f'/opt/data/fenjue/data/big_kcache/{code}.json'))
    d25 = [k for k in ks if k['date'] < '2025-01-01']
    d26 = [k for k in ks if k['date'] < '2026-01-01']
    last = ks[-1]
    r25 = d26[-1]['close'] / d25[-1]['close'] - 1 if d25 and d26 else None
    r26 = last['close'] / d26[-1]['close'] - 1 if d26 else None
    print(f'{nm}: 2025价格{100*r25:+.1f}% 2026YTD{100*r26:+.1f}% | 加股息后≈2025 {100*(r25+dy):+.1f}% / 2026 {100*(r26+dy*0.75):+.1f}%')