"""打法优化对照：v1 现行规则 vs v2 优化规则，2026-08-01 → 09-18，5万/10槽/费0.3%。
v2 规则（全部来自已注册证据）：
  R1 出场 T1 分档（#58）：入场次日收盘 ≥+3% → 拿到 T+20；±3% → T+10；≤-3% → T+3 离场
      （跌停底座系实测口径；缺口低族属外推，单列统计）
  R2 恐慌期日（hcap regime）豁免深档系成簇门（regime 本身=全市场确认）
  R3 成簇日选票：距60高最深者优先（pick_ranker 恐慌腿已验证），槽满时才用
  R4 缺口低族基础出场 T+20（#115：2026 靠长窗），同样过 T1 分档
v1 = 现行：成簇门≥5（恐慌日不豁免）+ T+5 一刀切 + 随机取舍
"""
import sys, json, statistics as st, random
sys.path.insert(0, 'engine')
import law_pipeline as lp

stocks = lp.load_universe()
lp.build_xsection(stocks)
regime = lp.load_regime()

CLAIMS = {
    '跌停底座': '组合_跌停低_三连阴',
    '复活门': '反转族_跌停潮50',
    '摇篮': '妖股摇篮_成簇',
    '缺口低': '组合_缺口低开_低位阳线_避周一',
    'TD9输家': '组合_跌停低_TD9买_输家250',
    'TD9超跌': '组合_跌停低_TD9买_超跌20',
}
PANIC_FAM = {'跌停底座', 'TD9输家', 'TD9超跌'}  # 深档系
WIN = ('2026-08-01', '2026-09-18')
FEE = 0.003

# ── 收集全部命中（含特征：距60高用于选票排序）──
raw = []
for cname, dn in CLAIMS.items():
    det = lp.REGISTRY[dn]
    for code, d in stocks.items():
        n = d['n']
        c, h = d['c'], d['h']
        for i in range(lp.START, n - 1):
            dt = d['date'][i]
            if dt < WIN[0] or dt > WIN[1] or lp._epx(d, i) <= 0:
                continue
            try:
                if not det(d, i):
                    continue
            except Exception:
                continue
            hi60 = max(h[max(0, i - 60):i]) if i >= 1 else 0
            pos60 = c[i - 1] / hi60 - 1 if hi60 > 0 else 0
            raw.append({'dt': dt, 'code': code, 'i': i, 'claim': cname,
                        'rg': regime.get(dt, '?'), 'pos60': pos60})
print(f'窗口内原始命中 {len(raw)}')

# ── 出场引擎 ──
def exits(d, i, mode):
    """返回 (出场收益, 出场标签)。入场=_epx(i)，费已含。"""
    n = d['n']
    ep = lp._epx(d, i)
    ei = i + 1
    if mode == 'T5':
        if ei + 5 < n:
            return d['c'][ei + 5] / ep - 1 - FEE, 'T+5结算'
        return (d['c'][-1] / ep - 1 - FEE, '盯市') if ei < n else (None, None)
    # T1 分档
    if ei >= n:
        return None, None
    r1 = d['c'][ei] / ep - 1
    tgt = 20 if r1 >= 0.03 else (10 if r1 >= -0.03 else 3)
    tag = 'T1强→T+20' if r1 >= 0.03 else ('T1平→T+10' if r1 >= -0.03 else 'T1弱→T+3')
    if ei + tgt < n:
        return d['c'][ei + tgt] / ep - 1 - FEE, tag + '结算'
    return (d['c'][-1] / ep - 1 - FEE, tag + '盯市') if ei < n else (None, None)

# ── 闸门+去重 ──
def gate(raw, v2):
    cl = {}
    for r in raw:
        if r['claim'] in PANIC_FAM:
            cl.setdefault(r['dt'], set()).add(r['code'])
    kept = []
    seen = set()
    for r in sorted(raw, key=lambda x: (x['dt'], x['pos60'])):  # pos60 升序=超跌最深优先
        if r['claim'] in PANIC_FAM:
            is_panic_day = r['rg'] == '恐慌期'
            if len(cl.get(r['dt'], set())) < 5 and not (v2 and is_panic_day):
                continue
        key = (r['dt'], r['code'])
        if key in seen:
            continue
        seen.add(key)
        kept.append(r)
    return kept

