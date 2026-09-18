# 全量测试清单（从文件系统盘，2026-09-18）

> 55 个研究脚本 / 84 个结果 JSON / 22 份报告 = 约 30 个批次。由脚本自动抽取，「该脚本分的轴」= 源码里出现的位置/深度/regime/分段/市值/量能/星期/月份 关键词。

| # | 结果文件 | 产出脚本 | 被测变体（从结果键抽出） | 该脚本分的轴 |
|---|---|---|---|---|
| 1 | banlu_backtest_20260913 | banlu_backtest.py | trigger_days, B2_全量, B1_池籍, B3_梯队, B4_梯队+首板+市值带, B5_B4+反人群期, B6_B4+早盘触发, B2_reg_平淡期, B2_reg_妖股期, B2_reg_主线期 | regime,市值,量能 |
| 2 | big_backtest | — | A, B, C, D, R | ? |
| 3 | bowei_shape_20260918 | — | date, stock, 样本, 今天, 形态B_高位小阴_当前形态, 形态A2_深跌≤-5且≤MA60, 形态X_首次跌破MA60, 结论 | ? |
| 4 | candle_research_20260911 | candle_research.py | TD9买入, TD9卖出, 大长腿_低位, 大长腿_高位, 避雷针_低位, 避雷针_高位, 随机对照 | 位置 |
| 5 | console_banks | console.py | strength, rows | regime,市值 |
| 6 | console_dividend_sectors | console.py | 煤炭, 保险, 运营商 | regime,市值 |
| 7 | console_sectors | console.py | 电力, 半导体 | regime,市值 |
| 8 | depth_position_grid_20260918 | — | date, 口径, rows, note | ? |
| 9 | dipbuy_backtest | dipbuy_backtest.py | B-dip2, B-dip5, B-open, R-dip1, R-dip2, R-open | — |
| 10 | dividend_anchor_oos | dividend_anchor_oos.py | scope, segments, universe_size_samples, caveats | 深度,分段,市值 |
| 11 | dividend_core_satellite_20260913 | dividend_core_satellite.py | window, equity, return%, maxDD%, trades, win%, by_year, universe, 核心仓卖出笔数, 卫星仓卖出笔数 | 分段 |
| 12 | dividend_core_satellite_exam2026 | dividend_core_satellite.py | window, equity, return%, maxDD%, trades, win%, by_year, universe, 核心仓卖出笔数, 卫星仓卖出笔数 | 分段 |
| 13 | dividend_sim_20260912 | dividend_sim.py | window, equity, return%, maxDD%, trades, win%, by_year, universe | 分段 |
| 14 | dividend_sim_exam2026 | dividend_sim.py | window, equity, return%, maxDD%, trades, win%, by_year, universe | 分段 |
| 15 | dividend_sim_unadj_20260913 | dividend_sim.py | note, window, fee_one_side, buy_thresh, sell_thresh, unadj, adj, signal_diff, unadj_missing, unadj_missing_sample | 分段 |
| 16 | entryexit_matrix | entryexit_matrix.py | matrix, by_regime, by_group | 位置,regime,分段 |
| 17 | exec_timing_m60_20260912 | exec_timing_m60.py | _meta, 反转全量(≤-3%), -3~-5%, -5~-7%, -7~-9.5%, ≤-9.5% | 深度 |
| 18 | factor_research_20260911 | factor_research.py | 因子月度超额(相对全宇宙等权), 日历效应-星期, 日历效应-月份 | 市值,量能,星期,月份 |
| 19 | failed_bounce_20260918 | — | date, 问题, 口径, A_跌停≤-9.8且收盘≤MA60_现有信号格, B_大跌≤-5且收盘≤MA60, C_大跌≤-5且当日首次跌破MA60, 结论 | ? |
| 20 | frontrun_fill_20260912 | — | 002519, 002848, 600207, 603693, 605058 | ? |
| 21 | frontrun_intersection_20260912 | frontrun_intersection.py | meta, V0, V1, V2, V3 | 位置,regime,分段,市值 |
| 22 | hold_dynamic_20260912 | hold_dynamic.py | fixed5, board_overnight, dynamic, dynamic_why | regime,市值,量能 |
| 23 | hold_dynamic_fill_20260912 | hold_dynamic.py | fixed5, board_overnight, dynamic, dynamic_why | regime,市值,量能 |
| 24 | holding_research_20260911 | holding_research.py | E1_跌3%, E1_跌5%, E1_跌7%, E1b_跌5%×大盘红, E1b_跌5%×大盘跌>0.5%, E1b_跌5%×站上MA60, E1b_跌5%×MA60下, E1b_跌5%×破20日新低, E1b_跌5%×未破20日低, E1b_跌5%×倍量 | 位置,深度,量能 |
| 25 | hot_regime_scan_20260912 | hot_regime_scan.py | 首板次日, 二连板晋级, 强势回调(MA60上-3%), 新高突破(20日+5%), 反转族对照(任意-3%) | 位置,regime,市值,量能 |
| 26 | law_pipeline_candle_20260911 | law_pipeline.py | TD9买入, 大长腿_低位, 避雷针_低位, 避雷针_高位 | 位置,深度,regime,分段,市值,量能 |
| 27 | law_pipeline_candle_20260913 | law_pipeline.py | 反转族_MA60上, 反转族_MA60下, PEAD_预增50+, PEAD_强利好, PEAD_强利空 | 位置,深度,regime,分段,市值,量能 |
| 28 | law_pipeline_submit_20260911 | law_pipeline.py | TD9买入, TD9卖出, 大长腿_低位, 大长腿_高位, 避雷针_低位, 避雷针_高位 | 位置,深度,regime,分段,市值,量能 |
| 29 | law_pipeline_submit_20260913 | law_pipeline.py | banlu_b5, TD9买入, TD9卖出, 大长腿_低位, 大长腿_高位, 避雷针_低位, 避雷针_高位, 长周期反转_250日输家 | 位置,深度,regime,分段,市值,量能 |
| 30 | law_pipeline_submit_20260914 | law_pipeline.py | 跌停接_MA60上_2月, 缩量涨停_晋级, 放量涨停_对照 | 位置,深度,regime,分段,市值,量能 |
| 31 | law_pipeline_submit_20260918 | law_pipeline.py | 跌停次日接_剔一字, 跌停接_MA60下, 跌停接_MA60上, frontrun_v2, 跌停接_MA60下_缩量, frontrun_v2_低位追, banlu_b5, banlu_b5_MA60上, banlu_b5_MA60下 | 位置,深度,regime,分段,市值,量能 |
| 32 | lianban_persistence_20260914 | — | total_events, universe, by_streak_dragon_pos, by_dragon | ? |
| 33 | limitdown_odds_20260918 | — | -3~-5|MA60上|T+1, -3~-5|MA60上|T+5, -3~-5|MA60下|T+1, -3~-5|MA60下|T+5, -5~-7|MA60下|T+1, -5~-7|MA60下|T+5, 真跌停≤-9.8|MA60下|T+1, 真跌停≤-9.8|MA60下|T+5, -5~-7|MA | ? |
| 34 | limitdown_odds_stability_20260918 | — | date, signal, 口径, 全样本, 对照_MA60上, 分年_T+1, 双段, 近500日_T+1, 近250日, 深度剂量_赔率_T+1 | ? |
| 35 | limitup_capture_t0_20260912 | limitup_capture_t0.py | Q1涨停捕获, Q2做T | 深度,市值 |
| 36 | ma_cycle_test | ma_cycle_test.py | 周K-其他, 月K-其他, 周K-科技, 月K-科技, 周K-银行, 月K-银行 | 位置,regime |
| 37 | mainline_dynamic_20260912 | mainline_dynamic.py | S1, S2, S3, S4, S2_why | regime,市值 |
| 38 | mainline_dynamic_fill_20260912 | mainline_dynamic.py | S1, S2, S3, S4, S2_why | regime,市值 |
| 39 | meineng_events_20260918 | — | date, stock, 口径, rows, 今天的对照 | ? |
| 40 | momentum_pead_20260913 | momentum_pead.py | A_price_momentum, B_pead_T20, B_pead_by_year | 位置,分段,量能 |
| 41 | news_event_study_20260912 | news_event_study.py | 资讯×盘中尾盘买, 资讯×次日开盘买, 复盘×盘中尾盘买, 复盘×次日开盘买, _meta | 量能 |
| 42 | north_profile_20260912 | north_profile.py | meta, coverage, latest_quarter, moves, top_ratio, top_increase_industries, coverage_by_industry, increase_stocks, decrease_stocks | 市值 |
| 43 | psy_laws2_20260913 | psy_laws.py | Z1_蔡格尼克_触板未封, Z2_曝光效应_第N次涨停_T1, Z3_峰终定律_T5, Z4_板块回锅肉_T1, Z5_初生牛犊_首板T1 | 深度,regime,分段,量能 |
| 44 | psy_laws_20260913 | psy_laws.py | T1_长周期反转_60日持有, T1_分段, T2_钝刀割肉, T2_分段_阴跌T5, T3_涨停后注意力衰减_追入口径 | 深度,regime,分段,量能 |
| 45 | regime_oos_validation | — | scope, anchors, conclusion, contamination_diff | ? |
| 46 | s10_retest_20260912 | s10_retest.py | raw, noLU, noLU_noLD | 分段 |
| 47 | s3_combo_20260912 | s3_combo.py | A 反转×主线期, A 反转×妖股期, A 反转×恐慌期, A 反转×平淡期, B 反转×周一, B 反转×周二, B 反转×周三, B 反转×周四, B 反转×周五, C 跌幅-3~-5% | 位置,深度,regime,市值,量能,星期 |
| 48 | seasonal_modulation | — | version, method, rules, discipline | ? |
| 49 | seat_gene_20260912 | seat_gene_backfill.py | meta, baseline_all_seat_buys, baseline_org_buys, profiles | 市值,量能 |
| 50 | seat_gene_gates_20260912 | seat_gene.py | ORG_BUY, GEJU_BUY, SHOUGE_BUY, ZHANG_BUY | 市值,量能 |
| 51 | seat_gene_rolling | seat_gene.py | window, days, seats | 市值,量能 |
| 52 | seat_taste_rolling | — | window, days, seats | ? |
| 53 | second_axis_grid_20260918 | — | date, 口径, 轴, note, claims | ? |
| 54 | second_axis_submit_20260918 | — | date, 批次, 口径, 结论_头条, signals | ? |
| 55 | sector_vshape_20260913 | sector_vshape.py | index_level, verdict, stock_level_n | 深度,分段 |
| 56 | sim_audit_20260912 | sim_audit.py | rev_n, scalp_n, A_sample60_mismatch, B_tiers, C_monthly_top5, C_monthly_bottom5, C_sep24_share%, D_slip0.003_equity, D_slip0.005_equity, E_avg_win% | 深度 |
| 57 | sim_play_fill_m60_20260912 | sim_play.py | window, trading_days, trades, trade_win%, trade_avg%, sim_equity, sim_return%, max_drawdown%, bench_index%, by_claim | 深度,市值 |
| 58 | sim_regime_split_20260912 | sim_regime_split.py | by_year, by_regime, regime_best_arm_样本内, switched_portfolio | regime,分段,市值 |
| 59 | sim_regime_split_8y_20260912 | sim_regime_split.py | by_year, by_regime, regime_best_arm_样本内, switched_portfolio | regime,分段,市值 |
| 60 | sim_retest_t1_20260912 | sim_retest_t1.py | R2_对账, R3_连板跌停 | 深度 |
| 61 | sim_tournament_20260912 | sim_tournament.py | window, days, capital, bench%, basket, strategies | 位置,regime,市值,量能 |
| 62 | sim_tournament_2y_20260912 | sim_tournament.py | window, days, capital, bench%, basket, strategies | 位置,regime,市值,量能 |
| 63 | sim_tournament_8y_20260912 | sim_tournament.py | window, days, capital, bench%, basket, strategies | 位置,regime,市值,量能 |
| 64 | smallcap_20260911 | smallcap_research.py | 全段, 2019-2022, 2023-2026, 逐月明细 | 分段,市值 |
| 65 | stock_shape_20260918 | — | date, 问题, 当前状态, 口径, 形态定义, 美能能源, 博威合金, 全市场基线, 结论 | ? |
| 66 | strategy_zoo_20260911 | strategy_zoo.py | S1 反转族(昨跌≥3%), S2 涨停收盘打板(尾盘挤进), S3 首板次日开盘追, S4 二连板次日追, S5 20日新高突破(海龟短), S6 55日新高突破(海龟长), S7 MA20上穿, S8 超跌20%(60日内), S9 三连阴买, S10 跌停次日接 | 分段,量能 |
| 67 | style_switch_20260913 | style_switch.py | meta, result | 分段,市值 |
| 68 | wait_for_limitdown_20260918 | — | date, 问题, 口径, 结果, 结论 | ? |
| 69 | watch_pool_backtest_20260912 | watch_pool.py | A_原版, B_试盘宽容, C_折中 | 量能 |
| 70 | zhaban_backtest_20260912 | zhaban_backtest.py | meta, R, U, matched_mid_T1c | 位置,regime,分段 |
| 71 | zhaban_features_20260913 | zhaban_features.py | meta, baseline, feature_tables, rule_search, multiple_testing | 分段,市值,量能 |
| 72 | zhaban_m60_fill_20260912 | zhaban_m60_fill.py | meta, 挂+6%, 挂+7%, 挂+8% | — |
| 73 | zhaban_shadow_summary | — | 更新时间, 登记日, 总登记, 已回填, 待回填, 未成交, 成交率%, 均笔%, 胜率%, 累计收益% | ? |
