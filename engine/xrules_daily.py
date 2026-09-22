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
SHADOW = ROOT / "data" / "xrules_shadow.jsonl"
FEE = 0.003
EXIT_N = {'T1-MEGA': 3, 'X2': 5, 'X3': 5}
STOP12 = {'X2', 'X3'}  # X2/X3 带 -12% 止损（T1-MEGA 无止损，T+3 硬出）

DETS_PANIC = {'跌停底座': '组合_跌停低_三连阴', '复活门': '反转族_跌停潮50', '摇篮': '妖股摇篮_成簇',
              'TD9输家': '组合_跌停低_TD9买_输家250', 'TD9超跌': '组合_跌停低_TD9买_超跌20'}
DET_GAP = '组合_缺口低开_低位阳线_避周一'
GATED = {'跌停底座', 'TD9输家', 'TD9超跌'}


def wd_cn(ds):
    return '一二三四五'[date(int(ds[:4]), int(ds[5:7]), int(ds[8:10])).weekday()]


# ── X规则影子盘（前向对账，L5）：触发登记→次日回填→出场结算→汇总 ──
def shadow_load():
    if not SHADOW.exists():
        return []
    return [json.loads(x) for x in SHADOW.read_text().splitlines() if x.strip()]


def shadow_register(entries):
    have = {(e['rule'], e['sig_date'], e['code']) for e in shadow_load()}
    new = [e for e in entries if (e['rule'], e['sig_date'], e['code']) not in have]
    if new:
        with SHADOW.open('a') as f:
            for e in new:
                f.write(json.dumps(e, ensure_ascii=False) + '\n')
    return len(new)


def shadow_backfill(stocks, cal):
    """回填在途单：入场价→T1→出场（T1-MEGA=T+3硬出；X2/X3=T+5或-12%止损先到先出）。
    返回 (汇总dict, 今日新结算list)。"""
    rows = shadow_load()
    if not rows:
        return {}, []
    changed = False
    newly = []
    for e in rows:
        if e.get('status') == 'closed':
            continue
        d = stocks.get(e['code'])
        if not d:
            continue
        didx = {dt: k for k, dt in enumerate(d['date'])}
        ei = didx.get(e['entry_date'])
        if ei is None:
            continue
        n = d['n']
        # 入场价回填
        if e.get('ep') is None and ei < n:
            e['ep'] = d['o'][ei] if d['o'][ei] > 0 else d['c'][ei]
            changed = True
        ep = e.get('ep')
        if not ep:
            continue
        exit_n = EXIT_N[e['rule']]
        exit_i = min(ei + exit_n, n - 1)
        # 止损（X2/X3）：入场后每日收盘 ≤ ep*0.88 → 当日收盘出
        stop_i = None
        if e['rule'] in STOP12:
            for j in range(ei, min(ei + exit_n, n)):
                if d['c'][j] / ep - 1 <= -0.12:
                    stop_i = j
                    break
        final_i = min(stop_i, exit_i) if stop_i is not None else exit_i
        if cal[-1] >= d['date'][final_i] and final_i < n:
            e['exit_date'] = d['date'][final_i]
            e['exit_px'] = d['c'][final_i]
            e['ret'] = round(d['c'][final_i] / ep - 1 - FEE, 4)
            e['status'] = 'closed'
            e['how'] = '止损' if (stop_i is not None and final_i == stop_i) else f'T+{exit_n}'
            changed = True
            newly.append(e)
    if changed:
        SHADOW.write_text('\n'.join(json.dumps(e, ensure_ascii=False) for e in rows) + '\n')
    summ = {}
    for e in rows:
        if e.get('status') != 'closed':
            continue
        s = summ.setdefault(e['rule'], {'n': 0, 'wins': 0, 'rets': []})
        s['n'] += 1
        s['wins'] += 1 if e['ret'] > 0 else 0
        s['rets'].append(e['ret'])
    out = {r: {'n': s['n'], 'win%': round(100 * s['wins'] / s['n'], 0),
               'mean%': round(100 * sum(s['rets']) / s['n'], 2)} for r, s in summ.items()}
    open_n = {}
    for e in rows:
        if e.get('status') != 'closed':
            open_n[e['rule']] = open_n.get(e['rule'], 0) + 1
    for r, s in out.items():
        s['open'] = open_n.get(r, 0)
    return out, newly


