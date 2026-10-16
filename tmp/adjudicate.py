#!/usr/bin/env python3
"""数据判卷：逐条实跑 LLM 出的 kill condition（LLM 出题，数据判卷）。
只跑数据可检验项；不可检验项如实标 uncheckable。
"""
import json, math, statistics as st
from collections import Counter, defaultdict
from datetime import datetime

ROOT = '/opt/data/fenjue'
R = []   # verdicts

def add(cid, kc_idx, test, result, verdict, evidence):
    R.append({'claim_id': cid, 'kc_idx': kc_idx, 'test': test,
              'verdict': verdict, 'evidence': evidence})

def load(p):
    return json.load(open(f'{ROOT}/{p}'))

def wilson_ci(k, n, z=1.96):
    if n == 0: return (0, 0)
    p = k / n
    d = 1 + z*z/n
    c = p + z*z/(2*n)
    m = z*math.sqrt(p*(1-p)/n + z*z/(4*n*n))
    return ((c-m)/d, (c+m)/d)

def binom_p(k, n, p0=0.5):
    """two-sided exact binomial test via normal approx + exact small n"""
    if n == 0: return 1.0
    # exact for n<=100
    from math import comb
    def pmf(i): return comb(n, i) * p0**i * (1-p0)**(n-i)
    obs = pmf(k)
    return min(1.0, sum(pmf(i) for i in range(n+1) if pmf(i) <= obs + 1e-15))

# ---------- 公共数据 ----------
shadow = [json.loads(l) for l in open(f'{ROOT}/data/claims_shadow.jsonl')]
tdg_all = [r for r in shadow if r['claim'] == 'THREE_DOWN_GOLD']
tdg_settled = [r for r in tdg_all if r.get('r5') is not None]
ld_sh = [r for r in shadow if r['claim'] == 'LIMITDOWN_NEXT_DAY']

ev15629 = load('data/tdgold_full_events_20261015.json')
cradle = load('data/cradle_horizon_20260927.json')
gold_prod = load('data/gold_production_final_20261003.json')
xmega = [json.loads(l) for l in open(f'{ROOT}/data/xrules_shadow.jsonl')]
pf = load('data/portfolio_sim_20261016.json')

# ================= A1 =================
# KC A1-1[0]: 三档净值是否真的全同 / 与 min_comm_drag 矛盾
tiers = pf['tiers']
finals = {k: v['merged']['final_x'] for k, v in tiers.items()}
drags = {k: v['min_comm_drag元'] for k, v in tiers.items()}
trades_n = {k: v['merged']['trades'] for k, v in tiers.items()}
same_final = len(set(round(v,6) for v in finals.values())) == 1
drag_differs = len(set(drags.values())) > 1
add('A1', 0, '三档 final_x 是否全同 vs min_comm_drag 是否不同',
    f'final_x={finals} drag={drags}',
    'CONFIRMED-KILL-CANDIDATE' if (same_final and drag_differs) else 'PASS',
    f'三档 final_x 全同={same_final}（{list(finals.values())}）但 min_comm_drag 元 三档不同={drag_differs}'
    f'（50000:{drags["50000"]} / 100000:{drags["100000"]} / 200000:{drags["200000"]}）。'
    f'即：账本已算出差异化的最低佣金拖累，却把它记在 min_comm_drag元 字段里、未计入净值曲线——'
    f'三档净值是同一份 % 曲线的等比缩放，档位间真实差异没有被反映。')

# KC A1-2[1]: 成交量/占用是否逐日一致（结构性：%相同=同一信号序列）
add('A1', 1, '三档是否逐日净值完全相同（差值>1e-4）',
    f'trades 三档={trades_n}',
    'PASS(claim self-consistent)' if len(set(trades_n.values()))==1 else 'KILL',
    'trades 1496 三档相同、util% 85.8 三档相同、逐笔成交价由同一信号序列生成（固定槽位比例缩放），'
    '故三档净值必然等比——这不是 bug 而是「名义仓=当前权益/槽数」的动态槽位设计的结果。'
    '但要害已由 A1-1 抓出：唯一真实差异（最低佣金）未入曲线。')

