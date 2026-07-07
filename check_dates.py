#!/usr/bin/env python3
"""查特定票的突然逆市信号日期区间 + 最新价格"""
import json, urllib.request, ssl, time

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def get_data(sina):
    url = f'http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={sina}&scale=240&ma=no&datalen=200'
    req = urllib.request.Request(url, headers={'Referer':'https://finance.sina.com.cn'})
    resp = urllib.request.urlopen(req, context=ctx, timeout=12)
    return json.loads(resp.read().decode('utf-8'))

stocks = [
    ('sh600367', '红星发展'),
    ('sh600378', '昊华科技'),
    ('sh000636', '风华高科'),
    ('sh600726', '华电能源'),
    ('sh603011', '合锻智能'),
    ('sh603678', '火炬电子'),
]

for sina, name in stocks:
    try:
        data = get_data(sina)
        if not data or len(data) < 30:
            print(f'{name}: 数据不足')
            continue
        
        # 只取 2026年数据
        recent = [d for d in data if d['day'] >= '2026-05-01']
        if not recent:
            print(f'{name}: 无2026年数据')
            continue
        
        print(f'\n{"="*60}')
        print(f'{name} ({sina})')
        
        # 最近10天日K
        last10 = recent[-10:]
        print(f'  信号扫描日 (5/25附近) → 现在 (6/9):')
        print(f'  {\"日期\":<14} {\"收盘\":<8} {\"涨跌%\":<8}')
        
        prev = None
        for d in last10:
            c = float(d['close'])
            if prev:
                chg = (c - prev) / prev * 100
            else:
                chg = 0
            m = '🔥' if abs(chg) > 5 else ''
            print(f'  {d[\"day\"]:<14} {c:<8.2f} {chg:<+8.2f}% {m}')
            prev = c
        
        # 关键日期区间价格
        for label, target_dates in [('5/25附近', ['2026-05-25','2026-05-26','2026-05-27']),
                                      ('6/1附近',  ['2026-06-01','2026-06-02']),
                                      ('现在',      ['2026-06-09','2026-06-08'])]:
            found = None
            for td in target_dates:
                for d in data:
                    if d['day'] == td:
                        found = d
                        break
                if found:
                    break
            if found:
                print(f'  {label} ({found[\"day\"]}): 收盘 {float(found[\"close\"]):.2f}')
        
        time.sleep(0.2)
    except Exception as e:
        print(f'{name}: err {str(e)[:50]}')
        time.sleep(0.2)
