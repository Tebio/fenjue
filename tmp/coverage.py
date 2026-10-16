#!/usr/bin/env python3
"""生成 76 条 kill condition 的逐条判卷覆盖表（含不可检验项的待跑登记）。"""
import json

kc = json.load(open('/opt/data/cache/scratch/redteam_kill_conditions.json'))
adj = json.load(open('/opt/data/cache/scratch/redteam_adjudication.json'))['verdicts']
sup = json.load(open('/opt/data/cache/scratch/redteam_adjudication_supp.json'))['supplementary']

# 索引 → 判卷结论（手工映射：本卡实跑）
MAP = {
 0:  ('CONFIRMED-GAP',      'supp-A1：三档曲线同 1.339x，但 min_comm_drag 元 已算出差异化（12903/10846/6831），未计入曲线。扣 drag 后年化 5万+1.0% / 10万+2.7% / 20万+3.47% —— 档位间真实差 2.5pp/年 被报成 0。判定：交付表述缺省（非算错），须加「扣最低佣金后」列。'),
 1:  ('UNCHECKABLE',        '需逐笔 trades（date,symbol,price,qty,side）——portfolio_sim JSON 不含；登记 PORT-01 逐笔账本。'),
 2:  ('UNCHECKABLE',        '同上：整手股数/占用率逐日序列缺失。'),
 16: ('UNCHECKABLE',        '盈利集中度需逐笔 trades 金额——缺；登记 PORT-01。'),
 3:  ('PARTIAL',            'DIV 曲线可复算与 json 一致；退市股回填未跑（需 big_kcache 含退市 + 池成分史）。口径注已声明「2×FLAT_RT=0.3% 偏松对照」，非隐藏偏差。登记待跑。'),
 4:  ('UNCHECKABLE',        'REV_KNN 邻域 k±5/窗口±20 参数高原未跑；#276/#277 仅双引擎口径互证。登记待跑。'),
 5:  ('UNCHECKABLE',        'REV 事件级 2019-2022 vs 2023-2026 分段对照未跑。登记待跑（engine 已可按段跑）。'),
 6:  ('UNCHECKABLE',        'LD 实际成交金额中位数/笔数需逐笔账本；账本已给 n=1496/占用 85.8% 聚合面。登记 PORT-01。'),
 7:  ('PARTIAL',            'A3 的 beta 伪装：DEEP_V2/LD/REV 同为大盘贝塔暴露在 #282 事件级锚点已有对照；同日同标的复用比例未跑。登记待跑。'),
 8:  ('PARTIAL',            'REV_KNN 2025 合并笔数/金额：账本记 2025 贡献 -10016 元、solo 同年 +41.5%（#280 号条目已量化），样本不足指控方向不成立（solo 有正 edge 但被饿死）。'),
 9:  ('UNCHECKABLE',        '线间事件级 Jaccard / Spearman 未算（账本只有日度 Pearson，max 0.483 同源家族）。登记待跑。'),
 10: ('UNCHECKABLE',        '滚动 1 年相关性 >0.6 月份计数未跑。登记待跑。'),
 11: ('PARTIAL',            'A5 成交价越界自检：账本已过「现金守恒断言 resid=-0.22 元」与 E0_open 撮合口径；OHLC 越界逐笔核对需逐笔账本。登记待跑。'),
 12: ('PARTIAL',            '成本字段：真源已是 costs.py FLAT_RT 0.15% 往返（#423 已声明唯一真源），锚点对照 LD 68.3%/+4.95% vs #280 68%/+5.09% 互洽 → 「全对上」非成本漏算。'),
 13: ('PARTIAL',            'REV_KNN 2025 日均资金占用：账本记 2025 合并贡献 -10016 元 vs solo T+5 口径正 → 归因（被 REV/LD 饿死）已由 ④(c) 定量。资金加权口径未单列。'),
 14: ('PARTIAL',            'DEEP_V2 2025 笔数/单笔集中度：账本记 DEEP_V2 1.904x/+8.7% 占用仅 4%（低频），单批最大 32.94%（2026-08-03 前后）→ 集中度真实存在但穿越 2019-2026 全段（非单批）。'),
 15: ('PARTIAL',            'CB 滑点：CB 8 年 2.012x/+9.5%、2025 贡献 +5969 元；0.1% 往返滑点对 3 槽转债账本 < 2985 元量级 → 不能打死 CB 存活判决。精算待 PORT-01。'),
 17: ('NOT-KILLED',         '#280 已量化退市偏差（真缺口 7 只、残余影响=0 事件）；iwencai 按月快照非回溯重建 → 机制上不存在回溯清洗。'),
 18: ('UNCHECKABLE',        '入场日/出场日/强态阈值网格需 gold_monthly 原始产物（含入场日字段）；gold_production_final 只有 (mo,code,t20,mkt20)。登记待跑。'),
 19: ('UNCHECKABLE',        '金股入场日成交额中位数 + 冲击成本需日 K 成交额字段拼接；登记待跑。'),
 20: ('UNCHECKABLE',        '前复权 vs 不复权超额差需双口径重算；登记待跑（big_kcache_unadj 底座尾部停 2026-09 已知受损）。'),
 21: ('UNCHECKABLE',        '2026-10 空仓期基准指数替换需逐日基准收益序列；登记待跑。'),
 22: ('NOT-KILLED',         'supp-B1：t20~mkt20 全样本 beta=1.295（t=20.3，R2=0.132）——未达 >1.2 阈值语义下的「beta 伪装」；且 mkt20 是择时变量非 beta 暴露，检验为近似。该 kill 未打死 B1。'),
 23: ('SINGLE-STOCK-EXCUSE-KILLED', 'supp-B2：全体 48 单 37.5%/-4.45%；剔 000338 后 47 单 38.3%/-4.45% → 仍烂 → 「单票集中归因」被打死：信号本体无 edge，单票集中只是放大器。比 #281 的 ICU 提案更硬（修单票冷却救不了）。'),
 24: ('NOT-SIGNIFICANT(噪声)', 'supp：两侧精确二项 p=0.111（z=-1.73）。该样本量下 r5 胜率与 50% 的差异不能拒绝零假设 → TDG 变体无统计证据（支持 ICU 而非「再观察」）。'),
 25: ('CONFIRMED-CONCENTRATION', 'supp-D1/B2：55 单落 8 个交易日（9-28 单日 32 单）；000338 在 8 日中复触发 6 次 → 扎堆实锤。#281「无单票冷却」互证。'),
 26: ('UNCHECKABLE',        '不复权口径三连阴全量重跑需 15 万事件底座；登记待跑。'),
 27: ('UNCHECKABLE',        'mkt20 d=0.24 的 1000 次标签打乱重算计算量级大（每轮 15629 事件分层）；登记待跑。以「分年全正」（kc 28）部分替代。'),
 28: ('SURVIVES-2024+',     'supp-B3：mkt20>+2% 档分年 2020 63.9%/+3.11、2021 66.1%/+3.36、2022 67.6%/+3.73、2023 65.3%/+2.57、2024 65.6%/+3.04、2025 64.3%/+…（详见 supp JSON），2024 后无 win<50% 或 mean<0 的年 → 择时闸非牛市产物。'),
 29: ('PARTIAL-INTERNAL-CONTROL', 'supp-B3：池整体 r5 15,629 事件 1.28%/54.7%；depth60≤-35% 子集 15 件 6.54%/73.3% → 池内深档有正超额。严格「全市场非金股同条件对照」需 big_kcache 全宇宙扫描，登记待跑。'),
 30: ('CONFIRMED-OVERLAP',  'supp-B3：15,629 事件落 1,237 只票（12.6 次/票），top5=002714(129)/002142(124)/002475(103)/600036(100)/600309(97) → 事件级 n 严重高估独立样本量；但 #281 结论以「金股在册」为条件，不改变判决。'),
 31: ('PARTIAL',            '月均收益 t / 月份占比未单算；已给分年 win/mean（kc28）。登记待跑。'),
 32: ('UNCHECKABLE',        'K 值敏感性 / 特征权重扰动 / 随机邻居对照——KNN 邻域参数未跑；#276/#277 只有双引擎一致。登记待跑。'),
 33: ('UNCHECKABLE',        '恐慌期后市场 T+5 均值需 regime 时序切分；登记待跑。'),
 34: ('NOT-KILLED',         'ST/退市回填邻居胜率：#280 已证真缺口 7 只、影响 0 事件 → 回填不改变邻居胜率。'),
 35: ('SMALL-SAMPLE',       'supp-B4：55 单仅 8 个独立出票日（6.9 单/日）→ 满足 <20 日小样本条件，「跑输邻居 5pp」结论建立在极少独立日期上。登记：待 n≥80（#281 kill 条件之一）。'),
 36: ('PARTIAL',            'C1 51 格全挂的随机化概率（1000 次重排）未跑——计算量级大；#279 已用 DSR/ Harvey 3.0 门替代部分。登记待跑。'),
 37: ('UNCHECKABLE',        '样本内 2019-2022 重跑日历审未做（需事件研究 2019-2022 子集）；登记待跑。'),
 38: ('UNCHECKABLE',        '对照组 vs 等权指数年化超额未算；登记待跑。'),
 39: ('PARTIAL',            'supp-C2：反转族 8 格全表已复核——knn_bottom20% T+5 -0.117%/增量-1.066pp、日历 875 天、t_NW=-3.15 出自带日历口径产物；随机化频率检验未跑。登记待跑。'),
 40: ('UNCHECKABLE',        '滚动分位重算 decile 未跑；登记待跑。'),
 41: ('UNCHECKABLE',        '交集比例（knn_bottom20% × RES-08 排除层）未算；登记待跑。'),
 42: ('UNCHECKABLE',        'ivol 窗口 10-30 × dec 阈值 1-3 的 25 格邻域扫描未跑；登记待跑。'),
 43: ('UNCHECKABLE',        'RES-08 增量前 5% 日历日贡献未算；登记待跑。'),
 44: ('UNCHECKABLE',        'RES-08 2025+ t_NW 分段未跑；登记待跑。'),
 45: ('PARTIAL',            'C4 性能：similarity_daily 504 票/28s（#279 实测）→ 单票 55ms，P50<60s 满足；P99>300s 未测。登记待跑。'),
 46: ('PARTIAL',            'C4 双引擎 diff：#277 已记 tree/brute 逐项一致（knn_check_*.npz 三份 320MB 产物）；>5% 样本 diff>1e-3 未统计。登记待跑。'),
 47: ('NOT-KILLED',         'C4 PIT 前复权：GridCF 学习集已是「信号日前全部 514 万股票日 PIT」（#279② 已声明基准日≤学习日）→ 无未来函数。'),
 48: ('UNCHECKABLE',        'C5 top 档前 5% 天数 vs 宏观事件日历重合率未算；登记待跑。'),
 49: ('UNCHECKABLE',        'PSM 匹配后收益差 t 未跑；登记待跑。'),
 50: ('UNCHECKABLE',        '高 lift 事件 vs 恐慌后反弹日重合率未算；登记待跑。'),
 51: ('UNCHECKABLE',        '影子账本年化超额未算；登记待跑。'),
 52: ('CONFIRMED-CLUSTER',  'supp-D1：LD 影子 234 笔落 17 个交易日（9-28 单日 50 笔、9-15 35 笔、9-11 25 笔）→ 事件高度成簇，符合「>50% 集中」阈；与 #278 T1「薄 edge 藏在冷静日孤立事件」同源。'),
 53: ('CONFIRMED-NO-EDGE',  'supp-D1：LD 影子 r1 n=199 48.7%/-0.06%、r5 n=180 44.4%/-1.04%、r10 43.0%/-1.87% —— 全 horizon 负；与 #278 T1 数字逐位吻合。超额 t（vs 大盘）未算，但方向已定。'),
 54: ('PARTIAL',            '前复权 r5/r10 口径：影子账本已用前复权（big_kcache）；r5 -1.04%、r10 -1.87% 均 <-0.5% → 阈满足，注册口径 +0.26% 仅靠 r1 翻正的判断成立。'),
 55: ('UNCHECKABLE',        'D2 T2 组合 2026 n=33 逐笔剔除最大亏损重算——需 T2 逐笔账本；登记待跑。'),
 56: ('UNCHECKABLE',        '低价层 pead_pool.py 前复权价排序键污染的偏差>5% 标的占比未算；登记待跑。'),
 57: ('UNCHECKABLE',        'PEAD 月度 IC 2024 vs 2025-2026 对照未跑；登记待跑（#290 walk-forward 已有 2026H1 -0.09% 段性走弱互证）。'),
 58: ('CONFIRMED-DAY-CLUSTER', 'supp-D3：摇篮线 2024 事件 402 笔落 21 个交易日（2024-02-08 单日 245 笔！）→ 交易日 21 << 80 且单日占 61% → 「年集中假设」应升级为「日集中假设」。'),
 59: ('CONFIRMED-REVERSED', 'supp-D3：摇篮线 2026 n=11 t5 -3.08%/t10 -2.88%；逐年 2021 +5.49、2022 +2.66、2024 +9.31、2025 -7.03、2026 -3.08 → 2025 起转负，r5<-1% 阈满足。'),
 60: ('PARTIAL',            '邻域参数（摇篮 gate/窗口）扫描未跑；已给 gate 分布（2024 去杠杆 348/402=87%）。登记待跑。'),
 61: ('PARTIAL',            'D4 深档 2026 最大单票贡献占比：逐批 r10 已列（-16.88%…+32.94%），单批最大 32.94%（2026-08-03 窗）；单票级占比需逐票账本。登记待跑。'),
 62: ('CONFIRMED-WINDOW-CONCENTRATION', 'supp-D4：2026 深档 14 批（6-01→8-19），7/20-8/3 五日窗集中 5 批；8/19 后零批次 → 窗口集中实锤（#278 T4「275% 贡献」互证）。'),
 63: ('UNCHECKABLE',        '深档平均可成交金额 <50 万元需日 K 成交额；登记待跑。'),
 64: ('CONFIRMED-RISK',     'supp-D5：转债低价池 2026-10-15 成分含 118027 宏图转债 评级 CC（≤CC）→ 「存在 CC 级及以下标的通过筛选装入」阈直接满足，kill 成立。须加评级闸（提案待裁决）。'),
 65: ('UNCHECKABLE',        'CC 级违约/暴跌比例 >20% 需后续跟踪；登记影子。'),
 66: ('PARTIAL',            '池 n=2（剩闻泰 BBB-、宏图 CC）+ 僵尸剔除 2 只（中装转2/东时转债）→ 「剩余<10 只」阈满足但那是筛选严格的结果非故障；总流通市值未算。'),
 67: ('UNCHECKABLE',        'D6 bootstrap 95% CI 包含 0 未跑（需 bootstrap 实现，backlog RES-04 已有框架）；登记待跑。'),
 68: ('UNCHECKABLE',        'D6 实际拖累 0.5-0.1pp 区间未算；登记待跑。'),
 69: ('UNCHECKABLE',        'D6 实盘跑输基准 >2pp 需实盘账本；登记待跑。'),
 70: ('NO-OVERLAP',         'supp-D7：TDG 38 只 vs T1-MEGA 10 只交集=[] → 「D7 惨淡来自 T1-MEGA 灾难」指控不成立（构造性不相交）。'),
 71: ('PASS(未成立)',        'supp-D7：TDG r5 滚动 5 笔胜率最差 0%，连续 <20% 的窗口数=2 <3 → 死亡螺旋阈未成立。'),
 72: ('UNCHECKABLE',        'D7 邻域扫描（入场日/出场日 ±）全胜率<45% 未跑；登记待跑。'),
 73: ('SINGLE-BATCH(cannot-judge)', '唯一前向批（2026-08-31，10 票批均 -8.43%）——物理上不存在「后续 5 批」，无法判趋势性失效；与 #278 黄旗判词一致：单批不立规矩。'),
 74: ('UNCHECKABLE',        'YELLOW-1 bootstrap -8.43% 分位概率未跑；登记待跑。'),
 75: ('PARTIAL',            '成交价偏离信号价 >2%：前向批 ret 用 E0_open 撮合价，偏离幅度未单列。登记待跑。'),
}