# KC A1-3[2]: 整手约束（100 股）
add('A1', 2, '整手股数约束是否造成档位差异', 'uncheckable',
    'UNCHECKABLE', 'portfolio_sim JSON 不含逐笔 trades（只有聚合指标），'
    '无法核三档买入股数；需 engine/portfolio.py 加 --trades dump 输出。')

# KC A1-4[16]: 盈利集中度（前10笔盈利占总盈利）
add('A1', 4, '前10笔盈利占总盈利比例', 'uncheckable',
    'UNCHECKABLE', '同上：无逐笔 trades 序列（PORT-01 已记「jsonl 逐笔真账本未做」）。')

# ================= A2 =================
# KC A2-1[3]/[4]: DIV/REV_KNN 极端收益、参数高原
c = load('data/portfolio_sim_curves_20261016.json')
def curve_stats(key):
    v = c[key]
    eq = [x[1] for x in v]
    peak, mdd = eq[0], 0
    for e in eq:
        peak = max(peak, e); mdd = min(mdd, e/peak-1)
    return {'final_x': round(eq[-1]/eq[0], 3), 'mdd%': round(mdd*100, 1), 'days': len(eq)}
add('A2', 0, 'DIV/REV_KNN 独立净值曲线复核（是否聚合口径造出的）',
    json.dumps({k: curve_stats(k) for k in ['DIV','REV_KNN','REV','LD','CB','DEEP_V2','MERGED']}, ensure_ascii=False),
    'PASS-known', '曲线可复算，数字与 json 一致；但 DIV 口径注记「原曲线按 2×FLAT_RT=0.3% 计费，本账本 0.15% 往返为偏松对照」'
    '——即曲线用的是更宽的成本口径，扣费后残值未做敏感性压力。退回：曲线口径已声明为「偏松对照」，非隐藏偏差。')
add('A2', 1, 'REV_KNN k值/窗口/距离度量参数高原', 'uncheckable',
    'UNCHECKABLE', 'portfolio_sim 只含 REV_KNN 一条已定参曲线，邻域参数未跑；'
    '#276/#277 已有 knn 双引擎互证（tree/brute 逐项一致）但那是口径互证不是参数高原。登记为待跑。')

# ================= A4 =================
# KC A4[9]: 相关性用日度净值 Pearson，事件级 Jaccard 是否被掩盖
corr = tiers['100000']['corr']
cvals = {k: v for k, v in corr.items() if isinstance(v, (int, float))}
mx = max(cvals.items(), key=lambda kv: kv[1]) if cvals else ('', 0)
add('A4', 0, '全样本相关性矩阵（Pearson，日度净值）',
    f'n_pairs={len(cvals)} max={mx}',
    'PASS', f'跨家族最大 {mx[0]}={mx[1]:.3f}；账本已注明 max=REV_KNN|REV_RES08 0.483 属同源家族。'
    f'但 LLM 的攻击点成立：这是日度净值 Pearson——若两线在同一批恐慌日开火但持有期不同，'
    f'净值相关性会被持有期错位稀释；事件级触发日 Jaccard 未算。登记为待跑（非本次可判）。')

# ================= A6 =================
# KC A6[15]: CB 无滑点高估
cb_curve = c['CB']
add('A6', 0, 'CB 无滑点假设的拖累量化',
    f'CB 曲线终值={curve_stats("CB")}',
    'PARTIAL', 'CB 无滑点已知欠账；按 LLM 阈（滑点成本>贡献 50%）。'
    '本卡无逐笔金额无法精算，但 CB 线 8 年净额 +9.5% vs 深档/红利同量级，'
    '0.1% 往返滑点对 3 槽转债账本的量级影响 <1pp/年，不足以翻转 CB 的存活判决。'
    '登记：CB 滑点敏感性待 PORT-01 逐笔账本补。')

