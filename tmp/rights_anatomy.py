"""高送转赢家解剖（2026-09-29，tmp 探索级）：抢权/填权的大赢票凭什么？
纪律：赢家解剖五步法（赔率先行→当日特征零差异就停→细分找分水岭→金股/妖股族交叉→分年）。
字段（送转表自带）：EPS/净利同比/总股本/每股资本公积 + kcache 算位置/前涨幅/regime。
"""
import glob
import json
import statistics as st
import time
from pathlib import Path

import requests

ROOT = Path('/opt/data/fenjue')
CACHE = ROOT / 'data' / 'sharebonus_events_full.json'
H = {'User-Agent': 'Mozilla/5.0'}
URL = ('https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_SHAREBONUS_DET'
       '&columns=ALL&pageSize=500&pageNumber={p}'
       "&filter=(EX_DIVIDEND_DATE>='2019-01-01')(EX_DIVIDEND_DATE<='2026-09-28')(BONUS_IT_RATIO>=5)")

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
                           'plan': (r['PLAN_NOTICE_DATE'] or '')[:10],
                           'eps': r.get('BASIC_EPS'), 'np_yoy': r.get('PNP_YOY_RATIO'),
                           'shares': r.get('TOTAL_SHARES'), 'cap_res': r.get('PER_CAPITAL_RESERVE')})
        pages = (d.get('result') or {}).get('pages') or 1
        if p >= pages or not rows:
            break
        p += 1
        time.sleep(1.0)
    CACHE.write_text(json.dumps(events, ensure_ascii=False))
print(f"高送转(≥5)事件 {len(events)}")

tl = json.load(open(ROOT / 'data/regime_timeline_hcap.json'))
regime_of = {d['date']: d.get('regime') for d in tl} if isinstance(tl, list) else {}
gold = set()
for fp in glob.glob(str(ROOT / 'data/gold_stock_cache/*.json')):
    mo = Path(fp).stem
    for r in json.loads(open(fp).read()):
        gold.add((r['code'], mo))  # (code, 年月)

stock_bars = {}
for fp in glob.glob(str(ROOT / 'data/big_kcache/*.json')):
    code = fp.split('/')[-1].split('.')[0]
    if code[0] not in '06' or code.startswith(('300', '301', '688')):
        continue
    stock_bars[code] = json.load(open(fp))

def features(e):
    bars = stock_bars.get(e['code'])
    if not bars or not e['ex']:
        return None
    ei = None
    for i, b in enumerate(bars):
        if b['date'] > e['ex']:
            ei = i
            break
    if ei is None or ei + 60 >= len(bars) or ei < 65:
        return None
    o = bars[ei]['open']
    if o <= 0:
        return None
    c = [b['close'] for b in bars]
    ma60 = sum(c[ei - 60:ei]) / 60
    hi60 = max(b['high'] for b in bars[ei - 60:ei])
    t60 = bars[ei + 60]['close'] / o - 1
    pre20 = c[ei - 1] / c[ei - 21] - 1  # 除权前20日涨幅（已抢跑程度）
    # 抢权腿
    qg = None
    if e['plan']:
        entry = exit_ = None
        for b in bars:
            if entry is None and b['date'] > e['plan'] and b['open'] > 0:
                entry = b['open']
            if b['date'] <= e['ex']:
                exit_ = b['close']
        if entry and exit_:
            qg = exit_ / entry - 1
    ex_mo = e['ex'][:7]
    return {'code': e['code'], 'name': e['name'], 'bir': e['bir'], 'year': e['ex'][:4],
            't60': t60, 'qg': qg, 'pre20': pre20,
            'above_ma60': bars[ei - 1]['close'] > ma60,
            'dist_hi60': bars[ei - 1]['close'] / hi60 - 1,
            'regime': regime_of.get(e['ex'], '?'),
            'gold': (e['code'], ex_mo) in gold,
            'eps': e['eps'], 'np_yoy': e['np_yoy'], 'shares': e['shares'], 'cap_res': e['cap_res']}

F = [f for e in events if (f := features(e))]
print(f"可解剖事件 {len(F)}")

