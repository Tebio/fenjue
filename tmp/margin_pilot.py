"""个股两融横截面试点（2026-09-29，tmp）：融资余额占流通比(RZYEZB)+融资净买(RZJME/SZ) 五分位 → T+20。
15 个抽样日（2024-07~2026-09 月度），决策用：有梯度→建全量管道；平→封箱不建。
"""
import glob
import json
import statistics as st
import time

import requests

H = {'User-Agent': 'Mozilla/5.0'}
URL = ('https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPTA_WEB_RZRQ_GGMX'
       '&columns=ALL&pageSize=500&pageNumber={p}&sortColumns=DATE&sortTypes=-1'
       "&filter=(DATE='{d}')")

DATES = ['2024-07-15', '2024-08-15', '2024-09-13', '2024-10-15', '2024-11-15', '2024-12-13',
         '2025-01-15', '2025-03-14', '2025-05-15', '2025-07-15', '2025-09-15',
         '2025-11-14', '2026-01-15', '2026-03-13', '2026-05-15', '2026-07-15', '2026-09-15']

bars_of = {}
for fp in glob.glob('/opt/data/fenjue/data/big_kcache/*.json'):
    code = fp.split('/')[-1].split('.')[0]
    if code[0] not in '06' or code.startswith(('300', '301', '688')):
        continue
    bars_of[code] = json.load(open(fp))

def fwd20(code, day):
    bars = bars_of.get(code)
    if not bars:
        return None
    for i, b in enumerate(bars):
        if b['date'] > day and b['open'] > 0 and i + 20 < len(bars):
            return bars[i + 20]['close'] / b['open'] - 1
    return None

records = []
for d in DATES:
    p, got = 1, 0
    while True:
        try:
            r = requests.get(URL.format(p=p, d=d), headers=H, timeout=30).json()
        except Exception:
            break
        rows = (r.get('result') or {}).get('data') or []
        for x in rows:
            code = x['SCODE']
            if code[0] not in '06' or code.startswith(('300', '301', '688')) or not x.get('SZ'):
                continue
            records.append({'date': d, 'code': code, 'rzyezb': x.get('RZYEZB'),
                            'rzjme_sz': (x.get('RZJME') or 0) / x['SZ'] * 100})
            got += 1
        pages = (r.get('result') or {}).get('pages') or 1
        if p >= pages or not rows:
            break
        p += 1
        time.sleep(1.0)
    print(f"{d}: {got} 只", flush=True)

print(f"\n总记录 {len(records)}")
for r in records:
    r['fwd'] = fwd20(r['code'], r['date'])
records = [r for r in records if r['fwd'] is not None and r['rzyezb'] is not None]
print(f"有效（有T+20） {len(records)}")

def quintile_report(key, label):
    vals = sorted(r[key] for r in records)
    n = len(vals)
    buckets = [[] for _ in range(5)]
    for r in records:
        q = min(4, sum(1 for v in vals if v < r[key]) * 5 // n)
        buckets[q].append(r['fwd'])
    print(f"\n== {label} 五分位 → T+20")
    for i, b in enumerate(buckets):
        wr = sum(1 for x in b if x > 0) / len(b) * 100
        print(f"  Q{i+1}: n={len(b)} 胜率{wr:.0f}% 均值{st.mean(b)*100:+.2f}% 中位{st.median(b)*100:+.2f}%")

quintile_report('rzyezb', '融资余额占流通比(杠杆拥挤度)')
quintile_report('rzjme_sz', '单日融资净买/流通市值(杠杆资金流)')
