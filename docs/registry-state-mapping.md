# REGISTRY 状态映射表（初始状态逐条依据 · 2026-10-16 卡 t_897ee796）

> 本表是 `engine/registry_state.py --init` 生成初始状态的**唯一依据**，供用户过目后再进代码运行。
> 状态枚举 = `INTERFACES.md` I6 冻结值 `IDEA/RESEARCH/CANDIDATE/SHADOW/LIVE/ICU/DEAD`；
> 卡的「L1/L2/候选/ICU/DEAD/REJECT」落在两个正交字段上：`layer`（L1 机制 / L2 注册 / EXP 实验变体）与 `state`，另加 `verdict`（submit PASS/**REJECT**，与 state 正交，REJECT 映射 state=RESEARCH 见 §规则）。

## 映射规则（写死，逐条可复核）

| 台账事实 | → state | → layer |
|---|---|---|
| claims_state.json = DEAD（周审计机器） | DEAD | L2 |
| claims_state.json = DECAYING | ICU | L2 |
| 在 AGENTS 生产线清单（有 cron 消费） | LIVE | L2 |
| claims_shadow 注册表桥（只记账） | SHADOW | L2 |
| claims_state = CANDIDATE，未上生产 | CANDIDATE | L2 |
| 无 claims 条目 + submit PASS | CANDIDATE | EXP |
| 无 claims 条目 + submit REJECT | RESEARCH（`reject_reason` 记挂哪闸） | EXP |
| 无 claims 条目 + 无 submit 判决 | IDEA | EXP |

**容量凭证纪律（#270）**：`g7_trusted` 仅在 `g7_槽10` 带 `K1_年化%` 数值时为 true；16 条 `CROSS_LOW_*` 只有布尔位 `{"过G7": true}`，已实测被不同批次脚本污染，**不作凭证**。

**统计**：state `{'DEAD': 32, 'RESEARCH': 27, 'CANDIDATE': 14, 'IDEA': 36, 'LIVE': 2, 'SHADOW': 6, 'ICU': 1}`；layer `{'L2': 52, 'EXP': 66}`；家族 `{'均线族': 5, '形态族': 9, '其他': 5, '妖股族': 13, '跌停族': 45, '反转族': 10, '池与名单族': 3, '预增族': 10, '突破族': 3, '缺口族': 13, '触板族': 2}`

## 家族 FDR（#263⑧ 落地）

| 家族 | 线数 | 已 submit 试探 m | 幸存 | REJECT | 期望假阳 0.05m | 判据 |
|---|---|---|---|---|---|---|
| 跌停族 | 45 | 15 | 2 | 13 | 0.75 | survivors_exceed_fp |
| 妖股族 | 13 | 6 | 1 | 5 | 0.3 | survivors_exceed_fp |
| 形态族 | 9 | 2 | 0 | 2 | 0.1 | insufficient_or_at_noise |
| 反转族 | 10 | 2 | 0 | 2 | 0.1 | insufficient_or_at_noise |
| 池与名单族 | 3 | 2 | 0 | 2 | 0.1 | insufficient_or_at_noise |
| 均线族 | 5 | 1 | 0 | 1 | 0.05 | insufficient_or_at_noise |
| 预增族 | 10 | 1 | 0 | 1 | 0.05 | insufficient_or_at_noise |
| 缺口族 | 13 | 1 | 0 | 1 | 0.05 | insufficient_or_at_noise |
| 其他 | 5 | 0 | 0 | 0 | 0.0 | insufficient_or_at_noise |
| 突破族 | 3 | 0 | 0 | 0 | 0.0 | insufficient_or_at_noise |
| 触板族 | 2 | 0 | 0 | 0 | 0.0 | insufficient_or_at_noise |

> 读法：家族内「幸存数 > 期望假阳」只是粗筛（本体系多数格无 p 值，只有 t_NW）；DSR 重算的分母建议见 `families.*.dsr_trials_suggested`。

## 逐条映射（118 条）

| # | REGISTRY 线 | layer | state | family | verdict | g7可信 | 依据 source |
|---|---|---|---|---|---|---|---|
| 1 | MA20上穿 | EXP | IDEA | 均线族 | — | — | 无 claims 条目、无 submit 判决、无 candle 产物 → 未测/未提交（IDEA） |
| 2 | N字回踩企稳 | EXP | RESEARCH | 形态族 | REJECT | — | submit 20260919 REJECT（挂：G1_tNW≥3、G2_时间分段、G3_regime≥3/4、G4_市值≥4/5、G6_0.30%成本仍正、G7_槽位10资金曲线>0） |
| 3 | PEAD_强利好 | EXP | IDEA | 预增族 | — | — | 无 claims 条目、无 submit，但已在 candle 全量跑过（law_pipeline_candle_20260913.json）→ IDEA（已测未提交） |
| 4 | PEAD_强利空 | EXP | RESEARCH | 预增族 | REJECT | — | submit 20260919 REJECT（挂：G2_时间分段、G3_regime≥3/4、G4_市值≥4/5、G5_位置匹配边际>0、G6_0.30%成本仍正、G7_槽位10资金曲线>0） |
| 5 | PEAD_扭亏 | EXP | IDEA | 预增族 | — | — | 无 claims 条目、无 submit 判决、无 candle 产物 → 未测/未提交（IDEA） |
| 6 | PEAD_预增 | EXP | IDEA | 预增族 | — | — | 无 claims 条目、无 submit 判决、无 candle 产物 → 未测/未提交（IDEA） |
| 7 | PEAD_预增50 | EXP | IDEA | 预增族 | — | — | 无 claims 条目、无 submit 判决、无 candle 产物 → 未测/未提交（IDEA） |
| 8 | PEAD_预增50+ | EXP | IDEA | 预增族 | — | — | 无 claims 条目、无 submit，但已在 candle 全量跑过（law_pipeline_candle_20260913.json）→ IDEA（已测未提交） |
| 9 | PEAD_预增50_低位 | EXP | IDEA | 预增族 | — | — | 无 claims 条目、无 submit 判决、无 candle 产物 → 未测/未提交（IDEA） |
| 10 | PEAD_预增50_高位 | EXP | IDEA | 预增族 | — | — | 无 claims 条目、无 submit 判决、无 candle 产物 → 未测/未提交（IDEA） |
| 11 | PEAD_首亏 | EXP | IDEA | 预增族 | — | — | 无 claims 条目、无 submit 判决、无 candle 产物 → 未测/未提交（IDEA） |
| 12 | TD9买入 | L2 | DEAD | 均线族 | — | 是 | claims_state.json=DEAD（周审计机器）+ AGENTS 台账 |
| 13 | TD9卖出 | EXP | RESEARCH | 均线族 | REJECT | — | submit 20260913 REJECT（挂：G2_时间分段、G3_regime≥3/4、G4_市值≥4/5、G5_位置匹配边际>0、G6_0.30%成本仍正） |
| 14 | banlu_b5 | EXP | CANDIDATE | 妖股族 | PASS | — | submit 20260918 PASS（过闸门，未注册条目） |
| 15 | banlu_b5_MA60上 | L2 | LIVE | 妖股族 | — | 是 | AGENTS 生产线清单（#238/#279）：B5 半路板生产线：cron stock_banlu_daily.py → engine/banlu_daily.py 调本探测器 |
| 16 | banlu_b5_MA60上_避周二 | EXP | RESEARCH | 妖股族 | REJECT | — | submit 20260919 REJECT（挂：G1_tNW≥3、G2_时间分段、G4_市值≥4/5、G7_槽位10资金曲线>0） |
| 17 | banlu_b5_MA60下 | EXP | RESEARCH | 妖股族 | REJECT | — | submit 20260918 REJECT（挂：G1_tNW≥3、G4_市值≥4/5） |
| 18 | frontrun_v2 | L2 | CANDIDATE | 妖股族 | — | 是 | claims_state.json=CANDIDATE（过闸门、未上生产） |
| 19 | frontrun_v2_低位追 | L2 | DEAD | 妖股族 | — | 是 | claims_state.json=DEAD（周审计机器）+ AGENTS 台账 |
| 20 | watchpool_grad | L2 | CANDIDATE | 池与名单族 | — | 是 | claims_state.json=CANDIDATE（过闸门、未上生产） |
| 21 | 三连阴 | EXP | IDEA | 形态族 | — | — | 无 claims 条目、无 submit 判决、无 candle 产物 → 未测/未提交（IDEA） |
| 22 | 三连阴_金股覆盖_v1 | L2 | DEAD | 形态族 | — | 否 | claims_state.json=DEAD（周审计机器）+ AGENTS 台账 |
| 23 | 上升趋势跌停ULD | EXP | IDEA | 跌停族 | — | — | 无 claims 条目、无 submit 判决、无 candle 产物 → 未测/未提交（IDEA） |
| 24 | 主线深回踩_RSI2_v1 | EXP | IDEA | 其他 | — | — | 无 claims 条目、无 submit 判决、无 candle 产物 → 未测/未提交（IDEA） |
| 25 | 二连板 | EXP | IDEA | 妖股族 | — | — | 无 claims 条目、无 submit 判决、无 candle 产物 → 未测/未提交（IDEA） |
| 26 | 交叉_缺口低开低_TD9买入_剔亏ST | L2 | DEAD | 缺口族 | — | 否 | claims_state.json=DEAD（周审计机器）+ AGENTS 台账 |
| 27 | 交叉_缺口低开低_三连阴_TD9买入 | L2 | SHADOW | 缺口族 | — | 否 | claims_shadow 桥（claims_shadow 影子盘在记账（只影子不推送）） |
| 28 | 交叉_缺口低开低_三连阴_剔亏ST | L2 | ICU | 缺口族 | — | 否 | claims_state.json=DECAYING（降级中）→ 映射 ICU |
| 29 | 交叉_缺口低开低_三连阴_避雷针低 | L2 | DEAD | 缺口族 | — | 否 | claims_state.json=DEAD（周审计机器）+ AGENTS 台账 |
| 30 | 交叉_缺口低开低_输家250_剔亏ST | L2 | DEAD | 缺口族 | — | 否 | claims_state.json=DEAD（周审计机器）+ AGENTS 台账 |
| 31 | 交叉_缺口低开低_避雷针低_TD9买入 | L2 | DEAD | 缺口族 | — | 否 | claims_state.json=DEAD（周审计机器）+ AGENTS 台账 |
| 32 | 交叉_缺口低开低_避雷针低_剔亏ST | L2 | DEAD | 缺口族 | — | 否 | claims_state.json=DEAD（周审计机器）+ AGENTS 台账 |
| 33 | 交叉_跌停低_TD9买入_缺口低开 | L2 | DEAD | 跌停族 | — | 否 | claims_state.json=DEAD（周审计机器）+ AGENTS 台账 |
| 34 | 交叉_跌停低_三连阴_超跌20 | L2 | SHADOW | 跌停族 | — | 否 | claims_shadow 桥（claims_shadow 影子盘在记账（只影子不推送）） |
| 35 | 交叉_跌停低_三连阴_输家250 | L2 | SHADOW | 跌停族 | — | 否 | claims_shadow 桥（claims_shadow 影子盘在记账（只影子不推送）） |
| 36 | 交叉_跌停低_缩量_剔亏ST | L2 | DEAD | 跌停族 | — | 否 | claims_state.json=DEAD（周审计机器）+ AGENTS 台账 |
| 37 | 交叉_跌停低_缩量_缺口低开 | L2 | DEAD | 跌停族 | — | 否 | claims_state.json=DEAD（周审计机器）+ AGENTS 台账 |
| 38 | 交叉_跌停低_缩量_避雷针低 | L2 | DEAD | 跌停族 | — | 否 | claims_state.json=DEAD（周审计机器）+ AGENTS 台账 |
| 39 | 交叉_跌停低_输家250_避雷针低 | L2 | DEAD | 跌停族 | — | 否 | claims_state.json=DEAD（周审计机器）+ AGENTS 台账 |
| 40 | 反复票_回撤企稳 | EXP | RESEARCH | 池与名单族 | REJECT | — | submit 20260921 REJECT（挂：G1_tNW≥3、G2_时间分段、G3_regime≥3/4、G4_市值≥4/5、G5_位置匹配边际>0、G6_0.30%成本仍正、G7_槽位10资金曲线>0） |
| 41 | 反复票_回调日 | EXP | RESEARCH | 池与名单族 | REJECT | — | submit 20260921 REJECT（挂：G1_tNW≥3、G2_时间分段、G3_regime≥3/4、G4_市值≥4/5、G5_位置匹配边际>0、G6_0.30%成本仍正、G7_槽位10资金曲线>0） |
| 42 | 反转族_MA60上 | EXP | IDEA | 反转族 | — | — | 无 claims 条目、无 submit，但已在 candle 全量跑过（law_pipeline_candle_20260913.json）→ IDEA（已测未提交） |
| 43 | 反转族_MA60下 | EXP | IDEA | 反转族 | — | — | 无 claims 条目、无 submit，但已在 candle 全量跑过（law_pipeline_candle_20260913.json）→ IDEA（已测未提交） |
| 44 | 反转族_MA60下_gap>+1 | EXP | IDEA | 反转族 | — | — | 无 claims 条目、无 submit 判决、无 candle 产物 → 未测/未提交（IDEA） |
| 45 | 反转族_MA60下_gap≤-3 | EXP | IDEA | 反转族 | — | — | 无 claims 条目、无 submit 判决、无 candle 产物 → 未测/未提交（IDEA） |
| 46 | 反转族_T-1大跌 | L2 | DEAD | 反转族 | — | 是 | claims_state.json=DEAD（周审计机器）+ AGENTS 台账 |
| 47 | 反转族_跌停潮50 | L2 | CANDIDATE | 反转族 | — | 是 | claims_state.json=CANDIDATE（过闸门、未上生产） |
| 48 | 大长腿_低位 | L2 | DEAD | 形态族 | — | 是 | claims_state.json=DEAD（周审计机器）+ AGENTS 台账 |
| 49 | 大长腿_高位 | EXP | RESEARCH | 形态族 | REJECT | — | submit 20260913 REJECT（挂：G2_时间分段、G3_regime≥3/4、G4_市值≥4/5、G5_位置匹配边际>0、G6_0.30%成本仍正） |
| 50 | 妖股启动期首板_v1 | EXP | IDEA | 妖股族 | — | — | 无 claims 条目、无 submit 判决、无 candle 产物 → 未测/未提交（IDEA） |
| 51 | 妖股摇篮_成簇 | L2 | CANDIDATE | 妖股族 | — | 是 | claims_state.json=CANDIDATE（过闸门、未上生产） |
| 52 | 妖股摇篮_缩量深跌小市值 | EXP | RESEARCH | 妖股族 | REJECT | — | submit 20260919 REJECT（挂：G7_槽位10资金曲线>0） |
| 53 | 强势回调_MA60上 | EXP | IDEA | 其他 | — | — | 无 claims 条目、无 submit 判决、无 candle 产物 → 未测/未提交（IDEA） |
| 54 | 恐慌深度_≤-9.5 | L2 | CANDIDATE | 反转族 | — | 是 | claims_state.json=CANDIDATE（过闸门、未上生产） |
| 55 | 放量涨停_对照 | EXP | RESEARCH | 妖股族 | REJECT | — | submit 20260914 REJECT（挂：G2_时间分段、G3_regime≥3/4、G4_市值≥4/5、G5_位置匹配边际>0、G6_0.30%成本仍正） |
| 56 | 海龟20突破 | EXP | IDEA | 突破族 | — | — | 无 claims 条目、无 submit 判决、无 candle 产物 → 未测/未提交（IDEA） |
| 57 | 海龟55突破 | EXP | IDEA | 突破族 | — | — | 无 claims 条目、无 submit 判决、无 candle 产物 → 未测/未提交（IDEA） |
| 58 | 涨停收盘打板 | EXP | IDEA | 其他 | — | — | 无 claims 条目、无 submit 判决、无 candle 产物 → 未测/未提交（IDEA） |
| 59 | 涨停洗盘Shakeout | EXP | IDEA | 妖股族 | — | — | 无 claims 条目、无 submit 判决、无 candle 产物 → 未测/未提交（IDEA） |
| 60 | 深档低位_缺口≤-2 | EXP | IDEA | 缺口族 | — | — | 无 claims 条目、无 submit 判决、无 candle 产物 → 未测/未提交（IDEA） |
| 61 | 组合_反转x大长腿低位 | EXP | RESEARCH | 反转族 | REJECT | — | submit 20260918 REJECT（挂：G3_regime≥3/4） |
| 62 | 组合_反转x避雷针低位 | L2 | DEAD | 反转族 | — | 是 | claims_state.json=DEAD（周审计机器）+ AGENTS 台账 |
| 63 | 组合_缺口低_剔亏ST_超跌20_输家250 | L2 | DEAD | 缺口族 | — | 是 | claims_state.json=DEAD（周审计机器）+ AGENTS 台账 |
| 64 | 组合_缺口低开_低位_剔亏ST | EXP | RESEARCH | 缺口族 | REJECT | — | submit 20260919 REJECT（挂：G7_槽位10资金曲线>0） |
| 65 | 组合_缺口低开_低位阳线 | L2 | DEAD | 缺口族 | — | 是 | claims_state.json=DEAD（周审计机器）+ AGENTS 台账 |
| 66 | 组合_缺口低开_低位阳线_避周一 | L2 | DEAD | 缺口族 | — | 是 | claims_state.json=DEAD（周审计机器）+ AGENTS 台账 |
| 67 | 组合_触板低_TD9买_剔亏ST_超跌20 | L2 | CANDIDATE | 触板族 | — | 是 | claims_state.json=CANDIDATE（过闸门、未上生产） |
| 68 | 组合_触板未封_低位 | L2 | CANDIDATE | 触板族 | — | 是 | claims_state.json=CANDIDATE（过闸门、未上生产） |
| 69 | 组合_跌停低_MA20上穿滤 | EXP | RESEARCH | 跌停族 | REJECT | — | submit 20260919 REJECT（挂：G1_tNW≥3、G2_时间分段、G3_regime≥3/4、G5_位置匹配边际>0、G6_0.30%成本仍正、G7_槽位10资金曲线>0） |
| 70 | 组合_跌停低_TD9买_超跌20 | L2 | DEAD | 跌停族 | — | 是 | claims_state.json=DEAD（周审计机器）+ AGENTS 台账 |
| 71 | 组合_跌停低_TD9买_输家250 | L2 | DEAD | 跌停族 | — | 是 | claims_state.json=DEAD（周审计机器）+ AGENTS 台账 |
| 72 | 组合_跌停低_TD9买入滤 | L2 | DEAD | 跌停族 | — | 是 | claims_state.json=DEAD（周审计机器）+ AGENTS 台账 |
| 73 | 组合_跌停低_TD9卖出 | EXP | RESEARCH | 跌停族 | REJECT | — | submit 20260918 REJECT（挂：G2_时间分段、G3_regime≥3/4） |
| 74 | 组合_跌停低_三连阴 | L2 | CANDIDATE | 跌停族 | — | 是 | claims_state.json=CANDIDATE（过闸门、未上生产） |
| 75 | 组合_跌停低_三连阴_深跌 | L2 | SHADOW | 跌停族 | — | 是 | claims_shadow 桥（claims_shadow 影子盘在记账（只影子不推送）） |
| 76 | 组合_跌停低_三连阴_缩量 | L2 | DEAD | 跌停族 | — | 是 | claims_state.json=DEAD（周审计机器）+ AGENTS 台账 |
| 77 | 组合_跌停低_大长腿低位 | EXP | RESEARCH | 跌停族 | REJECT | — | submit 20260918 REJECT（挂：G1_tNW≥3、G2_时间分段、G3_regime≥3/4、G5_位置匹配边际>0、G6_0.30%成本仍正） |
| 78 | 组合_跌停低_海龟20滤 | EXP | RESEARCH | 跌停族 | REJECT | — | submit 20260919 REJECT（挂：G1_tNW≥3、G2_时间分段、G3_regime≥3/4、G5_位置匹配边际>0、G6_0.30%成本仍正、G7_槽位10资金曲线>0） |
| 79 | 组合_跌停低_深跌 | L2 | SHADOW | 跌停族 | — | 是 | claims_shadow 桥（claims_shadow 影子盘在记账（只影子不推送）） |
| 80 | 组合_跌停低_深跌_跌停潮 | L2 | SHADOW | 跌停族 | — | 是 | claims_shadow 桥（claims_shadow 影子盘在记账（只影子不推送）） |
| 81 | 组合_跌停低_缠论底滤 | EXP | RESEARCH | 跌停族 | REJECT | — | submit 20260919 REJECT（挂：G1_tNW≥3、G2_时间分段、G3_regime≥3/4、G5_位置匹配边际>0、G6_0.30%成本仍正、G7_槽位10资金曲线>0） |
| 82 | 组合_跌停低_缩量_TD9滤 | EXP | RESEARCH | 跌停族 | REJECT | — | submit 20260919 REJECT（挂：G2_时间分段） |
| 83 | 组合_跌停低_缩量_剔亏ST | L2 | DEAD | 跌停族 | — | 是 | claims_state.json=DEAD（周审计机器）+ AGENTS 台账 |
| 84 | 组合_跌停低_缺口低开 | EXP | CANDIDATE | 跌停族 | PASS | — | submit 20260918 PASS（过闸门，未注册条目） |
| 85 | 组合_跌停低_输家_超跌20_TD9滤 | L2 | DEAD | 跌停族 | — | 是 | claims_state.json=DEAD（周审计机器）+ AGENTS 台账 |
| 86 | 组合_跌停低_输家_超跌20_剔亏ST | L2 | DEAD | 跌停族 | — | 是 | claims_state.json=DEAD（周审计机器）+ AGENTS 台账 |
| 87 | 组合_跌停低_输家_超跌20_缩量 | L2 | DEAD | 跌停族 | — | 是 | claims_state.json=DEAD（周审计机器）+ AGENTS 台账 |
| 88 | 组合_跌停低_避雷针_缩量 | L2 | DEAD | 跌停族 | — | 是 | claims_state.json=DEAD（周审计机器）+ AGENTS 台账 |
| 89 | 组合_跌停低_避雷针低位 | L2 | DEAD | 跌停族 | — | 是 | claims_state.json=DEAD（周审计机器）+ AGENTS 台账 |
| 90 | 组合_跌停低_金叉MA5 | EXP | RESEARCH | 跌停族 | REJECT | — | submit 20260918 REJECT（挂：G2_时间分段） |
| 91 | 组合_跌停低_金叉MACD滤 | EXP | RESEARCH | 跌停族 | REJECT | — | submit 20260919 REJECT（挂：G1_tNW≥3、G2_时间分段、G3_regime≥3/4、G5_位置匹配边际>0、G6_0.30%成本仍正） |
| 92 | 组合_跌停低_长周期_超跌20 | L2 | CANDIDATE | 跌停族 | — | 是 | claims_state.json=CANDIDATE（过闸门、未上生产） |
| 93 | 组合_跌停低_长周期输家 | L2 | DEAD | 跌停族 | — | 是 | claims_state.json=DEAD（周审计机器）+ AGENTS 台账 |
| 94 | 缠论底分型 | EXP | IDEA | 形态族 | — | — | 无 claims 条目、无 submit 判决、无 candle 产物 → 未测/未提交（IDEA） |
| 95 | 缩量横盘放量突破 | EXP | IDEA | 突破族 | — | — | 无 claims 条目、无 submit 判决、无 candle 产物 → 未测/未提交（IDEA） |
| 96 | 缩量涨停_晋级 | EXP | RESEARCH | 妖股族 | REJECT | — | submit 20260914 REJECT（挂：G2_时间分段、G3_regime≥3/4、G4_市值≥4/5、G5_位置匹配边际>0、G6_0.30%成本仍正） |
| 97 | 缺口低开3% | EXP | IDEA | 缺口族 | — | — | 无 claims 条目、无 submit 判决、无 candle 产物 → 未测/未提交（IDEA） |
| 98 | 触板未封 | EXP | IDEA | 其他 | — | — | 无 claims 条目、无 submit 判决、无 candle 产物 → 未测/未提交（IDEA） |
| 99 | 超跌20_60日 | EXP | IDEA | 其他 | — | — | 无 claims 条目、无 submit 判决、无 candle 产物 → 未测/未提交（IDEA） |
| 100 | 跌停接_MA60上 | EXP | RESEARCH | 跌停族 | REJECT | — | submit 20260918 REJECT（挂：G2_时间分段、G3_regime≥3/4、G4_市值≥4/5、G5_位置匹配边际>0、G6_0.30%成本仍正） |
| 101 | 跌停接_MA60上_2月 | EXP | RESEARCH | 跌停族 | REJECT | — | submit 20260914 REJECT（挂：G5_位置匹配边际>0） |
| 102 | 跌停接_MA60下 | L2 | DEAD | 跌停族 | — | 是 | claims_state.json=DEAD（周审计机器）+ AGENTS 台账 |
| 103 | 跌停接_MA60下_gap>+1 | EXP | IDEA | 跌停族 | — | — | 无 claims 条目、无 submit 判决、无 candle 产物 → 未测/未提交（IDEA） |
| 104 | 跌停接_MA60下_gap≤-3 | EXP | IDEA | 跌停族 | — | — | 无 claims 条目、无 submit 判决、无 candle 产物 → 未测/未提交（IDEA） |
| 105 | 跌停接_MA60下_gap≤-5 | EXP | IDEA | 跌停族 | — | — | 无 claims 条目、无 submit 判决、无 candle 产物 → 未测/未提交（IDEA） |
| 106 | 跌停接_MA60下_gap≤0 | EXP | IDEA | 跌停族 | — | — | 无 claims 条目、无 submit 判决、无 candle 产物 → 未测/未提交（IDEA） |
| 107 | 跌停接_MA60下_小市值 | EXP | RESEARCH | 跌停族 | REJECT | — | submit 20260918 REJECT（挂：G3_regime≥3/4、G7_槽位10资金曲线>0） |
| 108 | 跌停接_MA60下_放量 | EXP | RESEARCH | 跌停族 | REJECT | — | submit 20260918 REJECT（挂：G7_槽位10资金曲线>0） |
| 109 | 跌停接_MA60下_缩量 | EXP | CANDIDATE | 跌停族 | PASS | — | submit 20260918 PASS（过闸门，未注册条目） |
| 110 | 跌停接_MA60下_避周一 | EXP | RESEARCH | 跌停族 | REJECT | — | submit 20260919 REJECT（挂：G7_槽位10资金曲线>0） |
| 111 | 跌停次日接_剔一字 | L2 | CANDIDATE | 跌停族 | — | 是 | claims_state.json=CANDIDATE（过闸门、未上生产） |
| 112 | 避雷针_低位 | L2 | DEAD | 形态族 | — | 是 | claims_state.json=DEAD（周审计机器）+ AGENTS 台账 |
| 113 | 避雷针_高位 | L2 | CANDIDATE | 形态族 | — | 是 | claims_state.json=CANDIDATE（过闸门、未上生产） |
| 114 | 金叉_MA5上穿20 | EXP | IDEA | 均线族 | — | — | 无 claims 条目、无 submit 判决、无 candle 产物 → 未测/未提交（IDEA） |
| 115 | 金叉_MACD | EXP | IDEA | 均线族 | — | — | 无 claims 条目、无 submit 判决、无 candle 产物 → 未测/未提交（IDEA） |
| 116 | 长周期反转_250日输家 | EXP | RESEARCH | 反转族 | REJECT | — | submit 20260913 REJECT（挂：G6_0.30%成本仍正） |
| 117 | 预增低位池_v1 | L2 | LIVE | 预增族 | — | 是 | AGENTS 生产线清单（#241/#251）：预增低位池生产线：cron stock_pead_pool.py → engine/pead_pool.py 调本探测器 |
| 118 | 高窄旗形HTF | EXP | IDEA | 形态族 | — | — | 无 claims 条目、无 submit 判决、无 candle 产物 → 未测/未提交（IDEA） |

## 迁移通道（AI 不得直接改状态）

状态迁移只接受 `docs/proposals/*.json`，字段：`{"id":…, "from":…, "to":…, "evidence":…, "approved_by":"user", "approved_at":"YYYY-MM-DD"}`；`--apply` 逐条校验（from 必须与当前一致、to 必须在 I6 枚举内）并追加 `data/registry/state_ledger.jsonl`。