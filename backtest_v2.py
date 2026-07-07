#!/usr/bin/env python3
"""焚诀策略回测 v2 — Sina HTTP 直连日K（免akshare代理拦截）"""
import os, time, json, sys, urllib.request, ssl
from datetime import datetime, timedelta

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

# =====================
# 1. 池票次日胜率（Sina源）
# =====================
def sina_daily_ret(code, date_str):
    """拉 Sina 日K，算T日到T+1日涨跌"""
    sina = ('sh' if code[0]=='6' else 'sz') + code
    try:
        # Sina日K接口
        url = f'http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={sina}&scale=240&ma=no&datalen=30'
        req = urllib.request.Request(url, headers={'Referer':'https://finance.sina.com.cn'})
        resp = urllib.request.urlopen(req, context=ctx, timeout=10)
        data = json.loads(resp.read().decode('utf-8'))
        if not data or len(data) < 3:
            return None
        
        # 找T日和T+1日
        closes = []
        dates = []
        for d in data:
            dates.append(d['day'])
            closes.append(float(d['close']))
        
        # 找date_str在dates中的位置
        try:
            idx = dates.index(date_str)
        except:
            return None
        
        if idx + 1 >= len(closes):
            return None
        
        t_close = closes[idx]
        next_close = closes[idx + 1]
        ret = (next_close / t_close - 1) * 100
        return round(ret, 2)
    except:
        return None


def backtest_pool_sina(pool_file):
    """Sina源池票次日胜率"""
    date_str = os.path.basename(pool_file).replace('pool_','').replace('.json','')
    try:
        with open(pool_file) as f:
            pool = json.load(f)['results']
    except:
        return None
    
    # 只测前20只
    test_pool = pool[:20]
    results = []
    for s in test_pool:
        code = str(s['code'])
        ret = sina_daily_ret(code, date_str)
        if ret is not None:
            results.append({
                'name': s['name'], 'code': code,
                'ret': ret, 'sector': s.get('sector',''),
                'amount': s.get('amount_yi', 0),
                'ma5': s.get('ma5'), 'ma20': s.get('ma20'),
            })
        time.sleep(0.15)
    
    if not results:
        print(f"  {date_str}: 无有效数据")
        return None
    
    up = [r for r in results if r['ret'] > 0]
    win_rate = len(up) / len(results) * 100
    avg_ret = sum(r['ret'] for r in results) / len(results)
    
    print(f"\n📋 {date_str} 池票次日胜率 (Sina源)")
    print(f"  有效: {len(results)}只 | 上涨: {len(up)}只 | 胜率: {win_rate:.0f}% | 均值: {avg_ret:+.2f}%")
    
    # 按乖离分组
    with_ma = [r for r in results if r.get('ma5') and r.get('ma20')]
    if with_ma:
        low_gap = [r for r in with_ma if (r['ma5']/r['ma20'] - 1)*100 < 15]
        high_gap = [r for r in with_ma if (r['ma5']/r['ma20'] - 1)*100 >= 15]
        if low_gap:
            lu = len([r for r in low_gap if r['ret'] > 0])
            print(f"  低乖离(<15%): {len(low_gap)}只, 胜率{lu/len(low_gap)*100:.0f}%, 均值{sum(r['ret'] for r in low_gap)/len(low_gap):+.2f}%")
        if high_gap:
            hu = len([r for r in high_gap if r['ret'] > 0])
            print(f"  高乖离(≥15%): {len(high_gap)}只, 胜率{hu/len(high_gap)*100:.0f}%, 均值{sum(r['ret'] for r in high_gap)/len(high_gap):+.2f}%")
    
    # 前5明细
    for r in sorted(results, key=lambda x: x['ret'], reverse=True)[:5]:
        tag = '✅' if r['ret'] > 0 else '❌'
        print(f"  {tag} {r['code']} {r['name']:<8} → 次{r['ret']:+.2f}% {r['sector']}")
    
    return results