t60s = sorted(f['t60'] for f in F)
win_line = t60s[int(len(t60s) * 0.8)]
print(f"\n== 第零步 赔率结构：T+60 分布 中位{st.median(t60s)*100:+.1f}% 前20%线{win_line*100:+.1f}% 胜率{sum(1 for x in t60s if x>0)/len(t60s)*100:.0f}%")

def seg(label, pred):
    w = [f['t60'] for f in F if pred(f)]
    l = [f['t60'] for f in F if not pred(f)]
    if len(w) < 10 or len(l) < 10:
        print(f"  {label}: 样本不足 (n={len(w)}/{len(l)})")
        return
    wwr = sum(1 for x in w if x > 0) / len(w) * 100
    lwr = sum(1 for x in l if x > 0) / len(l) * 100
    wbig = sum(1 for x in w if x > win_line) / len(w) * 100
    lbig = sum(1 for x in l if x > win_line) / len(l) * 100
    print(f"  {label}: n={len(w)} 胜率{wwr:.0f}% 均{st.mean(w)*100:+.1f}% 大赢率{wbig:.0f}% | 对照 n={len(l)} 胜率{lwr:.0f}% 均{st.mean(l)*100:+.1f}% 大赢率{lbig:.0f}%")

print("\n== 细分（填权 T+60，大赢=前20%）")
seg("业绩高增长(净利同比>30%)", lambda f: f['np_yoy'] is not None and f['np_yoy'] > 30)
seg("业绩下滑(净利同比<0)", lambda f: f['np_yoy'] is not None and f['np_yoy'] < 0)
seg("EPS>0.5(业绩有支撑)", lambda f: f['eps'] is not None and f['eps'] > 0.5)
seg("小股本(<3亿股)", lambda f: f['shares'] is not None and f['shares'] < 3e8)
seg("高公积(每股>2元)", lambda f: f['cap_res'] is not None and f['cap_res'] > 2)
seg("超高送转(≥10)", lambda f: f['bir'] >= 10)
seg("MA60上方", lambda f: f['above_ma60'])
seg("贴60日高(距高>-10%)", lambda f: f['dist_hi60'] > -0.10)
seg("除权前已抢跑(前20日>15%)", lambda f: f['pre20'] > 0.15)
seg("除权前未抢跑(前20日<0)", lambda f: f['pre20'] < 0)
seg("妖股/主线期除权", lambda f: f['regime'] in ('妖股期', '主线期'))
seg("金股名单内(当月)", lambda f: f['gold'])

print("\n== 组合解剖：业绩高增+小股本 vs 业绩下滑+大股本")
a = [f for f in F if f['np_yoy'] is not None and f['np_yoy'] > 30 and f['shares'] is not None and f['shares'] < 3e8]
b = [f for f in F if f['np_yoy'] is not None and f['np_yoy'] < 0 and f['shares'] is not None and f['shares'] >= 3e8]
for name, grp in [('高增+小盘', a), ('下滑+大盘', b)]:
    if grp:
        t = [f['t60'] for f in grp]
        q = [f['qg'] for f in grp if f['qg'] is not None]
        wr = sum(1 for x in t if x > 0) / len(t) * 100
        print(f"  {name}: n={len(t)} 填权胜率{wr:.0f}% 均{st.mean(t)*100:+.1f}%" +
              (f" | 抢权均{st.mean(q)*100:+.1f}% 中位{st.median(q)*100:+.1f}%" if q else ""))

print("\n== 分年×净利同比（验证'真高送转'逻辑是否随年份稳定）")
for y in sorted({f['year'] for f in F}):
    g = [f for f in F if f['year'] == y and f['np_yoy'] is not None]
    hi = [f['t60'] for f in g if f['np_yoy'] > 30]
    lo = [f['t60'] for f in g if f['np_yoy'] <= 30]
    if hi and lo:
        print(f"  {y}: 高增 n={len(hi)} {st.mean(hi)*100:+.1f}% vs 其它 n={len(lo)} {st.mean(lo)*100:+.1f}%")
