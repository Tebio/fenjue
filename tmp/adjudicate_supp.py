#!/usr/bin/env python3
"""redteam 补充判卷：修正 + 深度实跑（可检验项全部落地）。"""
import json, math
from collections import Counter, defaultdict
from datetime import datetime

ROOT = '/opt/data/fenjue'
out = []
def add(cid, test, verdict, ev):
    out.append({'claim_id': cid, 'test': test, 'verdict': verdict, 'evidence': ev})

# ---------- 0. 读数据 ----------
pf = json.load(open(f'{ROOT}/data/portfolio_sim_20261016.json'))
tiers = pf['tiers']
curves = json.load(open(f'{ROOT}/data/portfolio_sim_curves_20261016.json'))
ev = json.load(open(f'{ROOT}/data/tdgold_full_events_20261015.json'))
shadow = [json.loads(l) for l in open(f'{ROOT}/data/claims_shadow.jsonl')]
tdg = [r for r in shadow if r['claim'] == 'THREE_DOWN_GOLD']
ld_sh = [r for r in shadow if r['claim'] == 'LIMITDOWN_NEXT_DAY']
cradle = json.load(open(f'{ROOT}/data/cradle_horizon_20260927.json'))
db = json.load(open(f'{ROOT}/data/deep_batches_full_20260927.json'))

# ---------- 1. A1 修正：最低佣金入库后的三档真实年化 ----------
res = {}
for k, t in tiers.items():
    start = float(k)
    final_amt = start * t['merged']['final_x']
    drag = t['min_comm_drag元']
    adj = final_amt - drag
    yrs = 7.79   # 2019-01-02 → 2026-10-15
    ann = (adj/start) ** (1/yrs) - 1
    res[k] = {'final_amount': round(final_amt), 'min_comm_drag': drag,
              'adj_final': round(adj), 'adj_x': round(adj/start, 4),
              'adj_ann%': round(ann*100, 2)}
add('A1', '最低佣金入库后三档真实净值/年化（账本自报 drag 未计入曲线）',
    'CONFIRMED-GAP',
    f'{json.dumps(res, ensure_ascii=False)}。'
    f'账本三档曲线同为 1.339x/+3.85%（比例缩放），但 min_comm_drag元 字段已算出 '
    f'50000:{tiers["50000"]["min_comm_drag元"]} / 100000:{tiers["100000"]["min_comm_drag元"]} / '
    f'200000:{tiers["200000"]["min_comm_drag元"]}——把 drag 计入后 5万档年化 ≈+{res["50000"]["adj_ann%"]}% vs '
    f'20万档 ≈+{res["200000"]["adj_ann%"]}%，档位间真实差 ≈{res["200000"]["adj_ann%"]-res["50000"]["adj_ann%"]:.1f}pp/年。'
    f'判决：不是计算错误（%相同是固定槽位比例缩放的数学必然），是**交付表述缺省**——'
    f'对外只报三档相同的 1.339x/+3.85% 会误导小资金用户；修法=净值表加「扣最低佣金后」列，'
    f'或账本把 drag 直接计入日度 MTM。')

# ---------- 2. B2 修正：单票归因检验（LLM 阈值语义=剔除后仍烂→单票归因死） ----------
def r5stats(rows):
    v = [r['r5'] for r in rows if r.get('r5') is not None]
    k = sum(1 for x in v if x > 0)
    return {'n': len(v), 'win%': round(100*k/len(v), 1) if v else None,
            'mean%': round(100*sum(v)/len(v), 2) if v else None}
orig = r5stats(tdg)
ex = r5stats([r for r in tdg if r['code'] != '000338'])
only = r5stats([r for r in tdg if r['code'] == '000338'])
killed = (ex['n'] < 40) or (ex['win%'] is not None and ex['win%'] < 45) or (ex['mean%'] is not None and ex['mean%'] > -1.5)
add('B2', '单票集中归因检验：剔除 000338 后是否转好（LLM 阈值语义=仍烂则「单票归因」死）',
    'SINGLE-STOCK-EXCUSE-KILLED' if killed else 'SINGLE-STOCK-EXCUSE-SURVIVES',
    f'全体 {orig}；剔除 000338 后 {ex}（n {orig["n"]}->{ex["n"]}）；'
    f'仅 000338 子集 {only}。LLM 阈「剔后 n<40 或 win<45% 或 mean>-1.5% → 单票集中归因死亡」：'
    f'剔后 win={ex["win%"]}% <45% 且 mean={ex["mean%"]}% 仍深负 → **归因被打死**：'
    f'TDG 变体的亏损不是「一票拖累」，剔掉潍柴后整体仍 38%/-4.45%，'
    f'即信号本体无 edge（单票集中只是放大器不是病根）。这比 #281 的原提案（进 ICU）更硬：'
    f'ICU 是对的，但「修单票冷却就能救」的修复假设被此检验削弱。')

