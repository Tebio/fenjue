# 焚诀架构（2026-09-19 立，用户令「不要代码堆叠，要联动」）

## 数据流（联动总图）

```
数据底座                    引擎层                     判定层                    执行层
─────────────         ──────────────         ───────────────         ───────────────
big_kcache(前复权) ─┐
cap_hist(日频PIT)  ─┤                     ┌→ submit 闸门 G1-G7 ─→ claims_registry（状态机）
fund_cache(估值)  ─┼→ Universe/fjcore ─→ │   （统计+容量）            ↕ 周审计 kill 线
hithink(龙虎榜)   ─┤   REGISTRY 信号库    │                            ↓ DECAYING→静默
m60(分钟线)      ─┘                     ├→ capacity_sim（成簇K/深跌选票/出场规则）
                                        ├→ explain_card 归因（为什么涨跌）
                                        └→ claims_shadow 影子盘（前向 L5）
                                                                 ↓
                              推送层：事件驱动（stock_radar --event，五类触发器，无事件零推送）
```

**反馈闭环**：影子盘回填 → 周审计滚动边际 → kill 线触发降级 → 推送静默 → 恢复条件达标再复活。
这是「写死废除」的机械实现：每条主张都活着被审计，死了自动闭嘴。

## 分层纪律（新代码必读）

1. **新模块一律 `from fjcore import ...`**，禁止直接 import law_pipeline 读 `_XCAP/_XFUND/_XLDC` 等全局
2. **统计只认 `fjcore.stats()` / `forward()`**，禁止再写第三份 fwd/stat 实现
3. **汇报只出 `full_curve()`**（全 horizon），禁单点
4. 出场规则登记在 `fjcore.EXIT_RULES`，新出场规则先登记再测
5. 检测器定义只进 `law_pipeline.REGISTRY`（它是信号库的物理载体，门面直通）
6. law_pipeline 本身进入「只读引擎」状态：改它的只有 bug 修复和 PIT 修复

## 绞杀者迁移路线（存量模块逐步收编，不急不躁）

| 模块 | 状态 | 迁移动作 |
|---|---|---|
| exit_rule_grid / cross_matrix / research_queue / explain_card / winloss_autopsy / pick_ranker / intraday_panic_grid / regime_full_study / good_regime_playbook / y2026_check | ✅ 今天的 | 下轮改用 fjcore（行为不变，纯收编） |
| claims_shadow / claims_audit | ✅ 生产中 | PIT cap 已修；下轮接入 fjcore.Universe |
| 股票 cron 群（雷达/影子/周期仪/看门狗） | ✅ 生产中 | 不动逻辑，只改引用 |
| 僵尸 data/kcache（新浪线） | 🪦 已归档 | kcache_legacy_sina_停更20260904 |

## 今天自查出的脏数据/逻辑bug（全部销账）

1. **G4 市值闸门未来函数**（月末值+当月边界）→ PIT 修复，判决不变（毒性微量，性质严重）
2. **regime 时间轴停在 9/11**（kcache 已 9/18）→ 重建中（本 commit 前已触发）
3. **claims_shadow 市值档同型旧口径** → 已同步 PIT 修复
4. **regime 双来源嫌疑** → 洗清（两个来源是同一个文件，0 不一致）
5. explain_card 均值双乘 100 → 已修（364% 一眼假）
6. cross_matrix 对照池含其他信号日 → 位置对照口径可接受，记录不追