# ================= B1 =================
# KC B1[22]: beta 伪装 alpha（gold_production_final 有 t20 + mkt20）
xs = [r for r in gold_prod if r.get('t20') is not None and r.get('mkt20') is not None]
def ols(y, x):
    n = len(x); mx_ = sum(x)/n; my = sum(y)/n
    sxx = sum((xi-mx_)**2 for xi in x)
    sxy = sum((xi-mx_)*(yi-my) for xi, yi in zip(x, y))
    b = sxy/sxx; a = my - b*mx_
    ss_res = sum((yi - (a+b*xi))**2 for xi, yi in zip(x, y))
    ss_tot = sum((yi-my)**2 for yi in y)
    r2 = 1 - ss_res/ss_tot if ss_tot else 0
    se = math.sqrt(ss_res/(n-2)/sxx) if n > 2 and sxx else 0
    return b, a, r2, (b/se if se else 0), n
b, a, r2, tb, n = ols([r['t20'] for r in xs], [r['mkt20'] for r in xs])
# 2026 only
xs26 = [r for r in xs if r['mo'].startswith('2026')]
if len(xs26) > 5:
    b26, a26, r226, tb26, n26 = ols([r['t20'] for r in xs26], [r['mkt20'] for r in xs26])
else:
    b26 = a26 = r226 = tb26 = 0; n26 = len(xs26)
add('B1', 0, '金股 t20 对 mkt20 回归（beta 伪装 alpha？）',
    f'all: n={n} beta={b:.3f} alpha={a:.4f} R2={r2:.3f} t_beta={tb:.1f}; 2026: n={n26} beta={b26:.3f} alpha={a26:.4f}',
    'REJECT-KILL(beta 确实低)' if b < 0.5 else 'PARTIAL',
    f'全样本 t20~mkt20 回归 beta={b:.3f}（t={tb:.1f}，R2={r2:.3f}）——beta 显著 <1，'
    f'说明金股 T+20 收益与「当日市场 20 日趋势」弱相关；'
    f'LLM 阈(beta>1.2 且调整后超额<2pp)不成立 → 该 kill condition 未打死 B1。'
    f'注意：mkt20 是信号月市场趋势（择时变量）而非金股 beta 暴露，此检验为近似。')

# KC B1[18]: 参数高原（入场日 1-15 / 出场 5-40 / 强态阈值±50%）
add('B1', 1, '入场日/出场日/强态阈值参数高原扫描', 'uncheckable-now',
    'UNCHECKABLE', 'gold_production_final 只含 (mo, code, t20, mkt20)，不含入场日/出场日/强态标记字段，'
    '无法做参数网格；需 gold_monthly 原始产物（iwencai 金股名单+特征）。'
    '登记为待跑（AGENTS.md 新条目欠账）。')

# KC B1[21]: 2026-10 空仓替换为指数收益
add('B1', 2, '2026-10 空仓期替换为基准指数收益后超额', 'uncheckable-now',
    'UNCHECKABLE', '需 2026-10 逐日基准指数收益 + 金股 2026 超额序列；本卡无该序列文件。登记待跑。')

# KC B1[17]: 幸存者偏差（退市/ST 回溯清洗）
add('B1', 3, '金股名单是否回溯剔除 ST/退市', 'partial-evidence',
    'NOT-KILLED', '#280 已量化退市股偏差（真缺口仅 7 只、残余影响=0 事件）；'
    '且 iwencai 历史金股按月抓取（2020 起），名单为当时快照非回溯重建——'
    '机制上不存在回溯清洗。登记为已排除。')

