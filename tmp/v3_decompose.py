"""终局定位：全信号按主张×出场分解 —— 找出 +3.9% 均值的来源与容量组合的死因。"""
import sys, json, statistics as st
sys.path.insert(0, 'engine')
import law_pipeline as lp

stocks = lp.load_universe()
lp.build_xsection(stocks)
CLAIMS = {
    '跌停底座': '组合_跌停低_三连阴', '复活门': '反转族_跌停潮50', '摇篮': '妖股摇篮_成簇',
    '缺口低': '组合_缺口低开_低位阳线_避周一',
    'TD9输家': '组合_跌停低_TD9买_输家250', 'TD9超跌': '组合_跌停低_TD9买_超跌20',
}
FEE = 0.003

stats = {k: {'n': 0, 't5': [], 't1c': []} for k in CLAIMS}
for cname, dn in CLAIMS.items():
    det = lp.REGISTRY[dn]
    for code, d in stocks.items():
        n = d['n']
        for i in range(lp.START, n - 1):
            if lp._epx(d, i) <= 0:
                continue
            try:
                if not det(d, i):
                    continue
            except Exception:
                continue
            ei = i + 1
            ep = lp._epx(d, i)
            stats[cname]['n'] += 1
            if ei + 5 < n:
                stats[cname]['t5'].append(d['c'][ei + 5] / ep - 1 - FEE)
            if ei < n:
                r1 = d['c'][ei] / ep - 1
                tgt = 20 if r1 >= 0.03 else 10
                xi = min(ei + tgt, n - 1)
                stats[cname]['t1c'].append(d['c'][xi] / ep - 1 - FEE)

print(f'{"主张":<10}{"信号数":>8}{"T+5出场":>18}{"T1分档出场(T+10/20)":>22}')
for k, v in stats.items():
    t5 = f"{100*sum(1 for x in v['t5'] if x>0)/len(v['t5']):.0f}%/{100*st.mean(v['t5']):+.2f}%" if v['t5'] else '-'
    t1 = f"{100*sum(1 for x in v['t1c'] if x>0)/len(v['t1c']):.0f}%/{100*st.mean(v['t1c']):+.2f}%" if v['t1c'] else '-'
    print(f'{k:<10}{v["n"]:>8}{t5:>18}{t1:>22}')