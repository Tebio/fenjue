#!/usr/bin/env python3
"""焚诀策略综合回测 — 日K级别（快速版）"""
import os, time, json, sys
from datetime import datetime, timedelta
for k in list(os.environ.keys()):
    if 'proxy' in k.lower(): del os.environ[k]

import akshare as ak
import pandas as pd
import numpy as np

# ============================
# 1. 池票次日胜率回测
# ============================
def backtest_pool_next_day(pool_file, days_ahead=1):
    """测试焚诀池中票的次日胜率"""
    date_str = os.path.basename(pool_file).replace('pool_','').replace('.json','')
    try:
        with open(pool_file) as f:
            pool = json.load(f)['results']
    except:
        return None
    
    print(f"\n{'='*60}")
    print(f"📋 策略1: 焚诀池 → 次日胜率 ({date_str})")
    print(f"池内 {len(pool)} 只，测试前25只")
    print(f"{'='*60}")
    
    results = []
    for i, s in enumerate(pool[:25]):
        code = str(s['code'])
        sina = ('sh' if code[0]=='6' else 'sz') + code
        try:
            # 拉日K：T日前30天到T日后5天
            start = (datetime.strptime(date_str, '%Y%m%d') - timedelta(days=30)).strftime('%Y%m%d')
            end = (datetime.strptime(date_str, '%Y%m%d') + timedelta(days=days_ahead+2)).strftime('%Y%m%d')
            df = ak.stock_zh_a_daily(symbol=sina, start_date=start, end_date=end, adjust='qfq')
            if len(df) < 3:
                continue
            
            # 找T日
            rows = df[df['date'].astype(str).str[:10] == date_str]
            if len(rows) == 0:
                continue
            idx = df.index.get_loc(rows.index[0])
            if idx + days_ahead >= len(df):
                continue
            
            t_close = df.iloc[idx]['close']
            next_close = df.iloc[idx + days_ahead]['close']
            ret = (next_close / t_close - 1) * 100
            
            # 计算MA5/MA20 (T日)
            if idx >= 4:
                ma5 = df['close'].iloc[idx-4:idx+1].mean()
            else:
                ma5 = t_close
            if idx >= 19:
                ma20 = df['close'].iloc[idx-19:idx+1].mean()
            else:
                ma20 = t_close
            
            ma20_gap = (t_close / ma20 - 1) * 100
            
            results.append({
                'name': s['name'], 'code': code,
                'ret': round(ret, 2),
                'ma20_gap': round(ma20_gap, 1),
                'sector': s.get('sector', ''),
                'amount': s.get('amount_yi', 0),
            })
        except Exception as e:
            pass
        time.sleep(0.3)  # 控制请求频率
    
    if not results:
        print("无有效数据")
        return None
    
    up = [r for r in results if r['ret'] > 0]
    down = [r for r in results if r['ret'] <= 0]
    print(f"有效样本: {len(results)}只")
    print(f"次日上涨: {len(up)}只 ({len(up)/len(results)*100:.0f}%)")
    print(f"次日下跌: {len(down)}只 ({len(down)/len(results)*100:.0f}%)")
    print(f"平均次日涨幅: {sum(r['ret'] for r in results)/len(results):+.2f}%")
    
    # 按ma20_gap分组
    low_gap = [r for r in results if r['ma20_gap'] < 15]
    high_gap = [r for r in results if r['ma20_gap'] >= 15]
    if low_gap:
        print(f"\n  低乖离(<15%): {len(low_gap)}只, 胜率{len([r for r in low_gap if r['ret']>0])/len(low_gap)*100:.0f}%, 均值{sum(r['ret'] for r in low_gap)/len(low_gap):+.2f}%")
    if high_gap:
        print(f"  高乖离(≥15%): {len(high_gap)}只, 胜率{len([r for r in high_gap if r['ret']>0])/len(high_gap)*100:.0f}%, 均值{sum(r['ret'] for r in high_gap)/len(high_gap):+.2f}%")
    
    return results