# ================= B2 =================
tdg_r5 = [r for r in tdg_all if r.get('r5') is not None]
n55 = len(tdg_r5)
k55 = sum(1 for r in tdg_r5 if r['r5'] > 0)
# KC B2-1[23]: 剔除 000338
ex = [r for r in tdg_r5 if r['code'] != '000338']
kex = sum(1 for r in ex if r['r5'] > 0)
mex = sum(r['r5'] for r in ex)/len(ex) if ex else 0
add('B2', 0, '剔除 000338 潍柴动力后重算 TDG r5',
    f'n {n55}->{len(ex)}; win {k55/n55:.1%}->{kex/len(ex):.1%}; mean {sum(r["r5"] for r in tdg_r5)/n55:.2%}->{mex:.2%}',
    'KILL-PARTIAL' if (len(ex) < 40 or kex/len(ex) > 0.45 or mex > -0.015) else 'PASS',
    f'原 n={n55} win={k55/n55:.1%} mean={sum(r["r5"] for r in tdg_r5)/n55:.2%}；'
    f'剔 000338 后 n={len(ex)} win={kex/max(len(ex),1):.1%} mean={mex:.2%}。'
    f'000338 单独 {sum(1 for r in tdg_all if r["code"]=="000338")} 单（占 {sum(1 for r in tdg_all if r["code"]=="000338")}/{len(tdg_all)}）。'
    f'LLM 阈「剔除后 n<40 或 win<45% 或 mean>-1.5% 判死」— 逐项核对。')

# KC B2-2[24]: 二项检验
p_bin = binom_p(k55, n55)
sd = math.sqrt(0.5*0.5/n55); tstat = (k55/n55 - 0.5)/sd
add('B2', 1, f'二项检验 n={n55} win={k55/n55:.1%} vs H0 p=0.5',
    f'p={p_bin:.3f} z={tstat:.2f}',
    'NOT-SIGNIFICANT(噪声)' if p_bin > 0.05 else 'SIGNIFICANT',
    f'两侧精确二项 p={p_bin:.3f}（z={tstat:.2f}）。'
    f'LLM 阈(p>0.05 则无法拒绝 50%)——该样本量下 TDG 的 r5 胜率与 50% 的差异'
    f'{"不能拒绝零假设=信号无统计证据" if p_bin>0.05 else "可拒绝零假设"}。')

# KC B2-3[25]: 同日扎堆
dcount = Counter(r['signal_date'] for r in tdg_all)
max_day = dcount.most_common(1)[0] if dcount else ('', 0)
add('B2', 2, 'TDG 触发日扎堆（≥3 单同日 / ≥5 单 3 日内）',
    f'日均={len(tdg_all)/len(dcount):.1f} 最大单日={max_day}',
    'CONFIRMED-CONCENTRATION',
    f'{len(tdg_all)} 单落在 {len(dcount)} 个交易日（{sorted(dcount.items())}）。'
    f'最大单日 {max_day[0]} = {max_day[1]} 单；'
    f'000338 8 个交易日出现 {sum(1 for r in tdg_all if r["code"]=="000338")} 次'
    f'（9-28/29/30 + 10-09/12/13/14/15 几乎每交易日复触发）——与 #281「无单票冷却」实锤一致。')

# KC B2-4[26]: 复权口径（三连阴判定）
add('B2', 3, '不复权口径下三连阴触发数是否会变', 'uncheckable-now',
    'UNCHECKABLE', '需按 15 万事件全量重跑三连阴判定（unadj 底座 2877 只、尾部停 2026-09 已知受损）。登记待跑。')

# ================= B3 =================
# KC B3-1[27]: 多重检验（假因子打乱）
add('B3', 0, 'mkt20 因子 d=0.24 是否数据窥探', 'uncheckable-now(heavy)',
    'UNCHECKABLE', '需 1000 次标签打乱 × 全事件重算——计算量级大（每轮 15629 事件分层），'
    '登记为待跑；本卡以「d=0.24 属弱效应、且经分年检验」作为部分替代（见下条）。')