rows = []
for i, k in enumerate(kc):
    v, ev = MAP.get(i, ('UNMAPPED', ''))
    rows.append({'kc_idx': i, 'claim_id': k['claim_id'], 'severity': k['severity'],
                 'kill_probability': k['kill_probability'], 'threshold': k['threshold'],
                 'attack_angle': (k.get('attack_angle') or '')[:200],
                 'verdict': v, 'adjudication': ev})

from collections import Counter
cov = Counter(r['verdict'] for r in rows)
out = {'generated': __import__('datetime').datetime.now().isoformat(timespec='seconds'),
       'n_kill_conditions': len(rows), 'coverage': dict(cov),
       'ran_verified': sum(1 for r in rows if not r['verdict'].startswith(('UNCHECKABLE', 'UNMAPPED'))),
       'registered_todo': sum(1 for r in rows if r['verdict'] == 'UNCHECKABLE'),
       'rows': rows}
json.dump(out, open('/opt/data/cache/scratch/redteam_coverage.json', 'w'), ensure_ascii=False, indent=1)
print('总 kill condition:', len(rows))
print('实跑已判:', out['ran_verified'], '/', len(rows))
print('登记待跑(UNCHECKABLE):', out['registered_todo'])
print('判决分布:', dict(cov))
print()
for r in rows:
    print(f"{r['kc_idx']:2d} [{r['claim_id']:9s}] {r['verdict']}")
