# 焚诀项目地图（2026-10-20 首版）

> 目的：让接手者（人和 agent）在动手前就知道"什么在跑、什么是死的、改哪里会炸"。
> 数据资产清单见 `docs/data-inventory.md`；派单与审计流程见 `docs/plan/PROTOCOL.md`。

## 一、四层结构

```
数据面  data/ (8.9GB 全本地)  ←  只有 13 个「生产者」脚本能写
   ↓
引擎面  engine/*.py (292 个)  ←  37 生产入口 / 31 库 / 102 研究工具 / 122 疑似死
   ↓
生产面  /opt/data/scripts（101 个，cron 真正调的就是它，**不在本仓库**）
   ↓
协议面  data/*.json 契约 + breaker.py 熔断 + data_health.py 体检 + verify.sh 总闸
```

**关键认知**：cron 调的是 `/opt/data/scripts/` 里的 101 个脚本，它们 `import` 或 `subprocess` 调 `fenjue/engine/*.py`。
所以"engine 里某脚本没被引用"≠死代码，也可能是被生产脚本 import 的库（31 个属于此类）。

## 二、一天的作业时序（生产链路）

| 时间 | 作业 | 产出 |
|---|---|---|
| 18:30 / 19:00 / 21:00 | `update_kcache` 两分片 + 兜漏 | `big_kcache/`、`big_kcache_unadj/`、`seam_metrics.json` |
| 19:00 后 | `update_m60` | `m60_cache/` |
| 盘中 9:25 | `ops_briefing` 作战单 | stdout → 推送 |
| 盘中每 5m | `reqable-tunnel-watchdog` 等 | 运维 |
| 15:0x 收盘后 | `fast_close_update`、`breadth_daily`、`zhaban_daily`、`cb_daily` | 各日度产物 |
| 20:35 | `stock_data_health.sh` → `data_health.py` | `data_health.json`（体检） |
| 20:40 | `dashboard_build.py` 面板 | `docs/dashboard.json`、`docs/ops-state.json` |
| 收盘后 | `regime_daily_append` / `xrules_daily` / `regime_age` | 权威时间轴、X规则线 |

熔断（`engine/breaker.py`）在 20:35 体检之后生效：体检判定某数据集 fatal → 次日相关下游拒写或降级。
三类语义见 `docs/plan/specs/DATA-07-circuit-breaker.md`。

## 三、活性统计（实测，非估计）

| 类别 | 数量 | 判据 |
|---|---|---|
| **生产入口** | 37 | 被 `/opt/data/scripts/` 直接调用 |
| **库** | 31 | 被其他 engine 脚本或生产脚本 `import` |
| **研究工具** | 102 | 无生产调用但有 ≤45 天内的产物（手动跑过，仍在用） |
| **疑似死代码** | 122 | 无生产调用 + 无 import + 无近期产物 |

### 已确认的死代码（抽样，不删只登记）
`downtrend_raid2..8`（7 个迭代残留）、`auction_*`（5 个）、`alpha_*`（3 个）、
`build_daily_state.py`（**全库零调用方**，产物停在 2026-10-15，却被接进了熔断的 DEGRADE_MARK——
这是个设计瑕疵：给一个没人跑的工具加降级标记）。

### 待核（判死可能有误，别急着删）
- ~~`daily_delta.py` / 「晨报」无生产者~~ —— **2026-10-20 已清口**：注册表登记了「晨报」下游，但 cron 搜不到任何作业、
  `line_health_report` 全库零引用，属"设计意图被当成现实登记"。已从下游定义与 `breaker.EXEMPT_WRITERS` 移除，
  `line_health.blocks` 改为真实消费者 `作战单9:25`（ops_briefing 嵌数据面段落 + data_stale 告警）。golden oracle 已确认性更新。
- `database.py` / `event_registry.py` —— 名字像基础设施，可能有动态引用，删前必须全库搜字符串。

### 判据的四个漏洞（K3 2026-10-20 咨询指出，已采纳）
122 这个数字**不可当结论用**，判据本身有系统性误判：
1. **一次性基建被判死**：`factor_census_base.npz`(222MB)、`similarity_features.npz`(446MB) 这类底座的生产者可能半年不跑，
   但产物天天被读。判据缺"产物仍被消费"这一腿——它们不是死代码，是**已完成的基建**。
2. **动态调用逃逸静态 grep**：subprocess 拼 f-string 脚本名、`importlib`/`getattr` 插件式加载、
   cron 的 agent 型 job 在 prompt 里用自然语言点名脚本——都不留 import 痕迹。
3. **跨仓库引用**：`/opt/data/skills/`（fenjue-screening 线）、`verify.sh`、`plan_lint.py` 的引用在 engine/ 内 grep 不到。
4. **产物命名无规律**被反向冤枉：输出名不带固定前缀的脚本，"近期产物"匹配不上就算死——而这恰好更可能是老脚本。

**结论**：核实死代码时必须加"产物被读"和"跨库字符串引用"两条复核腿，否则登记表本身会变成新的假账。

## 四、危险清单（改之前必看）

| 项 | 风险 |
|---|---|
| `/opt/data/scripts/` **不在本仓库** | **2026-10-20 已建独立 git 仓库**（115 文件入库，仅本地不推远端）。改前仍建议先 commit |
| `check_unadj_fresh.py`、`rebuild_unadj.py` 未跟踪但**正在生产用** | 已纳入版本控制（2026-10-20） |
| 判"死代码"的判据本身有系统性误判 | 见下方"判据的四个漏洞" |
| `lt_limitup_signal.py` **有 SyntaxError 却仍在生产引用列表里** | 已判死（#317），cron 已 disable；确认没有其它入口调它 |
| `k4_deep_v2.py` / `k3_deep_low_v2.py` 未跟踪 | 深档生产脚本无版本历史，改动前 `.bak` |
| `k4_panel.py` / `data/big_kcache/` | 禁止碰（序列污染源，见 AGENTS #330） |
| baostock 双进程 | 必须串行，否则数据错乱 |

## 五、纠错授权（用户 2026-10-20 明确）

> 允许在项目中纠错，不必事事请示。

边界：
- **可以直接改**：文档、注释、测试、死代码登记、版本控制纳入、契约自相矛盾处（如 spec R1）。
- **需要先说**：删除任何数据文件、改动生产脚本行为、改 cron 调度、重写既有实现。
- **永不擅自**：删 `big_kcache`/`k4_panel`/`big_kcache_unadj`、改 docker-compose、动用户持仓数据。

## 六、当前欠账（同步 AGENTS）

1. `data/seam_metrics.json` 生产未生成 —— 等 18:30 那班首次真实落盘
2. 「晨报」下游无绑定生产者（登记了依赖但没人产）
3. 122 个疑似死代码未逐个核实（只抽样）
4. 深档名单、周期仪的熔断仅 API 级验证
5. `stock_shadow_record.py` 未接熔断