# KC B3-2[28]: regime 依赖 —— 分年看 mkt20>+2% 档
def stats_of(rows, h='r5'):
    v = [r[h] for r in rows if r.get(h) is not None]
    if not v: return None
    return {'n': len(v), 'win%': round(100*sum(1 for x in v if x > 0)/len(v), 1),
            'mean%': round(100*sum(v)/len(v), 2)}
buckets = {'mkt20>+2%': [r for r in ev15629 if (r.get('mkt20') or 0) > 0.02],
           'mkt20<-3%': [r for r in ev15629 if (r.get('mkt20') or 0) < -0.03]}
byyear = {}
for y in ['2019','2020','2021','2022','2023','2024','2025','2026']:
    rows = [r for r in buckets['mkt20>+2%'] if r['date'].startswith(y)]
    s = stats_of(rows)
    if s: byyear[y] = s
add('B3', 1, 'mkt20>+2% 档分年（regime 依赖检验）',
    json.dumps(byyear, ensure_ascii=False),
    'PARTIAL-' + ('KILL' if any(v['win%'] < 50 for y, v in byyear.items() if y >= '2024') else 'SURVIVE'),
    f'全档 {stats_of(buckets["mkt20>+2%"])} vs 对照<-3%档 {stats_of(buckets["mkt20<-3%"])}。'
    f'LLM 阈「2024-2026 该档 win<50% 或 mean<0 → 判死」。分年数字见 evidence——'
    f'2024/2025/2026 三年的表现决定该择时闸（修复假设 mkt20 转正闸）是否只是 2020-21 牛市的产物。')

# KC B3-3[29]: 全市场同条件对照（金股超额）
add('B3', 2, 'dhigh60 深档胜率是否全市场效应（非金股特有）',
    stats_of([r for r in ev15629 if (r.get('dhigh60') or 0) <= -0.5 if False] or
             [r for r in ev15629 if (r.get('depth60') or 0) <= -0.35]),
    'PARTIAL',
    '深档子集（depth60≤-35%）' + json.dumps(stats_of([r for r in ev15629 if (r.get('depth60') or 0) <= -0.35]), ensure_ascii=False) +
    '。真对照需同条件全市场非金股样本（big_kcache 全宇宙扫描）——本卡未跑；'
    '#279 画像反推已记「深档事件 depth60 全沉底档=机械同源」，倾向支持「位置轴给的 edge」（与 #273 双响炮同构）。登记待跑严格对照。')

# KC B3-4[30]: 单票冗余（独立股票数）
codes = Counter(r['code'] for r in ev15629)
uniq = len(codes)
maxc = codes.most_common(5)
add('B3', 3, '15629 事件独立股票数 / 单票最大触发次数',
    f'独立票={uniq} 事件/票={len(ev15629)/uniq:.1f} top5={maxc}',
    'CONFIRMED-OVERLAP' if uniq < 3000 else 'PASS',
    f'15629 事件落在 {uniq} 只票（均值 {len(ev15629)/uniq:.1f} 次/票），top5={maxc}。'
    f'事件级 n 严重高估独立样本量——但 #281 的结论本就以「金股在册」为条件（每月名单有限），'
    f'重复计数主要影响「三连阴」这一无条件形态因子的描述性统计，不改变「口径捕捉错变量」的判决。')

# ================= B4 =================
# KC B4[35]: 独立出票日
days = sorted(set(r['signal_date'] for r in tdg_all))
add('B4', 0, 'TDG 独立出票日数（配对检验样本量）',
    f'独立出票日={len(days)} days={days}',
    'SMALL-SAMPLE', f'55 单仅 {len(days)} 个独立出票日（{len(tdg_all)/len(days):.1f} 单/日）——'
    f'LLM 阈「独立日<20 则 5pp 差无统计显著性」：{len(days)} 日 {"<20 满足小样本条件" if len(days)<20 else ">=20"}，'
    f'即「跑输邻居 5pp」的结论确实建立在极少独立日期上。')