# ── 账本：10槽×5000；pick='pos60' 超跌最深优先 / 'random' 随机（5种子均值）──
IDXCAL = [k['date'] for k in json.loads(open('data/index_sh000001.json').read())]
def book(kept, v2, pick='pos60', seed=42):
    trades = []
    for r in kept:
        d = stocks[r['code']]
        mode = 'T1' if v2 else 'T5'
        ret, tag = exits(d, r['i'], mode)
        if ret is None:
            continue
        entry_d = d['date'][r['i'] + 1]
        holdn = 20 if 'T+20' in tag else (10 if 'T+10' in tag else (3 if 'T+3' in tag else 5))
        exit_i = min(r['i'] + 1 + holdn, d['n'] - 1)
        trades.append({**r, 'ret': ret, 'tag': tag, 'entry_d': entry_d,
                       'exit_d': d['date'][exit_i]})
    import bisect
    rnd = random.Random(seed)
    openpos, taken, missed = [], 0, 0
    pnl = 0.0
    daily = []
    for t in sorted(trades, key=lambda x: (x['entry_d'], x['pos60'] if pick == 'pos60' else rnd.random())):
        ei = bisect.bisect_left(IDXCAL, t['entry_d'])
        xi = bisect.bisect_left(IDXCAL, t['exit_d'])
        openpos = [x for x in openpos if x > ei]
        if len(openpos) < 10:
            openpos.append(xi)
            pnl += t['ret'] * 5000
            taken += 1
            daily.append(t)
        else:
            missed += 1
    return pnl, taken, missed, daily

for label, v2, pick in (('v1 现行：T+5一刀切 + 随机选票', False, 'random'),
                        ('v1b：T+5 + 超跌最深选票', False, 'pos60'),
                        ('v2a：T1分档出场 + 随机选票', True, 'random'),
                        ('v2 全套：T1分档 + 恐慌豁免 + 超跌选票', True, 'pos60')):
    kept = gate(raw, v2)
    if pick == 'random':
        runs = [book(kept, v2, pick, seed=s) for s in (1, 2, 3, 4, 5)]
        pnl = st.mean([r[0] for r in runs])
        taken = int(st.mean([r[1] for r in runs]))
        missed = int(st.mean([r[2] for r in runs]))
        daily = runs[0][3]
    else:
        pnl, taken, missed, daily = book(kept, v2, pick)
    settled = [t for t in daily if '结算' in t['tag']]
    mtm = [t for t in daily if '盯市' in t['tag']]
    print(f'\n== {label} ==')
    print(f'入场 {taken} 笔（槽满错过 {missed}）| 已结算 {len(settled)} | 盯市 {len(mtm)}')
    if settled:
        rs = [t['ret'] for t in settled]
        print(f'已结算：胜率 {100*sum(1 for x in rs if x>0)/len(rs):.0f}% 均笔 {100*st.mean(rs):+.2f}%')
    if mtm:
        rs = [t['ret'] for t in mtm]
        print(f'盯市：胜率 {100*sum(1 for x in rs if x>0)/len(rs):.0f}% 均笔 {100*st.mean(rs):+.2f}%')
    print(f'💰 总盈亏 {pnl:+.0f} 元（5万的 {pnl/500:+.2f}%）')
    bc = {}
    for t in daily:
        bc.setdefault(t['claim'], []).append(t['ret'])
    print('分主张:', {k: f"{len(v)}笔 均{100*st.mean(v):+.2f}%" for k, v in sorted(bc.items())})
    if v2:
        tg = {}
        for t in daily:
            tg.setdefault(t['tag'].replace('结算', '').replace('盯市', ''), []).append(t['ret'])
        print('T1分档:', {k: f"{len(v)}笔 均{100*st.mean(v):+.2f}% 胜率{100*sum(1 for x in v if x>0)/len(v):.0f}%" for k, v in sorted(tg.items())})
        # T1弱桶反事实：这9笔若拿到T+20会怎样（验证"弱票早割"在本窗口是否帮倒忙）
        weak = [t for t in daily if 'T1弱' in t['tag']]
        if weak:
            cf = []
            for t in weak:
                d = stocks[t['code']]
                ei = t['i'] + 1
                if ei + 20 < d['n']:
                    cf.append(d['c'][ei + 20] / lp._epx(d, t['i']) - 1 - FEE)
                elif ei < d['n']:
                    cf.append(d['c'][-1] / lp._epx(d, t['i']) - 1 - FEE)
            print(f"T1弱桶反事实：{len(weak)}笔 T+3离场均{100*st.mean([t['ret'] for t in weak]):+.2f}% vs 拿到T+20均{100*st.mean(cf):+.2f}%")