import json
import sys

sys.path.insert(0, '/opt/data/scripts')
from reversal_daily import sina_pool

rows = sina_pool()
codes = [r for r in rows if r.get('prev_close') and r['prev_close'] > 0]
big_up = sorted(codes, key=lambda r: -(r['price'] / r['prev_close'] - 1))[:15]
big_dn = sorted(codes, key=lambda r: (r['price'] / r['prev_close'] - 1))[:10]
print('涨幅前15:', ' '.join(f"{r['name']}{r['price']/r['prev_close']-1:+.1%}" for r in big_up))
print('跌幅前10:', ' '.join(f"{r['name']}{r['price']/r['prev_close']-1:+.1%}" for r in big_dn))
wp = json.load(open('/opt/data/fenjue/data/watch_pool.json'))
pool_names = {e.get('name') for e in wp.get('pool', [])}
print('观察池∩涨幅前15:', [r['name'] for r in big_up if r['name'] in pool_names])
lu = sum(1 for r in codes if r['price'] / r['prev_close'] - 1 >= 0.098)
ld = sum(1 for r in codes if r['price'] / r['prev_close'] - 1 <= -0.098)
dn95 = [r for r in codes if r['price'] / r['prev_close'] - 1 <= -0.095]
print(f'主板涨停≈{lu} 跌停≈{ld} 触及-9.5%≈{len(dn95)}')
# 深V 候选（今日上午深砸收盘收复的）用日线 low/close 粗扫：收 vs 最低
# 需要 daily 数据——用 sina 快照的 high/low/price
v_cands = []
for r in codes:
    try:
        lo_pct = r['low'] / r['prev_close'] - 1
        cl_pct = r['price'] / r['prev_close'] - 1
        if lo_pct <= -0.07 and cl_pct > -0.05:
            v_cands.append((r['name'], lo_pct, cl_pct))
    except Exception:
        pass
print('日内深V（低≤-7% 收>-5%）:', v_cands[:12])