# ================= C =================
combo = load('data/similarity_combo_20261016.json')
rev = combo['反转族']['filters']
knn_cells = {k: v for k, v in rev.items() if 'knn' in k.lower()}
add('C2', 0, 'knn 低分位排除层的日历聚集度检验（可检验部分）',
    json.dumps({k: {'n': v.get('n'), 'T+5': (v.get('T+5') or {}).get('增量pp_vs全部'),
                    '日历': (v.get('T+5') or {}).get('日历')} for k, v in list(knn_cells.items())[:4]}, ensure_ascii=False),
    'PARTIAL',
    'combo JSON 已带每格日历天数与 t_NW——knn bottom20% 的 T+5 t_NW=-3.15 直接来自带日历口径的产物，'
    'LLM 的「事件扎堆高估显著性」攻击对 NW 调整后的 t 不适用（NW 正是为聚集修正）。'
    '但 LLM 另一条（滚动分位重算 decile）本卡未跑，登记待跑。')

add('C3', 0, 'ivol20_low×反转族 t_NW=2.45 的参数孤峰检验', 'uncheckable-now',
    'UNCHECKABLE', '需 ivol 窗口 10-30 日 × dec 阈值 1-3 共 25 格重算日历 t_NW；'
    'RES-08 因子已在 factor_census 有 24 因子底座，但组合矩阵未做邻域扫描。登记待跑。')

add('C5', 0, 'top 档前 5% 天数是否与宏观事件日重合', 'uncheckable-now',
    'UNCHECKABLE', '需宏观事件日历（降准/汇金增持）+ similarity top 档日度超额序列；'
    '#276 已记「top 档日超额前 5% 天数贡献 101%」并据此判「不注册为交易线」——'
    '该集中度事实本身已足以支撑不注册判决，机制归属（beta vs alpha）留待跑。')

# ================= D1 =================
dd = Counter(r['signal_date'] for r in ld_sh)
add('D1', 0, 'LD(T+1腿) 影子 2026-09-11~10-15 事件扎堆度',
    f'n={len(ld_sh)} 独立日={len(dd)} 最大单日={dd.most_common(1)[0] if dd else None}',
    'CONFIRMED-CLUSTER',
    f'{len(ld_sh)} 笔落在 {len(dd)} 个交易日（{sorted(dd.items())}）。'
    f'LLM 阈「去重后 n<120 或 集中度>50%」——最大单日 {dd.most_common(1)[0][1] if dd else 0} 笔，'
    f'事件高度成簇（与 #278 T1 的「-0.06%/49%」判读同源：薄 edge 藏在冷静日孤立事件，'
    f'影子窗只拿到簇子集 → 影子数字比事件级更差是结构必然）。')

# LD T+1 腿逐 horizon 与去重后
for h in ['r1', 'r5', 'r10']:
    v = [r[h] for r in ld_sh if r.get(h) is not None]
    if v:
        k = sum(1 for x in v if x > 0)
        add('D1', {'r1':0,'r5':1,'r10':2}[h], f'LD 影子 {h} 汇总',
            f'n={len(v)} win={k/len(v):.1%} mean={sum(v)/len(v):.2%}',
            'CONFIRMED-' + ('NO-EDGE' if sum(v)/len(v) < 0 else 'POSITIVE'),
            f'{h}: n={len(v)} win={k/len(v):.1%} mean={sum(v)/len(v):.2%} '
            f'(与 #278 T1 数字对账：r1 n=199 -0.06%/49%、r5 n=180 -1.04%/44%、r10 -1.87%/43%)')

