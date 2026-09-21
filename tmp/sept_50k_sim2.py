"""9 月模拟 V2：加推送实况过滤器（成簇门）+ 分主张拆解 + 在途按 9/18 收盘盯市。"""
import sys, json, statistics as st
sys.path.insert(0, 'engine')
import law_pipeline as lp

stocks = lp.load_universe()
lp.build_xsection(stocks)

CLAIMS = {
    '跌停底座(组合三连阴)': '组合_跌停低_三连阴',
    '恐慌复活门': '反转族_跌停潮50',
    '摇篮成簇': '妖股摇篮_成簇',
    '缺口低_避周一': '组合_缺口低开_低位阳线_避周一',
    'TD9旗舰_输家': '组合_跌停低_TD9买_输家250',
    'TD9旗舰_超跌': '组合_跌停低_TD9买_超跌20',
}
CLUSTER_GATED = {'跌停底座(组合三连阴)', 'TD9旗舰_输家', 'TD9旗舰_超跌'}  # 深档低位系：当日≥5只才推
SEP = ('2026-09-01', '2026-09-18')
FEE = 0.003
HOLD = 5

# 先按主张收集（不去重），再算每日深档系簇数，最后应用成簇门+跨主张去重
raw = []
for cname, det_name in CLAIMS.items():
    det = lp.REGISTRY[det_name]
    for code, d in stocks.items():
        n = d['n']
        for i in range(lp.START, n - 1):
            dt = d['date'][i]
            if dt < SEP[0] or dt > SEP[1] or lp._epx(d, i) <= 0:
                continue
            try:
                if not det(d, i):
                    continue
            except Exception:
                continue
            ei = i + 1
            r_settled = d['c'][ei + HOLD] / lp._epx(d, i) - 1 - FEE if ei + HOLD < n else None
            r_mtm = d['c'][-1] / lp._epx(d, i) - 1 - FEE if ei < n else None
            raw.append({'dt': dt, 'code': code, 'entry_d': d['date'][ei], 'claim': cname,
                        'r5': r_settled, 'mtm': r_mtm})

# 深档系每日簇数（成簇门判定用同族信号数）
cluster_day = {}
for r in raw:
    if r['claim'] in CLUSTER_GATED:
        cluster_day.setdefault(r['dt'], set()).add(r['code'])

kept, blocked = [], []
seen = set()
for r in sorted(raw, key=lambda x: (x['dt'], x['code'])):
    if r['claim'] in CLUSTER_GATED and len(cluster_day.get(r['dt'], set())) < 5:
        blocked.append(r)
        continue
    key = (r['dt'], r['code'])
    if key in seen:
        continue
    seen.add(key)
    kept.append(r)

print(f'原始命中 {len(raw)}，成簇门拦截 {len(blocked)}，去重后入场 {len(kept)} 笔\n')
print('== 逐日明细（成簇门后）==')
by_day = {}
for r in kept:
    by_day.setdefault(r['dt'], []).append(r)
for dt in sorted(by_day):
    rs = by_day[dt]
    done = [x['r5'] for x in rs if x['r5'] is not None]
    mtm = [x['mtm'] for x in rs if x['mtm'] is not None]
    line = f"{dt}: {len(rs)} 笔 [{'/'.join(sorted({x['claim'] for x in rs}))}]"
    if done:
        line += f" 已结算胜率{100*sum(1 for x in done if x>0)/len(done):.0f}% 均{100*st.mean(done):+.2f}%"
    line += f" 盯市均{100*st.mean(mtm):+.2f}%" if mtm else ''
    print(line)

print('\n== 分主张（盯市口径）==')
by_claim = {}
for r in kept:
    by_claim.setdefault(r['claim'], []).append(r)
for cname, rs in sorted(by_claim.items()):
    mtm = [x['mtm'] for x in rs]
    done = [x['r5'] for x in rs if x['r5'] is not None]
    line = f"{cname}: {len(rs)} 笔 盯市{100*st.mean(mtm):+.2f}% 胜率{100*sum(1 for x in mtm if x>0)/len(mtm):.0f}%"
    if done:
        line += f" | 已结算 {len(done)} 笔 均{100*st.mean(done):+.2f}%"
    print(line)

# 账本：每笔 5000，10 槽
allr = [x['mtm'] for x in kept]
pnl = sum(allr) * 5000
print(f'\n== 总账（盯市 9/18 收盘，含在途）==')
print(f'{len(kept)} 笔 × 5000 元：总盈亏 {pnl:+.0f} 元 = 本金 5 万的 {pnl/500:+.2f}%')
print(f'对照：上证 9 月 -1.87%')
blk = [x for x in blocked]
if blk:
    bm = [x['mtm'] for x in blk]
    print(f'\n被成簇门拦下的 {len(blk)} 笔（零星日）盯市均值 {100*st.mean(bm):+.2f}%——拦截效果验证')