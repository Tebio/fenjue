"""G3 regime 重审（2026-09-20）：regime 时间轴 9/19 13:04 重建后，旧主张的 G3 分段可能漂移。
单遍宇宙扫全部有 detector 的注册主张，按当前时间轴重算 regime 分段（run_pipeline 同款口径：
_epx 入场、T+5、净-0.15%、START=65、hi=n-21），套 G3 修正判据，与注册状态对账。"""
import json, sys, statistics as st
sys.path.insert(0, 'engine')
import yaml
import law_pipeline as lp

stocks = lp.load_universe()
lp.build_xsection(stocks)
regime = lp.load_regime()
claims = yaml.safe_load(open('data/claims_registry.yaml'))['claims']

# 主张 -> detector 映射（只审有 detector 且在 REGISTRY 的）
targets = []
for c in claims:
    det = c.get('detector')
    if det and det in lp.REGISTRY:
        targets.append((c['id'], det))
print(f'有 detector 的主张: {len(targets)} / 总 {len(claims)}')

dets = {det: lp.REGISTRY[det] for _, det in targets}
# 单遍收集：det -> regime -> [T+5 净收益]
buckets = {det: {} for det in dets}
FEE = 0.0015
H = 5
for code, d in stocks.items():
    n = d['n']
    hi = n - max(lp.HORIZONS) - 1
    dates = d['date']
    for i in range(lp.START, hi):
        if lp._epx(d, i) <= 0:
            continue
        rg = regime.get(dates[i], '?')
        r = None
        for det, fn in dets.items():
            try:
                if fn(d, i):
                    if r is None:
                        r = d['c'][i + H] / lp._epx(d, i) - 1 - FEE
                    buckets[det].setdefault(rg, []).append(r)
            except Exception:
                pass

def g3(cells):
    cells = {k: v for k, v in cells.items() if v}
    if len(cells) >= 3:
        return sum(1 for v in cells.values() if v['m'] > 0) >= len(cells) - 1
    return bool(cells) and all(v['m'] > 0 for v in cells.values())

print('\n== G3 重审（当前时间轴） ==')
flips = []
for cid, det in targets:
    cells = {}
    for rg, rs in buckets[det].items():
        if len(rs) >= 30:
            cells[rg] = {'n': len(rs), 'm': round(100 * st.mean(rs), 2),
                         'w': round(100 * sum(1 for x in rs if x > 0) / len(rs), 1)}
    ok = g3(cells)
    flag = '' if ok else '  ← G3 FAIL'
    if not ok:
        flips.append(cid)
    print(f'{cid} [{det}]: G3={"PASS" if ok else "FAIL"}{flag}')
    for rg, v in sorted(cells.items()):
        print(f'    {rg}: n={v["n"]} 均值{v["m"]:+.2f}% 胜率{v["w"]}%')
print(f'\nG3 FAIL 清单: {flips}')
json.dump({'claims': [cid for cid, _ in targets],
           'g3_fail': flips,
           'detail': {det: {rg: {'n': len(rs), 'mean%': round(100*st.mean(rs), 2)}
                            for rg, rs in buckets[det].items() if len(rs) >= 30}
                      for _, det in targets}},
          open('data/g3_reaudit_20260920.json', 'w'), ensure_ascii=False, indent=1)
print('saved data/g3_reaudit_20260920.json')