def main():
    stocks = lp.load_universe()
    lp.build_xsection(stocks)
    regime = lp.load_regime()
    idx = json.loads((ROOT / "data/index_sh000001.json").read_text())
    cal = [k['date'] for k in idx]
    day = sys.argv[1] if len(sys.argv) > 1 else cal[-1]
    # 覆盖率闸（2026-09-21 实锤：baostock 断链只更了 328/3377，不全数据会写出垃圾判定
    # 并覆盖掉前一晚的正确状态——低于 60% 拒绝写 state，退出码 1 让 cron 报警。
    # 只在生产路径（day=最新交易日）启用；历史日重判不受此限）
    if day == cal[-1]:
        _cov = sum(1 for d in stocks.values() if d['date'] and d['date'][-1] == day) / max(len(stocks), 1)
        if _cov < 0.6:
            print(f"🚨 X规则线 {day}: big_kcache 覆盖率仅 {_cov:.0%}（<60%），数据不全拒绝判定——kcache 可能断链，速查")
            sys.exit(1)
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
        # 2026-09-21 致命 off-by-one 修复：原条件 `i+1 >= d['n'] or lp._epx(d,i)<=0` 把
        # 「信号日=最新一根」全部跳过——生产路径（判定当日）永远零信号，只有历史日回测能出票。
        # 探测器只需要 ≤i 的历史，入场在明天，不需要 i+1 存在。
        if i is None or i < lp.START:
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

    # 影子盘：先回填历史在途单（今日收盘价=最新一根）
    shadow_sum, newly_closed = shadow_backfill(stocks, cal)

    state = {'date': day, 'regime': rg, 'ldc': ldc, 'gap_cluster': len(gap_sigs),
             'panic_cluster': pan_cl, 'streak': streak.get(day, 0), 'entry_day': entry_d,
             'rules': {}, 'shadow': shadow_sum}
    msgs = []
    if newly_closed:
        for e in newly_closed[:5]:
            msgs.append(f"📒 影子结算 {e['rule']} {e['code']} {e.get('name', '')} {100 * e['ret']:+.1f}%（{e['how']}）")
    shadow_entries = []

    # ── T1-MEGA v2 ──
    # 2026-09-22 解剖台复验（#152）：生产语境下 vr<1 票有毒（42%/-1.16%，近年段 -3.28%）→ 选票剔 vr<1；
    # 梯队≥3 优先维持（妖股期语境双段复验成立 56%/+1.34% vs <3 35%/-1.24%）。
    tier = 1.0 if rg in ('妖股期', '恐慌期') else 0.5
    if len(gap_sigs) >= 20 and entry_d:
        ranked = sorted(gap_sigs, key=lambda r: (-(r['ladder'] >= 3), -r['vr']))
        picks = [r for r in ranked if r['vr'] >= 1][:10]
        dropped = len(ranked[:10]) - len(picks)
        state['rules']['T1-MEGA'] = {'fired': bool(picks), 'tier': tier,
                                     'picks': [{k: r[k] for k in ('code', 'name', 'vr', 'ladder', 'pos60')} for r in picks],
                                     'vr_dropped': dropped}
        if picks:
            msgs.append(f"🔥 T1-MEGA v2 触发（缺口低簇 {len(gap_sigs)}≥20，{rg}={'全仓' if tier == 1 else '半仓'}）：")
            for r in picks:
                lad = f" 梯队{r['ladder']}板" if r['ladder'] >= 3 else ''
                msgs.append(f"   {r['code']} {r['name']} 量比{r['vr']:.1f}{lad}")
            if dropped:
                msgs.append(f"   （剔量比<1 票 {dropped} 只——解剖台：该档 42%/-1.16% 有毒）")
            msgs.append(f"   买：{entry_d}（周{entry_wd}）开盘分散买入；卖：T+3 收盘（全史组合层 55%/+4.45%均笔）")
            for r in picks:
                shadow_entries.append({'rule': 'T1-MEGA', 'sig_date': day, 'code': r['code'],
                                       'name': r['name'], 'entry_date': entry_d, 'ep': None, 'status': 'open'})
        else:
            state['rules']['T1-MEGA']['why'] = '簇≥20 但排序前10全部量比<1（有毒档全剔）→ 不出票'
    else:
        state['rules']['T1-MEGA'] = {'fired': False, 'why': f"簇{len(gap_sigs)}<20"}

    # ── X3（浅跌前三，梯队标签）；X2 已停用（2026-09-22 解剖台：12 维无一活格 t<2.3，组合层实测拖后腿）──
    shallow = sorted(pan_sigs, key=lambda r: -r['pos60'])
    x3_ok = rg == '恐慌期' and streak.get(day, 0) >= 2 and big
    if entry_d and date(int(entry_d[:4]), int(entry_d[5:7]), int(entry_d[8:10])).weekday() == 0:
        x3_ok = False  # 跳周一
    state['rules']['X2'] = {'fired': False, 'why': '已停用（2026-09-22 解剖台全维无活格）',
                            'retired': True}
    for rule, ok in (('X3', x3_ok),):
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
            for r in picks:
                shadow_entries.append({'rule': rule, 'sig_date': day, 'code': r['code'],
                                       'name': r['name'], 'entry_date': entry_d, 'ep': None, 'status': 'open'})
        else:
            why = ('非妖股/恐慌期' if rg not in ('妖股期', '恐慌期')
                   else ('恐慌streak<2（第2天才接）' if rg == '恐慌期' and streak.get(day, 0) < 2
                         else '非大簇日' if not big
                         else '入场日=周一跳过' if entry_d and date(int(entry_d[:4]), int(entry_d[5:7]), int(entry_d[8:10])).weekday() == 0
                         else ('无恐慌族信号' if not shallow else '?')))
            if rule == 'X3' and rg != '恐慌期':
                why = '非恐慌期'
            state['rules'][rule] = {'fired': False, 'why': why}

    # ── 公告排雷（2026-09-22 移植层）：出票过东财公告审查，hard_excluded 从名单+影子同步剔除 ──
    try:
        import announcement_vet
        _codes = sorted({e['code'] for e in shadow_entries})
        _vet = announcement_vet.vet_batch(_codes) if _codes else {}
        _killed = {c for c, v in _vet.items() if v.get('status') == 'hard_excluded'}
        if _killed:
            msgs.append(f"🚫 公告排雷剔除 {len(_killed)} 只：" + "、".join(
                f"{c}({','.join(_vet[c]['hard_flags'])})" for c in sorted(_killed)))
            shadow_entries = [e for e in shadow_entries if e['code'] not in _killed]
            for _r in state['rules'].values():
                if _r.get('picks'):
                    _r['picks'] = [p for p in _r['picks'] if p['code'] not in _killed]
                    if not _r['picks']:
                        _r['fired'] = False
                        _r['why'] = (_r.get('why') or '') + '；全部票被公告排雷剔除'
        _rev = [f"{c}({','.join(v['review_flags'])})" for c, v in sorted(_vet.items())
                if v.get('status') in ('review', 'review_light')]
        if _rev:
            msgs.append(f"📰 公告需复核：{'、'.join(_rev)}")
    except Exception as _e:
        msgs.append(f"📰 公告排雷数据源不可达（{type(_e).__name__}）——名单未经审查")

    OUT.write_text(json.dumps(state, ensure_ascii=False, indent=1))
    n_reg = shadow_register([e for e in shadow_entries if e['entry_date']])
    if n_reg:
        msgs.append(f"📒 影子登记 {n_reg} 单（{entry_d} 入场回填待跟）")
    if msgs:
        print(f"⚔️ X规则线 {day}（{rg}）判定")
        print("\n".join(msgs))


if __name__ == '__main__':
    main()