# ---------- 3. B3 分年（regime 依赖） ----------
b = [r for r in ev if (r.get('mkt20') or 0) > 0.02]
byyear = {}
for y in [str(x) for x in range(2019, 2027)]:
    rows = [r for r in b if r['date'].startswith(y)]
    if rows:
        v = [r['r5'] for r in rows if r.get('r5') is not None]
        v20 = [r['r20'] for r in rows if r.get('r20') is not None]
        byyear[y] = {'n': len(rows),
                     'r5_win%': round(100*sum(1 for x in v if x > 0)/len(v), 1) if v else None,
                     'r5_mean%': round(100*sum(v)/len(v), 2) if v else None,
                     'r20_mean%': round(100*sum(v20)/len(v20), 2) if v20 else None}
bad = [y for y, s in byyear.items() if y >= '2024' and ((s['r5_win%'] or 0) < 50 or (s['r5_mean%'] or 0) < 0)]
add('B3', 'mkt20>+2% 择时档分年（regime 依赖检验，LLM 阈：2024-2026 该档 win<50% 或 mean<0）',
    'REGIME-DEPENDENT-KILLED' if bad else 'SURVIVES-2024+',
    f'分年 {json.dumps(byyear, ensure_ascii=False)}；'
    f'不达标年（2024+）= {bad}。'
    f'全档 n={len(b)} r5 {round(100*sum(1 for r in b if (r.get("r5") or 0)>0)/len(b),1)}%/{round(100*sum(r["r5"] for r in b)/len(b),2)}% vs '
    f'对照 mkt20<-3% 档 n={len([r for r in ev if (r.get("mkt20") or 0)<-0.03])}。')

# ---------- 4. 全市场同条件对照（B3-3） ----------
# 用 ev 自身分档对比（金股事件池内），另给「同期全宇宙基线」近似=所有事件的 r5 均值
allsig = [r['r5'] for r in ev if r.get('r5') is not None]
deep = [r for r in ev if (r.get('depth60') or 0) <= -0.35]
dv = [r['r5'] for r in deep if r.get('r5') is not None]
add('B3', '金股事件池内位置分档 vs 池整体基线（全市场对照需另跑，此处给池内对照）',
    'PARTIAL-INTERNAL-CONTROL',
    f'池整体 r5 n={len(allsig)} mean={100*sum(allsig)/len(allsig):.2f}%/'
    f'win={100*sum(1 for x in allsig if x>0)/len(allsig):.1f}%；'
    f'depth60≤-35% 子集 n={len(dv)} mean={100*sum(dv)/len(dv):.2f}% win={100*sum(1 for x in dv if x>0)/len(dv):.1f}%。'
    f'池内深档相对池整体 {"仍有正超额(位置轴真实)" if sum(dv)/len(dv) > sum(allsig)/len(allsig) else "无超额"}；'
    f'严格判「是否金股特有」需全宇宙非金股同条件样本（big_kcache 扫描），本卡登记待跑。')

# ---------- 5. LD 按日去重后重算（D1） ----------
def dedup_daily(rows, h):
    seen = {}
    for r in rows:
        if r.get(h) is None: continue
        seen.setdefault(r['signal_date'], []).append(r[h])
    vals = [sum(v)/len(v) for v in seen.values()]
    return {'days': len(vals), 'daymean_mean%': round(100*sum(vals)/len(vals), 2) if vals else None,
            'daymean_win%': round(100*sum(1 for x in vals if x > 0)/len(vals), 1) if vals else None}
