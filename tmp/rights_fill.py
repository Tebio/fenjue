"""高送转抢权/填权实测（2026-09-29，tmp 探索级）。
源：东财 RPT_SHAREBONUS_DET（BONUS_IT_RATIO=每10股送转合计，EX_DIVIDEND_DATE=除权日，PLAN_NOTICE_DATE=预案公告日）。
两腿：抢权=公告次日开盘→除权日收盘；填权=除权次日开盘→T+20/60/120收盘。
口径：big_kcache 前复权（填权=前复权口径除权后上涨，即可投资问题本身）；对照=全部股票日同窗口前向收益 + 低送转组(0<送转<5)。
"""
import json
import time
from pathlib import Path

import requests

ROOT = Path('/opt/data/fenjue')
CACHE = ROOT / 'data' / 'sharebonus_events.json'
H = {'User-Agent': 'Mozilla/5.0'}
URL = ('https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_SHAREBONUS_DET'
       '&columns=ALL&pageSize=500&pageNumber={p}'
       "&filter=(EX_DIVIDEND_DATE>='2019-01-01')(EX_DIVIDEND_DATE<='2026-09-28')(BONUS_IT_RATIO>0)")

if CACHE.exists():
    events = json.loads(CACHE.read_text())
else:
    events, p = [], 1
    while True:
        d = requests.get(URL.format(p=p), headers=H, timeout=30).json()
        rows = (d.get('result') or {}).get('data') or []
        for r in rows:
            events.append({'code': r['SECURITY_CODE'], 'name': r['SECURITY_NAME_ABBR'],
                           'bir': r['BONUS_IT_RATIO'], 'ex': (r['EX_DIVIDEND_DATE'] or '')[:10],
                           'plan': (r['PLAN_NOTICE_DATE'] or '')[:10]})
        pages = (d.get('result') or {}).get('pages') or 1
        if p >= pages or not rows:
            break
        p += 1
        time.sleep(1.0)
    CACHE.write_text(json.dumps(events, ensure_ascii=False))
print(f"送转事件 {len(events)} 条（2019起）")

kcache = ROOT / 'data' / 'big_kcache'
import glob
import statistics as st

# 全部股票日前向收益基线（20/60/120日）
base = {20: [], 60: [], 120: []}
stock_bars = {}
for fp in glob.glob(str(kcache / '*.json')):
    code = fp.split('/')[-1].split('.')[0]
    if code[0] not in '06' or code.startswith(('300', '301', '688')):
        continue
    bars = json.load(open(fp))
    stock_bars[code] = bars
    for i in range(0, len(bars) - 121):
        o = bars[i + 1]['open']
        if o <= 0:
            continue
        for k in base:
            base[k].append(bars[i + 1 + k]['close'] / o - 1)

def fwd_stock(code, from_date, k):
    """from_date 之后首个交易日开盘买 → k 交易日后收盘"""
    bars = stock_bars.get(code)
    if not bars:
        return None
    for i, b in enumerate(bars):
        if b['date'] > from_date and i + k < len(bars) and b['open'] > 0:
            return bars[i + k]['close'] / b['open'] - 1
    return None

def span_ret(code, from_date, to_date):
    """公告次日开盘 → 除权日收盘（抢权腿）"""
    bars = stock_bars.get(code)
    if not bars:
        return None
    entry = exit_ = None
    for b in bars:
        if entry is None and b['date'] > from_date and b['open'] > 0:
            entry = b['open']
        if b['date'] <= to_date:
            exit_ = b['close']
    if entry and exit_:
        return exit_ / entry - 1
    return None

groups = {'高送转(≥5)': [e for e in events if e['bir'] >= 5],
          '低送转(<5)': [e for e in events if 0 < e['bir'] < 5]}
for gname, evs in groups.items():
    print(f"\n== {gname} 填权腿（除权次日开盘买） n事件={len(evs)}")
    for k in (20, 60, 120):
        rets = [r for e in evs if (r := fwd_stock(e['code'], e['ex'], k)) is not None]
        if rets:
            wr = sum(1 for x in rets if x > 0) / len(rets) * 100
            b = base[k]
            bwr = sum(1 for x in b if x > 0) / len(b) * 100
            print(f"  T+{k}: n={len(rets)} 胜率{wr:.0f}% 均值{st.mean(rets)*100:+.2f}% | 基线 {bwr:.0f}%/{st.mean(b)*100:+.2f}%")
    print(f"  抢权腿（公告次日开盘→除权收盘）:")
    rets = [r for e in evs if e['plan'] and e['ex'] and (r := span_ret(e['code'], e['plan'], e['ex'])) is not None]
    if rets:
        wr = sum(1 for x in rets if x > 0) / len(rets) * 100
        print(f"  n={len(rets)} 胜率{wr:.0f}% 均值{st.mean(rets)*100:+.2f}% 中位{st.median(rets)*100:+.2f}%")

print("\n== 高送转填权腿分年验尸（T+60）")
years = {}
for e in groups['高送转(≥5)']:
    r = fwd_stock(e['code'], e['ex'], 60)
    if r is not None:
        years.setdefault(e['ex'][:4], []).append(r)
for y in sorted(years):
    v = years[y]
    wr = sum(1 for x in v if x > 0) / len(v) * 100
    print(f"  {y}: n={len(v)} 胜率{wr:.0f}% 均值{st.mean(v)*100:+.2f}%")
