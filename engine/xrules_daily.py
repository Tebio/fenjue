#!/usr/bin/env python3
"""engine/xrules_daily.py — X规则线每日判定（19:15 BJT cron，kcache 18:30 刷新后跑）。
三条线全保真口径（law_pipeline 探测器+更新后 kcache，无前视）：
  T1-MEGA v2：任意 regime 缺口低簇≥20 → 次日开盘量比前10（妖股/恐慌全仓、平淡/主线半仓）→ T+3 收盘
  X2：妖股/恐慌期 + 大簇日（恐慌族簇≥5 或 缺口低簇≥8 或 ldc≥30）→ 浅跌前三 → T+5/-12%
      （恐慌期需 streak≥2；入场日周一跳过）
  X3：恐慌期 streak≥2 + 大簇日 → 浅跌前三 → T+5/-12%
输出：触发才打印（看门狗）；状态恒落盘 data/xrules_state.json 供作战单/面板读取。
用法：python xrules_daily.py [YYYY-MM-DD]（默认=kcache 最新交易日；可回测任意日）
"""
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import law_pipeline as lp

ROOT = Path("/opt/data/fenjue")
OUT = ROOT / "data" / "xrules_state.json"
FEE = 0.003

DETS_PANIC = {'跌停底座': '组合_跌停低_三连阴', '复活门': '反转族_跌停潮50', '摇篮': '妖股摇篮_成簇',
              'TD9输家': '组合_跌停低_TD9买_输家250', 'TD9超跌': '组合_跌停低_TD9买_超跌20'}
DET_GAP = '组合_缺口低开_低位阳线_避周一'
GATED = {'跌停底座', 'TD9输家', 'TD9超跌'}


def wd_cn(ds):
    return '一二三四五'[date(int(ds[:4]), int(ds[5:7]), int(ds[8:10])).weekday()]


