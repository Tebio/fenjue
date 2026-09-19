# 会话交接卡（2026-09-19 晚）

> 用途：上下文压缩。新会话开场白只需要一句：「读 /opt/data/fenjue/docs/SESSION_STATE.md + AGENTS.md 尾部 108 条起，继续」。

## 系统现状快照
- 持仓：美能能源 001299，成本 9.675（9/18 清仓宝丰换入）。已否：赞宇/长信/宝丰。
- 注册表 39 条主张（claims_registry.yaml）；2026 为逆风年（全体系 T+5 无过 52%），开火等风：
  恐慌 regime 回归 + 裸底座滚动边际回正 + 连续两周审计过线。
- 最强组合（全七闸+容量）：深跌+跌停潮 94.2%/+14.1（纪录）、三连阴+深跌 91.7%（DSR 0.93）、
  输家250×超跌20 K1 年化 11.4%。执行口径：成簇日（K≥3）+ 次日 10:30 买 + T+5 尾盘卖。
- 影子盘：注册表桥已挂全部新主张，每交易日 19:00 BJT 自动登记回填。
- 雷达推送问责制：radar_push_log.jsonl 进账本自动回填盈亏。
- 黑名单：高位剧震（连板链+天量剧震 T+20 边际 -2.66pp）、高位避雷针、彩票/绞肉机/低价股（因子黑名单）。

## 基础设施
- Kimi Code 桥：/opt/data/scripts/kimi_bridge.py（数据源 25 源）；会话派单 API（:5646，需 profile 设 model）。
  九大金融技能已装在 Windows 侧，技能缓存在 .kimi-code/plugins/managed/institutional-finance-kit/skills/。
  **Windows 睡着时 Kimi 线不可用**；技能详见 devops/kimi-code-bridge skill。
- QQ 断连自救：/opt/data/scripts/qq_watch_daemon.sh（日志事件驱动）+ gateway:startup hook 自动武装。
- OpenClash：选择节点组已改 fallback（300s 探活自动切节点），覆写钩子持久化。
- NAS 容器：a-stock-mcp 幽灵容器 9/19 已重建（network_mode: container:hermes）。
- ASMR 播放器全卸（neokikoeru 付费墙/kikoeru-express 只认 RJ 号/navidrome 已删）。

## 纪律速查（新会话必读）
- 新信号必走 law_pipeline REGISTRY + submit 六闸门+G7；禁一次性脚本。
- 汇报必须全 horizon 曲线（T+1/2/3/5/10/20 胜率+均值+赔率），禁报单点（用户钦定）。
- 画像≠买点：描述性统计必须过闸门才准当条件（放量/小市值已被毙过）。
- GitHub push 纪律：本地验证完毕才推；GH_TOKEN@/opt/data/.env 拼 x-access-token，推完即擦。
- 参照案例校准阈值必须公开标注（金健两处教训）。
- 推送红线：胜率<50% 或滚动 edge 贴线不主动推；空仓是合法答案（明星电力教训）。

## 进行中/欠账
- 归因引擎 explain_card.py（为什么涨/跌、谁拉谁砸）v1 在建
- 2021 vs 2026 失效年对比：2026 恐慌期反指（-1.58%）≠ 2021 全面熄火——机制研究待续
- T1 加仓开关（+1.4pp/年）未影子验证；fill 率黑盒（打板口径）待 m60/影子定量
- 僵尸 data/kcache（新浪线 9/04 停更）归档/删除待裁决
- 周审计 cron 周六 10:00 BJT；周一体温计复检
EOF

---

## 9/19 深夜增量（切会话前必读）

- 注册表 48 条；三底座交叉全完成（恐慌/缺口/触板）；双腿=恐慌腿+主线腿（正交零撞车）
- 主线腿：regime 门控（主线期才玩），容量 K1 +5.5%/年；选票器=收阳最强（pick="strength"，容量验证 5.5→7.3%）
- 恐慌腿选票器=超跌最深（pick="deep"，右尾捕获 69%）
- PEAD 首跑：追利好 T+5 负期望；利空漂移 T+20 58.1%/+4.28（n=6713 最强）
- 流动性约束销账：剔入场日额<2亿 回撤 -8.0→-6.1% 免费
- 红队制度化：DS 裁决书 docs/redteam-20260919.md（17 实锤 1 驳回）；自我红队二轮 docs/self-redteam-2-20260919.md（Q2 未来函数自首撤回）
- 架构图 docs/fenjue-architecture.html（Archify 产出，语义已修）；Archify skill 已装；GitNexus 已装但守卫误拦，周一 cron 绕
- 穷尽地图 docs/BACKLOG.md
- 推送=事件驱动（stock_radar --event，5 分钟检查五类触发器，无事件零推送）；冲板推送进问责账本
- 事件推送 cron：焚诀事件驱动推送 */5 1-7 * * 1-5 UTC；10:30 定时档已暂停，14:45 复盘保留
- GitHub 最新 commit 7168a8fd
