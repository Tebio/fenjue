#!/usr/bin/env python3
"""三阶段模拟 — 5/8 9:25→9:40 防偷看未来版
T-1池: pool_20260507.json (5/7收盘)
K线: Sina分钟K线 2026-05-08
"""
import os, sys, json, time
from collections import Counter

for k in list(os.environ.keys()):
    if 'proxy' in k.lower(): del os.environ[k]

import akshare as ak

SIM_DAY = '2026-05-08'
T1_POOL = '/opt/data/fenjue/pool_20260507.json'
OUT_DIR = '/opt/data/fenjue/sim'

def to_sina(code):
    c = str(code)
    return ('sh' if c[0] == '6' else 'sz') + c

def load_pool():
    with open(T1_POOL) as fh:
        data = json.load(fh)
    return data['results']

def get_minute(sina_code):
    df = ak.stock_zh_a_minute(symbol=sina_code, period='1')
    df['day_str'] = df['day'].astype(str)
    return df[df['day_str'].str.startswith(SIM_DAY)]

# ── Phase 1: 竞价初筛 ──
print(f'\n{"="*60}')
print(f'🔔 Phase 1: 竞价初筛 (2026-05-08 9:25) — T-1池 pool_20260507')
print(f'{"="*60}\n')

pool = load_pool()
candidates = pool[:80]  # 取前80只
results = []
errors = 0
start = time.time()

for i, stock in enumerate(candidates):
    code = stock['code']
    try:
        minute = get_minute(to_sina(code))
        if len(minute) == 0:
            errors += 1
            time.sleep(0.15)
            continue
        first = minute.iloc[0]
        open_price = float(first['open'])
        prev_close = stock['price']  # 5/7收盘 = 正确的前收盘
        gap_pct = (open_price - prev_close) / prev_close * 100
        if gap_pct > 1:
            results.append(dict(
                code=code, name=stock['name'],
                prev_close=prev_close, open=round(open_price, 2),
                gap_pct=round(gap_pct, 2),
                vol_1st=int(first['volume']),
                sector=stock.get('sector', ''),
                amount_yi=stock.get('amount_yi', 0),
            ))
    except Exception as e:
        errors += 1
    time.sleep(0.15)
    if (i+1) % 20 == 0:
        elapsed = time.time() - start
        print(f'  {i+1}/{len(candidates)} ({elapsed:.0f}s) 高开{len(results)} 错{errors}', flush=True)

results.sort(key=lambda x: x['gap_pct'], reverse=True)
elapsed = time.time() - start
print(f'\n🔔 竞价结果 ({elapsed:.0f}s): {len(results)}只高开>1% | 错{errors}\n')

for r in results[:25]:
    print(f"  {r['code']} {r['name']:<8} 昨收{r['prev_close']} → 开{r['open']} (+{r['gap_pct']}%) 首分{r['vol_1st']}手 {r['sector']}")

os.makedirs(OUT_DIR, exist_ok=True)
with open(os.path.join(OUT_DIR, 'phase1_0508.json'), 'w') as fh:
    json.dump({'date': '20260508', 'count': len(results), 'elapsed': round(elapsed), 'results': results}, fh, ensure_ascii=False, indent=2)

if not results:
    print('\n⚠️ Phase1无高开票，终止')
    sys.exit(0)

# ── Phase 2: 9:40 防骗炮 ──
print(f'\n{"="*60}')
print(f'✅ Phase 2: 骗炮验证 (2026-05-08 9:40)')
print(f'{"="*60}\n')

candidates = results[:30]
print(f'📋 Phase1: {len(results)}只 → 验证前{len(candidates)}只\n')

verified = []
failed = []
start = time.time()

for i, stock in enumerate(candidates):
    code = stock['code']
    try:
        minute = get_minute(to_sina(code))
        if len(minute) < 10:
            failed.append({**stock, 'reason': f'K线不足({len(minute)}条)'})
            continue
        first10 = minute.head(10)
        closes = [float(x) for x in first10['close']]
        highs = [float(x) for x in first10['high']]
        total_vol = int(first10['volume'].sum())

        open_price = stock['open']
        latest = closes[-1]
        highest = max(highs)
        from_open = (latest - open_price) / open_price * 100
        from_high = (latest - highest) / highest * 100

        reasons = []
        if from_open < -1:
            reasons.append(f'高开低走({from_open:+.1f}%)')
        if from_high < -3:
            reasons.append(f'冲高回落({from_high:+.1f}%)')
        if total_vol < 10000:
            reasons.append(f'缩量({total_vol}手)')

        if reasons:
            failed.append({**stock, 'reason': '; '.join(reasons), 'from_open': round(from_open,2), 'latest': round(latest,2)})
        else:
            verified.append(dict(
                code=code, name=stock['name'],
                prev_close=stock['prev_close'], open=open_price,
                latest=round(latest, 2), gap_pct=stock['gap_pct'],
                from_open=round(from_open, 2), total_vol=total_vol,
                sector=stock['sector'],
            ))
    except Exception as e:
        failed.append({**stock, 'reason': str(e)[:60]})

    if (i+1) % 5 == 0:
        print(f'  验证 {i+1}/{len(candidates)} 通过{len(verified)} 排除{len(failed)}', flush=True)

elapsed = time.time() - start
verified.sort(key=lambda x: x['from_open'], reverse=True)

# ── 输出 ──
print(f'\n{"="*60}')
print(f'🎯 最终出击 ({elapsed:.0f}s): {len(verified)}只')
print(f'{"="*60}\n')

# 读取5/8收盘池做最终表现对比
try:
    with open('/opt/data/fenjue/pool_20260508.json') as fh:
        p8 = {r['code']: r for r in json.load(fh)['results']}
except:
    p8 = {}

for v in verified:
    close_info = p8.get(v['code'], {})
    close_pct = close_info.get('pct', 0)
    mark = '🔥' if close_pct > 5 else ('✅' if close_pct > 0 else '❌')
    print(f"  {mark} {v['code']} {v['name']:<8} 开{v['open']} 9:40价{v['latest']} "
          f"(高开{v['gap_pct']}%, 开盘后{v['from_open']:+.1f}%) 量{v['total_vol']}手 {v['sector']} "
          f"→ 收盘{close_pct:+.1f}%")

if failed:
    print(f'\n❌ 骗炮排除: {len(failed)}只')
    for f in failed:
        print(f"  ❌ {f['code']} {f['name']:<8} {f.get('reason','?')}")

# ── 板块分析 ──
if verified:
    sectors = Counter(v['sector'] for v in verified)
    print(f'\n📊 板块聚合:')
    for sec, cnt in sectors.most_common(8):
        names = [v['name'] for v in verified if v['sector'] == sec]
        print(f"  {sec}: {cnt}只 — {', '.join(names)}")

with open(os.path.join(OUT_DIR, 'phase2_0508.json'), 'w') as fh:
    json.dump({'date': '20260508', 'verified': len(verified), 'failed': len(failed),
               'results': verified, 'excluded': failed}, fh, ensure_ascii=False, indent=2)

print(f'\n💾 结果已保存 sim/phase2_0508.json')