# ============================
# 2. 快金叉回测
# ============================
def backtest_golden_cross(pool_file):
    """MA5接近MA20(差距-8%~+3%)的票 → 次日表现"""
    date_str = os.path.basename(pool_file).replace('pool_','').replace('.json','')
    try:
        with open(pool_file) as f:
            pool = json.load(f)['results']
    except:
        return None
    
    print(f"\n{'='*60}")
    print(f"📐 策略2: 快金叉 → 次日胜率 ({date_str})")
    print(f"筛选条件: MA5/MA20差距 -8%~+3% + 当日收阳 + 成交>1亿")
    print(f"{'='*60}")
    
    # 先过滤池中有ma5/ma20字段的票
    with_ma = [s for s in pool if s.get('ma5') and s.get('ma20')]
    print(f"池中有MA数据的: {len(with_ma)}只")
    
    # 快金叉候选
    cross_candidates = []
    for s in with_ma:
        ma5, ma20 = s['ma5'], s['ma20']
        gap = (ma5 - ma20) / ma20 * 100
        if -8 <= gap <= 3 and s.get('amount_yi', 0) > 1:
            cross_candidates.append({'name': s['name'], 'code': s['code'], 'gap': round(gap,1), 'ma5': ma5, 'ma20': ma20, 'amount': s.get('amount_yi',0)})
    
    if not cross_candidates:
        print("无快金叉候选")
        return None
    
    print(f"快金叉候选: {len(cross_candidates)}只")
    
    # 拉次日数据
    results = []
    for c in cross_candidates[:15]:
        code = str(c['code'])
        sina = ('sh' if code[0]=='6' else 'sz') + code
        try:
            start = (datetime.strptime(date_str, '%Y%m%d') - timedelta(days=5)).strftime('%Y%m%d')
            end = (datetime.strptime(date_str, '%Y%m%d') + timedelta(days=3)).strftime('%Y%m%d')
            df = ak.stock_zh_a_daily(symbol=sina, start_date=start, end_date=end, adjust='qfq')
            if len(df) < 3:
                continue
            rows = df[df['date'].astype(str).str[:10] == date_str]
            if len(rows) == 0:
                continue
            idx = df.index.get_loc(rows.index[0])
            if idx + 1 >= len(df):
                continue
            t_close = df.iloc[idx]['close']
            next_close = df.iloc[idx + 1]['close']
            ret = (next_close / t_close - 1) * 100
            results.append({'name': c['name'], 'code': c['code'], 'gap': c['gap'], 'ret': round(ret, 2)})
        except:
            pass
        time.sleep(0.3)
    
    if not results:
        print("无有效次日数据")
        return None
    
    up = [r for r in results if r['ret'] > 0]
    print(f"有效样本: {len(results)}只")
    print(f"次日上涨: {len(up)}只 ({len(up)/len(results)*100:.0f}%)")
    print(f"平均次日涨幅: {sum(r['ret'] for r in results)/len(results):+.2f}%")
    for r in sorted(results, key=lambda x: x['ret'], reverse=True):
        mark = '✅' if r['ret'] > 0 else '❌'
        print(f"  {mark} {r['code']} {r['name']:<8} MA差{r['gap']:+.1f}% → 次日{r['ret']:+.2f}%")
    
    return results


# ============================
# 3. 板块迁移追踪回测
# ============================
def backtest_sector_migration(pool_file_old, pool_file_new):
    """行业迁移信号 → 板块次日表现"""
    try:
        with open(pool_file_old) as f:
            old_pool = json.load(f)['results']
        with open(pool_file_new) as f:
            new_pool = json.load(f)['results']
    except:
        return None
    
    date_old = os.path.basename(pool_file_old).replace('pool_','').replace('.json','')
    date_new = os.path.basename(pool_file_new).replace('pool_','').replace('.json','')
    
    from collections import Counter
    old_sec = Counter(r.get('sector','') for r in old_pool)
    new_sec = Counter(r.get('sector','') for r in new_pool)
    
    print(f"\n{'='*60}")
    print(f"📊 策略3: 行业迁移追踪 ({date_old} → {date_new})")
    print(f"{'='*60}")
    
    # 翻倍/腰斩/归零行业
    doubled = []
    halved = []
    gone = []
    
    all_sectors = set(list(old_sec.keys()) + list(new_sec.keys()))
    for sec in all_sectors:
        o = old_sec.get(sec, 0)
        n = new_sec.get(sec, 0)
        if o == 0: continue
        if n >= o * 2 and o >= 2:
            doubled.append((sec, o, n))
        elif n <= o * 0.5 and o >= 4:
            halved.append((sec, o, n))
        elif n == 0 and o >= 3:
            gone.append((sec, o, n))
    
    if doubled:
        print(f"\n🟢 翻倍行业（资金涌入信号）:")
        for sec, o, n in doubled:
            print(f"  {sec}: {o}→{n}只")
    
    if halved:
        print(f"\n🔴 腰斩行业（资金撤出信号）:")
        for sec, o, n in halved:
            print(f"  {sec}: {o}→{n}只")
    
    if gone:
        print(f"\n🔴🔴 归零行业（板块退潮）:")
        for sec, o, n in gone:
            print(f"  {sec}: {o}→0只")
    
    if not (doubled or halved or gone):
        print("无显著行业迁移信号")
    
    return {'doubled': doubled, 'halved': halved, 'gone': gone}


