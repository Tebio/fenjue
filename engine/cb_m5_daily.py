"""#86b 转债5m前向攒数（每晚）：当日涨停股+其转债的 5m K线落盘
目的：为股债联动 5m drift（+2.14%/n=146 首读）攒跨 regime 样本，2-3月后终审。
轻量：每天只拉 涨停股(~40) + 对应转债(~40)，~2分钟。
产出: data/cb_m5/<日期>/stock_<code>.json / bond_<code>.json
"""
import json, time, sys, urllib.request, datetime
from pathlib import Path
from collections import defaultdict

ROOT = Path('/opt/data/fenjue')
OUT = ROOT / 'data/cb_m5'

def sina_m5(symbol, n=48):
    url = ('https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/'
           f'CN_MarketData.getKLineData?symbol={symbol}&scale=5&ma=no&datalen={n}')
    req = urllib.request.Request(url, headers={'Referer': 'https://finance.sina.com.cn/'})
    for _ in range(3):
        try:
            return json.loads(urllib.request.urlopen(req, timeout=15).read())
        except Exception:
            time.sleep(2)
    return None

def main():
    import os
    for k in list(os.environ):
        if 'proxy' in k.lower(): os.environ.pop(k)
    today = datetime.date.today().isoformat()
    outdir = OUT / today
    # 今日涨停股（周期仪 boards 已落盘）
    rl = ROOT / 'data/regime_log.jsonl'
    last = json.loads(rl.read_text().strip().splitlines()[-1])
    if last['date'] != today:
        print(f'非交易日或周期仪未跑（{last["date"]}），跳过')
        return 0
    stocks = [b['code'] for b in last.get('boards', [])]
    if not stocks:
        print('今日无涨停，跳过')
        return 0
    sys.path.insert(0, '/opt/data/python-libs')
    import akshare as ak
    df = ak.bond_zh_cov()
    s2b = {}
    for _, r in df.iterrows():
        s2b.setdefault(str(r['正股代码']).zfill(6), []).append(str(r['债券代码']).zfill(6))
    outdir.mkdir(parents=True, exist_ok=True)
    got_s = got_b = 0
    for c in stocks:
        d = sina_m5(('sh' if c.startswith('6') else 'sz') + c)
        if d:
            (outdir / f'stock_{c}.json').write_text(json.dumps(d))
            got_s += 1
        time.sleep(0.7)
        for bond in s2b.get(c, []):
            d2 = sina_m5(('sh' if bond.startswith('11') else 'sz') + bond)
            if d2:
                (outdir / f'bond_{bond}.json').write_text(json.dumps(d2))
                got_b += 1
            time.sleep(0.7)
    print(f'{today}: 涨停股 {got_s}/{len(stocks)}、转债 {got_b} 只 5m 落盘')
    return 0

if __name__ == '__main__':
    sys.exit(main())