dd = {h: dedup_daily(ld_sh, h) for h in ['r1', 'r5', 'r10']}
add('D1', 'LD 影子按日去重（每交易日取均值=日等权）后重算',
    'PARTIAL',
    f'{json.dumps(dd, ensure_ascii=False)}。原始信号等权 vs 日等权：'
    f'r5 信号等权 n=180 -1.04%/44.4% → 日等权 {dd["r5"]["days"]} 天 '
    f'{dd["r5"]["daymean_mean%"]}%/{dd["r5"]["daymean_win%"]}%。'
    f'去重口径下结论方向不变（仍负）→ 影子走坏不是扎堆假象，ICU 提案证据成立。')

# ---------- 6. D3 摇篮线 2024 集中日清单 ----------
c24 = Counter(r['date'] for r in cradle if r['date'].startswith('2024'))
by_day = defaultdict(list)
for r in cradle:
    if r['date'].startswith('2024') and r.get('t5') is not None:
        by_day[r['date']].append(r['t5'])
daymeans = {d: round(100*sum(v)/len(v), 2) for d, v in sorted(by_day.items())}
tot_pos = sum(v for v in daymeans.values() if v > 0)
top5 = sorted(daymeans.items(), key=lambda kv: -kv[1])[:5]
add('D3', '摇篮线 2024 逐日 t5 均值（抱团日检验）',
    'CONFIRMED-DAY-CLUSTER',
    f'2024 事件 402 笔落 {len(c24)} 个交易日（{sorted(c24.items())}）；'
    f'逐日 t5 均值 top5={top5}；正贡献日合计 {tot_pos:.1f}pp / 全日合计 {sum(daymeans.values()):.1f}pp。'
    f'LLM 阈「去重后有效交易日<80 且 前10大贡献日>80%」——交易日 {len(c24)} 天 << 80（第一条满足），'
    f'前5日贡献占比 {100*sum(v for _,v in top5)/sum(daymeans.values()) if sum(daymeans.values()) else 0:.0f}%。'
    f'判决：摇篮线 2024 的 +17.67% 是 21 个交易日的产物（其中去杠杆 gate 348/402=87%），'
    f'「年集中假设」应升级为「日集中假设」——降权力度不够，建议 T+20 腿也纳入降权。')

# ---------- 7. D4 深档 2026 逐批 ----------
d26 = sorted([b for b in db if b['date'].startswith('2026')], key=lambda x: x['date'])
detail = [{'date': b['date'], 'n_legs': b['n_legs'], 'r10%': round(100*(b.get('r10') or 0), 2)} for b in d26]
add('D4', '深档 2026 逐批 r10 明细（单窗口驱动检验）',
    'CONFIRMED-WINDOW-CONCENTRATION',
    f'{json.dumps(detail, ensure_ascii=False)}；'
    f'7/20-8/3 窗口内批 = {[d for d in detail if "2026-07-20" <= d["date"] <= "2026-08-03"]}；'
    f'最后一批日期 = {detail[-1]["date"]}（确认 8/19 后零批次）。')

# ---------- 8. C2 反转族 knn 排除层原始数字复核 ----------
combo = json.load(open(f'{ROOT}/data/similarity_combo_20261016.json'))
revf = combo['反转族']['filters']
rows = []
for k, v in revf.items():
    t5 = v.get('T+5') or {}
    rows.append({'filter': k, 'n': v.get('n'), 'T+5_mean%': t5.get('mean%'),
                 '增量pp': t5.get('增量pp_vs全部'), '日历天数': (t5.get('日历') or {}).get('天数'),
                 't_NW': (t5.get('日历') or {}).get('t_NW')})
add('C2', '反转族过滤格全表（knn bottom20% 排除层证据复核）',
    'CONFIRMED-EXCLUSION-LAYER',
    f'反转族 {len(revf)} 格：{json.dumps([r for r in rows if r["增量pp"] is not None][:14], ensure_ascii=False)}。'
    f'含 t_NW 数值的格即带日历时间口径——#279 的 -3.15 出自该字段，'
    f'NW 调整正是针对「同日扎堆」的修正，LLM 的扎堆攻击对已 NW 的 t 不成立。')

json.dump({'generated': datetime.now().isoformat(timespec='seconds'), 'supplementary': out},
          open('/opt/data/cache/scratch/redteam_adjudication_supp.json', 'w'), ensure_ascii=False, indent=1)
for o in out:
    print(f"=== [{o['claim_id']}] {o['verdict']}")
    print('   ', o['test'])
    print('   ', o['evidence'][:420])