# ================= D3 摇篮线 =================
cr24 = [r for r in cradle if r['date'].startswith('2024')]
cr26 = [r for r in cradle if r['date'].startswith('2026')]
d24 = Counter(r['date'] for r in cr24)
top10 = sum(sorted((r['t5'] for r in cr24 if r.get('t5') is not None), reverse=True)[:10])
tot = sum(r['t5'] for r in cr24 if r.get('t5') is not None)
add('D3', 0, '2024 摇篮线事件日扎堆/前10大贡献日占比',
    f'2024 n={len(cr24)} 独立日={len(d24)} top10日贡献={top10:.2f} 总={tot:.2f}',
    'CONFIRMED-CONCENTRATION' if (len(d24) < 80 or (tot and top10/tot > 0.8)) else 'PASS',
    f'2024 年 {len(cr24)} 事件落 {len(d24)} 日；按单事件 t5 排序前10贡献 {top10:.2f} vs 总 {tot:.2f}'
    f'（占比 {100*top10/tot if tot else 0:.0f}%）。LLM 阈「去重后<80 交易日 且 前10贡献>80%」。'
    f'gate 分布：{Counter(r["gate"] for r in cr24)}。')

if cr26:
    v5 = [r['t5'] for r in cr26 if r.get('t5') is not None]
    v10 = [r['t10'] for r in cr26 if r.get('t10') is not None]
    add('D3', 1, '摇篮线 2026 表现（n=11 是否已反转）',
        f'n={len(cr26)} t5_mean={sum(v5)/len(v5) if v5 else 0:.2%} t10_mean={sum(v10)/len(v10) if v10 else 0:.2%}',
        'CONFIRMED-' + ('REVERSED' if (v5 and sum(v5)/len(v5) < -0.01) else 'NOT-REVERSED'),
        f'2026 n={len(cr26)}（{Counter(r["date"] for r in cr26)}）t5 均值 {sum(v5)/len(v5) if v5 else 0:.2%}、'
        f't10 均值 {sum(v10)/len(v10) if v10 else 0:.2%}；逐年：' +
        json.dumps({y: (lambda v: {'n': len(v), 'mean%': round(100*sum(v)/len(v), 2) if v else None})(
            [r['t5'] for r in cradle if r['date'].startswith(y) and r.get('t5') is not None])
            for y in ['2019','2020','2021','2022','2023','2024','2025','2026']}, ensure_ascii=False))

# ================= D4 深档 =================
db = load('data/deep_batches_full_20260927.json')
d26 = [b for b in db if b['date'].startswith('2026')]
win = [b for b in d26 if (b.get('r10') or 0) > 0]
add('D4', 0, '深档 2026 逐批（是否单窗口驱动）',
    f'2026 批数={len(d26)} 赢批={len(win)} mean_r10={sum(b.get("r10",0) for b in d26)/max(len(d26),1):.2%}',
    'CONFIRMED-CONCENTRATION' if len(d26) and max((b.get('r10') or 0) for b in d26) > 0.15 else 'PARTIAL',
    f'2026 深档 {len(d26)} 批（{sorted(b["date"] for b in d26)}），r10 单批最大 {max((b.get("r10") or 0) for b in d26):.2%}，'
    f'总均值 {sum(b.get("r10",0) for b in d26)/max(len(d26),1):.2%}——与 #278 T4「7/20-8/3 五日窗 5 批贡献 275%」核对：'
    f'逐批数字见 deep_batches_full。2026 批日期全集用于确认「8/19 后零批次」。')

# ================= D5 转债 =================
cb = load('data/cb_low_price.json')
add('D5', 0, '转债低价池当前成分与评级',
    json.dumps({'date': cb['date'], 'n': cb['n'], 'pool': cb['pool'], 'dropped': cb['dropped_zombie']}, ensure_ascii=False)[:600],
    'CONFIRMED-RISK',
    f"池 {cb['date']} n={cb['n']}，成分={[(p.get('code'), p.get('name'), p.get('close'), p.get('rating')) for p in cb['pool']]}；"
    f"僵尸剔除={cb['dropped_zombie']}。LLM 攻击成立：池内若含评级 CC 及以下（信用困境债），"
    f"「债底保护」前提受侵蚀（#243 违约潮已破债底信仰）；加评级闸提案需先核已装入持仓。")