# =====================
# 2. 快金叉回测（Sina源）
# =====================
def backtest_golden_cross_sina(pool_file):
    """快金叉候选 → 次日表现"""
    date_str = os.path.basename(pool_file).replace('pool_','').replace('.json','')
    try:
        with open(pool_file) as f:
            pool = json.load(f)['results']
    except:
        return None
    
    with_ma = [s for s in pool if s.get('ma5') and s.get('ma20')]
    cross_candidates = []
    for s in with_ma:
        ma5, ma20 = s['ma5'], s['ma20']
        gap = (ma5 - ma20) / ma20 * 100
        if -8 <= gap <= 3 and s.get('amount_yi', 0) > 1:
            cross_candidates.append(s)
    
    if not cross_candidates:
        return None
    
    results = []
    for c in cross_candidates[:15]:
        code = str(c['code'])
        ret = sina_daily_ret(code, date_str)
        if ret is not None:
            results.append({
                'name': c['name'], 'code': code,
                'gap': round((c['ma5']/c['ma20'] - 1)*100, 1),
                'ret': ret
            })
        time.sleep(0.15)
    
    if not results or len(results) < 3:
        return None
    
    up = [r for r in results if r['ret'] > 0]
    print(f"\n📐 {date_str} 快金叉 → 次日胜率 (Sina源)")
    print(f"  候选: {len(cross_candidates)}只 | 有效: {len(results)}只 | 胜率: {len(up)/len(results)*100:.0f}% | 均值: {sum(r['ret'] for r in results)/len(results):+.2f}%")
    for r in sorted(results, key=lambda x: x['ret'], reverse=True)[:8]:
        tag = '✅' if r['ret'] > 0 else '❌'
        print(f"  {tag} {r['code']} {r['name']:<8} MA差{r['gap']:+.1f}% → 次{r['ret']:+.2f}%")
    
    return results


# =====================
# 3. 冲高回落收阳 → 次日（Sina日K + 分钟K统计）
# =====================
def backtest_spike_fade_sina(date_str, watch_codes):
    """
    用 Sina 日K数据近似「冲高>4% + 回落>1.5% + 收阳」模式
    Sina日K有 open/high/low/close，可近似判断
    """
    print(f"\n📈 {date_str} 冲高回落收阳 → 次日 (Sina日K近似)")
    results = []
    
    for code, name in watch_codes:
        sina = ('sh' if code[0]=='6' else 'sz') + code
        try:
            url = f'http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={sina}&scale=240&ma=no&datalen=60'
            req = urllib.request.Request(url, headers={'Referer':'https://finance.sina.com.cn'})
            resp = urllib.request.urlopen(req, context=ctx, timeout=10)
            data = json.loads(resp.read().decode('utf-8'))
            
            if not data or len(data) < 5:
                continue
            
            for i in range(1, len(data)-1):
                d = data[i]
                o = float(d['open'])
                c = float(d['close'])
                h = float(d['high'])
                high_pct = (h - o) / o * 100
                fade = (c - h) / h * 100
                pct = (c - o) / o * 100
                
                if high_pct > 4 and fade < -1.5 and pct > 0.5:
                    next_c = float(data[i+1]['close'])
                    next_ret = (next_c - c) / c * 100
                    results.append({
                        'stock': name, 'date': d['day'],
                        'high_pct': round(high_pct,1), 'fade': round(fade,1),
                        'pct': round(pct,1), 'next_ret': round(next_ret,1)
                    })
        except Exception as e:
            pass
        time.sleep(0.2)
    
    if not results:
        print("  无匹配样本")
        return None
    
    up = [r for r in results if r['next_ret'] > 0]
    print(f"  总样本: {len(results)}次 | 次日涨: {len(up)}次 | 胜率: {len(up)/len(results)*100:.0f}%")
    print(f"  平均次日: {sum(r['next_ret'] for r in results)/len(results):+.2f}%")
    for r in sorted(results, key=lambda x: x['next_ret'], reverse=True):
        tag = '✅' if r['next_ret'] > 0 else '❌'
        print(f"  {tag} {r['stock']:<8} {r['date']} 冲{r['high_pct']:+.1f}% 回{r['fade']:+.1f}% → 次{r['next_ret']:+.1f}%")
    
    return results


# =====================
# MAIN
# =====================
if __name__ == '__main__':
    import glob
    pool_files = sorted(glob.glob('/opt/data/fenjue/pool_*.json'))
    
    print("="*60)
    print("🔥 焚诀策略综合回测 v2 (Sina HTTP直连)")
    print("="*60)
    
    # 最近3个池文件
    recent = pool_files[-3:]
    for pf in recent:
        backtest_pool_sina(pf)
        backtest_golden_cross_sina(pf)
    
    # 冲高回落模式测试
    watch = [
        ('600584', '长电科技'), ('002409', '雅克科技'),
        ('600745', '闻泰科技'), ('601677', '明泰铝业'),
        ('603501', '韦尔股份'), ('002384', '东山精密'),
    ]
    backtest_spike_fade_sina('recent', watch)
    
    print(f"\n{'='*60}")
    print("✅ 回测完成")
