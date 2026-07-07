#!/usr/bin/env python3
"""三阶段模拟 v2 — Sina源分钟K线"""
import os, sys, json, time

for k in list(os.environ.keys()):
    if 'proxy' in k.lower(): del os.environ[k]

import akshare as ak
import pandas as pd

SIM_DATE = '20260508'
SIM_DAY = '2026-05-08'
POOL_FILE = f'/opt/data/fenjue/pool_{SIM_DATE}.json'
OUT_DIR = '/opt/data/fenjue/sim'

def load_pool():
    with open(POOL_FILE) as fh:
        data = json.load(fh)
    return data['results']

def to_sina(code):
    c = str(code)
    return ('sh' if c[0] == '6' else 'sz') + c

def get_minute_data(sina_code):
    """获取某只股票的分钟K线，筛选当天数据"""
    df = ak.stock_zh_a_minute(symbol=sina_code, period='1')
    df['day_str'] = df['day'].astype(str)
    return df[df['day_str'].str.startswith(SIM_DAY)]

def phase1_sim():
    """用Sina分钟K线模拟竞价"""
    print(f'\n{"="*60}')
    print(f'🔔 Phase 1 模拟: 竞价初筛 ({SIM_DATE} 9:25) Sina源')
    print(f'{"="*60}\n')
    
    pool = load_pool()
    candidates = pool[:50]
    
    results = []
    errors = 0
    start = time.time()
    
    for i, stock in enumerate(candidates):
        code = stock['code']
        try:
            minute = get_minute_data(to_sina(code))
            if len(minute) == 0:
                errors += 1
                time.sleep(0.2)
                continue
            
            first = minute.iloc[0]
            open_price = float(first['open'])
            prev_close = stock['price']
            gap_pct = (open_price - prev_close) / prev_close * 100
            
            if gap_pct > 1:
                first_vol = int(first['volume'])
                results.append(dict(
                    code=code, name=stock['name'],
                    prev_close=prev_close, open=round(open_price, 2),
                    gap_pct=round(gap_pct, 2),
                    vol_1st=first_vol,
                    sector=stock['sector'],
                    amount_yi=stock['amount_yi'],
                ))
        except Exception as e:
            errors += 1
        
        time.sleep(0.2)
        if (i+1) % 20 == 0:
            elapsed = time.time() - start
            print(f'  {i+1}/{len(candidates)} ({elapsed:.0f}s) 高开{len(results)} 错{errors}')
    
    results.sort(key=lambda x: x['gap_pct'], reverse=True)
    elapsed = time.time() - start
    print(f'\n🔔 竞价结果 ({elapsed:.0f}s): {len(results)}只高开>1% | 错{errors}')
    
    for r in results[:25]:
        print(f"  {r['code']} {r['name']:<8} 昨收{r['prev_close']} → 开{r['open']} (+{r['gap_pct']}%) 首分{r['vol_1st']}手 {r['sector']}")
    
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, 'phase1_sim.json'), 'w') as fh:
        json.dump({'date': SIM_DATE, 'count': len(results), 'elapsed': round(elapsed), 'results': results}, fh, ensure_ascii=False, indent=2)
    
    return results

def phase2_sim(phase1_results):
    """验证骗炮"""
    print(f'\n{"="*60}')
    print(f'✅ Phase 2 模拟: 骗炮验证 ({SIM_DATE} 9:40) Sina源')
    print(f'{"="*60}\n')
    
    candidates = phase1_results[:30]
    print(f'📋 Phase1候选: {len(phase1_results)}只 → 验证前{len(candidates)}只\n')
    
    verified = []
    failed = []
    start = time.time()
    
    for i, stock in enumerate(candidates):
        code = stock['code']
        try:
            minute = get_minute_data(to_sina(code))
            if len(minute) < 10:
                failed.append({**stock, 'reason': f'K线不足({len(minute)}条)'})
                continue
            
            # 取前10分钟 (9:30-9:40)
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
                    prev_close=stock['prev_close'],
                    open=open_price,
                    latest=round(latest, 2),
                    gap_pct=stock['gap_pct'],
                    from_open=round(from_open, 2),
                    total_vol=total_vol,
                    sector=stock['sector'],
                ))
        except Exception as e:
            failed.append({**stock, 'reason': str(e)[:60]})
        
        if (i+1) % 5 == 0:
            print(f'  验证 {i+1}/{len(candidates)} 通过{len(verified)} 排除{len(failed)}')
    
    elapsed = time.time() - start
    verified.sort(key=lambda x: x['from_open'], reverse=True)
    
    print(f'\n{"="*60}')
    print(f'🎯 最终出击 ({elapsed:.0f}s): {len(verified)}只')
    print(f'{"="*60}')
    
    for v in verified:
        print(f"  ✅ {v['code']} {v['name']:<8} 开{v['open']} 现{v['latest']} (+{v['gap_pct']}%高开, 开盘后{v['from_open']:+.1f}%) 量{v['total_vol']}手 {v['sector']}")
    
    if failed:
        print(f'\n❌ 骗炮: {len(failed)}只')
        for f in failed:
            print(f"  ❌ {f['code']} {f['name']:<8} {f.get('reason','?')}")
    
    # 回测实际表现
    print(f'\n📊 当日实际收盘表现:')
    pool = load_pool()
    for v in verified:
        for p in pool:
            if p['code'] == v['code']:
                mark = '🔥' if p['pct'] > 5 else ('✅' if p['pct'] > 0 else '❌')
                print(f"  {mark} {v['code']} {v['name']:<8} 出击{v['from_open']:+.1f}% → 收盘{p['pct']:+.1f}%")
                break
    
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, 'phase2_sim.json'), 'w') as fh:
        json.dump({'date': SIM_DATE, 'verified': len(verified), 'failed': len(failed), 'results': verified, 'excluded': failed}, fh, ensure_ascii=False, indent=2)
    
    return verified

if __name__ == '__main__':
    print(f'🧪 三阶段模拟 v2 — {SIM_DATE} (Sina源)')
    p1 = phase1_sim()
    if p1:
        phase2_sim(p1)
    else:
        print('\n⚠️ Phase1无高开票')
