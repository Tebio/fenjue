"""#77 妖股生命周期四段论：晋级段条件概率树 / 分歧段大面特征 / 二波段条件
数据：big_kcache 8年 + HiThink板块映射 + cap_hist
"""
import json
from pathlib import Path
from collections import defaultdict

ROOT = Path('/opt/data/fenjue')
KC = ROOT / 'data/big_kcache'
paths = [p for p in KC.glob('*.json') if p.stem[:2] in ('60', '00')]

import glob
sec_map = json.load(open(sorted(glob.glob(str(ROOT / 'data/hithink/sectors/stock_sectors_*.json')))[-1]))
STOP = {"融资融券", "深股通", "沪股通", "国企改革", "次新股", "ST股"}

# ── 每日涨停集合（先扫一遍建板块热度）──
print('pass1: 建板块热度...', flush=True)
lu_by_day = defaultdict(set)
stock_ks = {}
for fp in paths:
    try: ks = json.load(open(str(fp)))
    except Exception: continue
    stock_ks[fp.stem] = ks
    for t in range(1, len(ks)):
        prev = ks[t-1]['close']
        if prev > 0 and ks[t]['close'] / prev - 1 >= 0.098:
            lu_by_day[ks[t]['date']].add(fp.stem)

sec_lu_day = defaultdict(lambda: defaultdict(int))
for d, codes in lu_by_day.items():
    for c in codes:
        for e in sec_map.get(c, []):
            nm = e.get('name')
            if nm and nm not in STOP:
                sec_lu_day[d][nm] += 1

def stock_ladder(c, d):
    for e in sec_map.get(c, []):
        nm = e.get('name')
        if nm and nm not in STOP and sec_lu_day[d].get(nm, 0) >= 3:
            return sec_lu_day[d][nm]
    return 0

def cell(): return {'n': 0, 'yes': 0}
def dump(G, title, ylab):
    print(f'\n=== {title} ===')
    for k in sorted(G):
        c = G[k]
        if c['n'] < 100: continue
        print(f'  {str(k):34s} n={c["n"]:>6d}  {ylab}={c["yes"]/c["n"]*100:5.1f}%')

# ── 晋级段+分歧段+二波段 ──
print('pass2: 生命周期扫描...', flush=True)
G_jinji = defaultdict(cell)     # (连板数档, 位置, 换手档) → 次日晋级
G_fenqi = defaultdict(cell)     # (断板日开盘档, 板块梯队) → 次日大面
G_erbo = defaultdict(cell)      # (冷却天数档, 距前高) → 二波次日再板/收红
G_erbo_red = defaultdict(cell)

for c0, ks in stock_ks.items():
    n = len(ks)
    if n < 130: continue
    closes = [k['close'] for k in ks]
    vols = [k.get('volume', 0) or 0 for k in ks]
    is_lu = [False] * n
    for t in range(1, n):
        if closes[t-1] > 0 and closes[t] / closes[t-1] - 1 >= 0.098:
            is_lu[t] = True
    # 连板段标记
    t = 130
    while t < n - 1:
        if not is_lu[t]:
            t += 1; continue
        # 连板数（含t）
        streak = 1
        while t - streak >= 0 and is_lu[t - streak]:
            streak += 1
        ma60 = sum(closes[max(0, t-60):t+1]) / min(61, t+1)
        pos = 'MA60下' if closes[t] < ma60 else 'MA60上'
        # 换手档（量比 vs 5日）
        v5 = sum(vols[max(0, t-5):t]) / 5 if t >= 5 else 0
        vr = vols[t] / v5 if v5 > 0 else 1
        vg = '缩量(<0.8)' if vr < 0.8 else '常量' if vr < 1.5 else '放量(≥1.5)'
        sg = f'{streak}板' if streak <= 3 else '4板+'
        nxt_board = is_lu[t+1] if t + 1 < n else False
        G_jinji[(sg, pos, vg)]['n'] += 1
        G_jinji[(sg, pos, vg)]['yes'] += nxt_board
        t += 1
    # 分歧段：连板(≥2)断的第一天
    t = 130
    while t < n - 1:
        if is_lu[t] and not is_lu[t+1] and t + 2 < n:
            # 找连板长度
            streak = 1
            while t - streak >= 0 and is_lu[t - streak]:
                streak += 1
            if streak >= 2:
                brk = t + 1  # 断板日
                open_chg = ks[brk]['open'] / closes[t] - 1
                og = '低开(<-2%)' if open_chg < -0.02 else '平开' if open_chg < 0.02 else '高开(≥2%)'
                lad = '梯队热(≥3)' if stock_ladder(c0, ks[brk]['date']) >= 3 else '梯队散'
                big_face = (closes[brk+1] / closes[brk] - 1) <= -0.05
                G_fenqi[(og, lad)]['n'] += 1
                G_fenqi[(og, lad)]['yes'] += big_face
            t += 1
        else:
            t += 1
    # 二波段：历史有≥3连板，冷却≥5日后首板
    t = 130
    while t < n - 1:
        if is_lu[t]:
            # 之前120日有≥3连板，且近5日无板
            run = mx = 0
            has_dragon = False
            for u in range(max(1, t-120), t-4):
                if is_lu[u]:
                    run += 1; mx = max(mx, run)
                    if mx >= 3: has_dragon = True; break
                else:
                    run = 0
            if has_dragon and not any(is_lu[t-4:t]):
                # 冷却天数
                cool = 0
                for u in range(t-1, max(0, t-120), -1):
                    if is_lu[u]: break
                    cool += 1
                cg = '冷却5-15日' if cool <= 15 else '冷却16-40日' if cool <= 40 else '冷却40日+'
                prev_high = max(closes[max(0, t-120):t])
                dist = (closes[t] / prev_high - 1) * 100
                dg = '距前高<10%' if dist > -10 else '距前高10-30%' if dist > -30 else '距前高>30%'
                nxt_board = is_lu[t+1]
                nxt_red = closes[t+1] > closes[t]
                G_erbo[(cg, dg)]['n'] += 1
                G_erbo[(cg, dg)]['yes'] += nxt_board
                G_erbo_red[(cg, dg)]['n'] += 1
                G_erbo_red[(cg, dg)]['yes'] += nxt_red
        t += 1

dump(G_jinji, '晋级段：次日再板概率（连板数×位置×换手）', '晋级率')
dump(G_fenqi, '分歧段：断板次日大面率（断板开盘×板块梯队）', '大面率')
dump(G_erbo, '二波段：老龙再启动次日再板率（冷却×距前高）', '再板率')
dump(G_erbo_red, '二波段：次日收红率', '收红率')