def main():
    stocks = lp.load_universe()
    lp.build_xsection(stocks)
    regime = lp.load_regime()
    idx = json.loads((ROOT / "data/index_sh000001.json").read_text())
    cal = [k['date'] for k in idx]
    day = sys.argv[1] if len(sys.argv) > 1 else cal[-1]
    # 行业映射与名单
    mmap = json.loads((ROOT / "data/industry_map.json").read_text())
    code2ind = {str(k).zfill(6): v['industry'] for k, v in mmap.items() if isinstance(v, dict) and v.get('industry')}
    names = {str(s['code']).zfill(6): s.get('name', '')
             for s in json.loads((ROOT / "data/main_board_codes.json").read_text()).get('stocks', [])}
    # 恐慌 streak
    streak = {}
    s = 0
    for k in idx:
        s = s + 1 if regime.get(k['date']) == '恐慌期' else 0
        streak[k['date']] = s
    # 行业→日→涨停数（当日）
    sec_board = defaultdict(int)
    for code, d in stocks.items():
        didx = {dt: k for k, dt in enumerate(d['date'])}
        d['_didx'] = didx
        i = didx.get(day)
        if i and i >= 1 and d['c'][i] / d['c'][i - 1] - 1 >= 0.098:
            sec_board[code2ind.get(code, '')] += 1
    # 信号收集（当日）
    gap_sigs, pan_sigs = [], []
    for code, d in stocks.items():
        i = d['_didx'].get(day)
        if i is None or i < lp.START or i + 1 >= d['n'] or lp._epx(d, i) <= 0:
            continue
        c, h, v = d['c'], d['h'], d['v']
        hi60 = max(h[max(0, i - 60):i]) if i >= 1 else 0
        pos60 = c[i - 1] / hi60 - 1 if hi60 > 0 else 0
        vols = [v[x] for x in range(max(1, i - 5), i)]
        vr = v[i] / (sum(vols) / len(vols)) if vols and sum(vols) > 0 else 1
        ind = code2ind.get(code, '')
        rec = {'code': code, 'name': names.get(code, ''), 'pos60': pos60, 'vr': vr,
               'ind': ind, 'ladder': sec_board.get(ind, 0)}
        try:
            if lp.REGISTRY[DET_GAP](d, i):
                gap_sigs.append(rec)
        except Exception:
            pass
        for cn, dn in DETS_PANIC.items():
            try:
                if lp.REGISTRY[dn](d, i):
                    pan_sigs.append({**rec, 'claim': cn})
            except Exception:
                pass
    rg = regime.get(day, '?')
    ldc = lp._XLDC.get(day, 0)
    pan_cl = len({r['code'] for r in pan_sigs if r['claim'] in GATED})
    big = pan_cl >= 5 or len(gap_sigs) >= 8 or ldc >= 30
    entry_d = cal[cal.index(day) + 1] if day in cal and cal.index(day) + 1 < len(cal) else None
    entry_wd = wd_cn(entry_d) if entry_d else '?'

    state = {'date': day, 'regime': rg, 'ldc': ldc, 'gap_cluster': len(gap_sigs),
             'panic_cluster': pan_cl, 'streak': streak.get(day, 0), 'entry_day': entry_d,
             'rules': {}}
    msgs = []

    # ── T1-MEGA v2 ──
    tier = 1.0 if rg in ('妖股期', '恐慌期') else 0.5
    if len(gap_sigs) >= 20 and entry_d:
        picks = sorted(gap_sigs, key=lambda r: (-(r['ladder'] >= 3), -r['vr']))[:10]
        state['rules']['T1-MEGA'] = {'fired': True, 'tier': tier,
                                     'picks': [{k: r[k] for k in ('code', 'name', 'vr', 'ladder', 'pos60')} for r in picks]}
        msgs.append(f"🔥 T1-MEGA v2 触发（缺口低簇 {len(gap_sigs)}≥20，{rg}={'全仓' if tier == 1 else '半仓'}）：")
        for r in picks:
            lad = f" 梯队{r['ladder']}板" if r['ladder'] >= 3 else ''
            msgs.append(f"   {r['code']} {r['name']} 量比{r['vr']:.1f}{lad}")
        msgs.append(f"   买：{entry_d}（周{entry_wd}）开盘分散买入；卖：T+3 收盘（全史组合层 55%/+4.45%均笔）")
    else:
        state['rules']['T1-MEGA'] = {'fired': False, 'why': f"簇{len(gap_sigs)}<20"}

    # ── X2 / X3（浅跌前三，梯队标签）──
    shallow = sorted(pan_sigs, key=lambda r: -r['pos60'])
    x3_ok = rg == '恐慌期' and streak.get(day, 0) >= 2 and big
    x2_ok = rg in ('妖股期', '恐慌期') and big and not (rg == '恐慌期' and streak.get(day, 0) < 2)
    if entry_d and date(int(entry_d[:4]), int(entry_d[5:7]), int(entry_d[8:10])).weekday() == 0:
        x3_ok = x2_ok = False  # 跳周一
    for rule, ok in (('X2', x2_ok), ('X3', x3_ok)):
        if ok and shallow:
            picks = shallow[:3]
            state['rules'][rule] = {'fired': True,
                                    'picks': [{**{k: r[k] for k in ('code', 'name', 'pos60', 'ladder')},
                                               'claim': r['claim']} for r in picks]}
            msgs.append(f"🗡 {rule} 触发（{rg} 大簇 恐慌族{pan_cl}/缺口低{len(gap_sigs)}/ldc{ldc}）：浅跌前三")
            for r in picks:
                lad = f" 梯队{r['ladder']}板" if r['ladder'] >= 3 else ''
                msgs.append(f"   {r['code']} {r['name']} {r['claim']} 距60高{r['pos60']:.0%}{lad}")
            msgs.append(f"   买：{entry_d}（周{entry_wd}）开盘；卖：T+5 收盘或 -12% 止损")
        else:
            why = ('非妖股/恐慌期' if rg not in ('妖股期', '恐慌期')
                   else ('恐慌streak<2（第2天才接）' if rg == '恐慌期' and streak.get(day, 0) < 2
                         else '非大簇日' if not big
                         else '入场日=周一跳过' if entry_d and date(int(entry_d[:4]), int(entry_d[5:7]), int(entry_d[8:10])).weekday() == 0
                         else ('无恐慌族信号' if not shallow else '?')))
            if rule == 'X3' and rg != '恐慌期':
                why = '非恐慌期'
            state['rules'][rule] = {'fired': False, 'why': why}

    OUT.write_text(json.dumps(state, ensure_ascii=False, indent=1))
    if msgs:
        print(f"⚔️ X规则线 {day}（{rg}）判定")
        print("\n".join(msgs))


if __name__ == '__main__':
    main()