# ============================
# 4. 高开1-6% vs 低开/平开 次日胜率
# ============================
def backtest_gap_up(pool_file):
    """高开幅度 vs 次日表现"""
    date_str = os.path.basename(pool_file).replace('pool_','').replace('.json','')
    try:
        with open(pool_file) as f:
            pool = json.load(f)['results']
    except:
        return None
    
    print(f"\n{'='*60}")
    print(f"🔔 策略4: 竞价高开幅度 → 收盘胜率 ({date_str})")
    print(f"{'='*60}")
    
    # 需要快照数据
    snap_path = f'/opt/data/fenjue/snapshots/snapshot_{date_str}_0925.json'
    if not os.path.exists(snap_path):
        print(f"无竞价快照: {snap_path}")
        return None
    
    with open(snap_path) as f:
        snap = json.load(f)
    
    quotes = snap.get('quotes', {})
    if not quotes:
        print("快照无行情数据")
        return None
    
    # 匹配池票 + 快照early_pct
    pool_map = {str(s['code']): s for s in pool}
    results = []
    
    for code, q in quotes.items():
        if code not in pool_map:
            continue
        early_pct = q.get('early_pct', 0) or 0
        early_amt = q.get('early_amount_yi', 0) or 0
        s = pool_map[code]
        
        class_label = ''
        if early_pct >= 6:
            class_label = '超高开 ≥6%'
        elif early_pct >= 3:
            class_label = '高开 3-6%'
        elif early_pct >= 1:
            class_label = '小高开 1-3%'
        elif early_pct >= -1:
            class_label = '平开 ±1%'
        else:
            class_label = '低开 <-1%'
        
        results.append({
            'name': s['name'], 'code': code,
            'early_pct': early_pct,
            'day_pct': s.get('pct', 0) or 0,
            'class': class_label,
        })
    
    if not results:
        print("无匹配数据")
        return None
    
    # 按分类统计
    from collections import defaultdict
    classes = defaultdict(list)
    for r in results:
        classes[r['class']].append(r)
    
    print(f"总样本: {len(results)}只\n")
    for cls, items in sorted(classes.items()):
        avg_day = sum(it['day_pct'] for it in items) / len(items)
        up = len([it for it in items if it['day_pct'] > 0])
        print(f"  {cls}: {len(items)}只, 当日胜率{up/len(items)*100:.0f}%, 均涨幅{avg_day:+.2f}%")
    
    return results


# ============================
# MAIN
# ============================
if __name__ == '__main__':
    # 找最近的可回测池文件
    import glob
    pool_files = sorted(glob.glob('/opt/data/fenjue/pool_*.json'))
    if len(pool_files) < 2:
        print("需要至少2个池文件")
        sys.exit(1)
    
    print("=" * 60)
    print("🔥 焚诀策略综合回测报告")
    print(f"可用池文件: {len(pool_files)}个 ({pool_files[0][-13:-5]} ~ {pool_files[-1][-13:-5]})")
    print("=" * 60)
    
    # 对最近3个有日期的池做回测
    test_dates = []
    for pf in pool_files[-4:]:
        d = os.path.basename(pf).replace('pool_','').replace('.json','')
        test_dates.append(d)
    
    for d in test_dates:
        pf = f'/opt/data/fenjue/pool_{d}.json'
        if not os.path.exists(pf):
            continue
        
        # 策略1: 池票次日胜率
        backtest_pool_next_day(pf)
        
        # 策略2: 快金叉
        backtest_golden_cross(pf)
        
        # 策略4: 高开分类
        backtest_gap_up(pf)
    
    # 策略3: 行业迁移（需要两个相邻日期）
    if len(test_dates) >= 2:
        for i in range(len(test_dates)-1):
            pf_old = f'/opt/data/fenjue/pool_{test_dates[i]}.json'
            pf_new = f'/opt/data/fenjue/pool_{test_dates[i+1]}.json'
            if os.path.exists(pf_old) and os.path.exists(pf_new):
                backtest_sector_migration(pf_old, pf_new)
    
    print(f"\n{'='*60}")
    print("✅ 回测完成")
    print(f"{'='*60}")