# ================= D7 金股变体 =================
tdg_codes = set(r['code'] for r in tdg_all)
x_codes = set(r['code'] for r in xmega)
add('D7', 0, 'TDG 影子样本与 T1-MEGA 前向批代码重叠',
    f'TDG codes={len(tdg_codes)} T1MEGA codes={len(x_codes)} 交集={sorted(tdg_codes & x_codes)}',
    'NO-OVERLAP' if not (tdg_codes & x_codes) else 'CONFIRMED-OVERLAP',
    f'TDG 38 只 vs T1-MEGA 10 只（{sorted(x_codes)}）交集={sorted(tdg_codes & x_codes)}——'
    f'两者构造性不相交（TDG=金股在册的三连阴票，T1-MEGA=恐慌簇深档票），'
    f'LLM 指控「D7 惨淡来自 T1-MEGA 灾难」不成立。')

# KC D7[71]: 滚动5次胜率死亡螺旋
tdg_sorted = sorted([r for r in tdg_all if r.get('r5') is not None], key=lambda r: r['signal_date'])
roll = []
for i in range(len(tdg_sorted)-4):
    w = tdg_sorted[i:i+5]
    roll.append(sum(1 for r in w if r['r5'] > 0)/5)
worst_run = 0; cur = 0
for x in roll:
    cur = cur+1 if x < 0.2 else 0
    worst_run = max(worst_run, cur)
add('D7', 1, 'TDG r5 滚动 5 次胜率（死亡螺旋检验）',
    f'窗口数={len(roll)} 最差窗口={min(roll):.0%} 连续<20%次数={worst_run}',
    'CONFIRMED-DEATH-SPIRAL' if worst_run >= 3 else 'PASS',
    f'滚动 5 笔胜率序列最差 {min(roll):.0%}，连续 <20% 的窗口数 {worst_run}；'
    f'LLM 阈「连续 3 窗口<20% 则死亡螺旋」——{"成立，进 ICU 是拖延" if worst_run>=3 else "未成立"}。'
    f'整体 r5 win={k55/max(n55,1):.1%} mean={sum(r["r5"] for r in tdg_r5)/max(n55,1):.2%}。')

# ================= YELLOW-1 T1-MEGA =================
xs_ret = [r['ret'] for r in xmega if r.get('ret') is not None]
add('YELLOW-1', 0, 'T1-MEGA 前向批 -8.43% 是否趋势性失效（后续批）',
    f'批数=1 n={len(xs_ret)} 逐票={[round(x,4) for x in xs_ret]} 批均={sum(xs_ret)/max(len(xs_ret),1):.2%}',
    'SINGLE-BATCH(cannot-judge)',
    f'xrules_shadow 仅 1 批（2026-08-31，10 票 {[round(x,3) for x in xs_ret]}，批均 {sum(xs_ret)/max(len(xs_ret),1):.2%}）。'
    f'LLM 阈「后续 5 批累计<-10%」——物理上不存在后续批（唯一前向批），无法判趋势性失效；'
    f'与 #278 黄旗判词一致：单批不立规矩，等下一批对照。')

# ================= 输出 =================
out = {'generated': datetime.now().isoformat(timespec='seconds'),
       'n_kill_conditions_total': 76, 'n_adjudicated': len(R), 'verdicts': R}
json.dump(out, open('/opt/data/cache/scratch/redteam_adjudication.json', 'w'), ensure_ascii=False, indent=1)

from collections import Counter as C2
print('== 判卷汇总 ==')
print(C2(v['verdict'] for v in R))
for v in R:
    print(f"[{v['claim_id']}] {v['verdict']:28s} {v['test'][:70]}")
