# DATA-07 · 熔断泛化（数据不合格 → 下游拒写，而非只告警）

## 目标
把「数据不可信 → 拒绝产出垃圾」从 regime 一处的临时 `exit 1`，泛化成注册表驱动的统一熔断：
数据集 `severity: fatal` 且状态阻断（`freshness_core.is_blocking`）时，其 `blocks` 列出的下游
**不许写盘**（或写盘但显式标 `data_stale: true`），不再靠各脚本自觉。

## 非目标
- 不自动补数、不自动重跑（同 #278 纪律）
- 不改任何评分/阈值/信号规则
- 不做常驻 watchdog

## 现状证据
1. `regime_daily_append` 有覆盖率闸（自制 `coverage()`），但它是孤例；
2. `xrules_daily` 的覆盖率闸只比末 bar 日期（2026-10-20 实测：kcache 停更时它照跑，产出 10-16 的判定并静默覆盖 state——`data/xrules_state.json` 的 `date` 停在 10-16 直到人工补跑）；
3. 其余下游（深档名单、影子盘、B5、观察池）对数据缺陷零校验。

## 输入 / 输出
- 输入：`data/data_health.json`（DATA-06 产物）+ `data/datasets_registry.yaml` 的 `blocks`
- 输出：`engine/breaker.py`（`allow(writer, ref_date) -> (bool, reason)`）、各下游入口一行调用；
  被拒绝时写 `data/breaker_events.jsonl`

## 接口契约
```python
def allow(writer: str, ref_date: str, root: Path = ROOT) -> tuple[bool, str]:
    """writer 在注册表的 blocks 里被任一阻断数据集点名 → (False, "被 <key> 阻断：<reason>")。
    data_health.json 缺失或损坏 → (True, "health 未知，放行并记 event") —— 不许因监控机自己挂了而全线停摆。"""
```
另含 **SEAM-FIX 指标化**：`update_kcache` 的复权漂移重拉次数/票数写进 `data/data_health.json` 的 `metrics.seam`，
不再只打日志；连续多日 seam 异常 → 该数据集降为 stale。

## 验收
- 正例：伪造 `big_kcache` fatal → 深档名单/影子盘入口 `allow()` 返回 False 且不写盘，`breaker_events.jsonl` 有记录
- 反例：`data_health.json` 删除 → 全部 `allow()` 返回 True（fail-open）且事件记录"health 未知"
- 对照：regime 现有覆盖率闸的行为与本熔断对同一伪造缺口的判决一致，差异逐条解释
- `metrics.seam` 真实出现在 json 里，数值等于当日 `SEAM-FIX` 计数

## 回滚
`breaker.allow` 全部调用点加开关位 `data/breaker_disabled.flag`，存在即全部放行。

## 依赖 / 风险
依赖 DATA-06。风险：fail-open 意味着监控机自身故障时熔断失效——这是有意的（宁可产出可疑数据也不要全线停摆），
但 `breaker_events.jsonl` 必须记录，事后可审计。

## 工期
1.0 人日


## 裁决修订 R1（2026-10-20，主 agent 勘察接入点后自我否决原设计）

勘察发现原 spec 的「fatal 且阻断 → 下游一律不许写盘」是**错的**，必须分两类：

### ① 追加型 / 记账型 → 拒写（write-block）
一旦写进历史序列就会被**永久污染**，事后无法分辨哪一行是脏数据：
- `权威时间轴`（regime_daily_append → regime_timeline_hcap.json）
- `X规则线`（xrules_daily → xrules_state.json，2026-10-20 已实证：kcache 停更时它按旧日期判并静默覆盖 state）
- `影子盘`（台账进 shadow_intents.jsonl，写错了直接污染胜率统计）
- ~~`回测族` 的**新数据追加**~~（2026-10-20 主 agent 撤回：与 R1-③ 的 EXEMPT 表自相矛盾，K3 施工时按更晚的接口契约执行 EXEMPT 并声明异议——它是对的。回测族产物可重跑可弃，不该占熔断面）
拒写 = 不写盘 + `breaker_events.jsonl` 记录 + 非零退出码。

### ② 展示型 → 照写 + 标 stale（degrade-mark）
用户必须能看到东西，同时知道它不可信。拒写会让他在数据断供时**什么都收不到**，比给他一个带警告的次优产物更糟：
- `作战单9:25`、`面板20:40`、`日度状态包`、`深档名单`、`周期仪`
做法：产物里带 `data_stale: true` + 依赖项清单，渲染层在顶部打横幅（ops_briefing 的 🚨 行已有雏形）。

### ③ 检查器 / 告警通道 → **豁免**（exempt，永不熔断）
这是最容易犯的错：熔断告警器等于**掐断告警**。数据断供时你更需要它跑：
- `盘前自检`（preflight）、`晨报`、`line_health`、`data_health` 自身
实现：`breaker.allow()` 对 `EXEMPT_WRITERS` 恒返回 True，且该豁免表写死在 `breaker.py` 里，
**不许由注册表 `blocks` 决定**——否则将来谁给注册表加一行就能把告警器静音。

### ④ 边界声明
`engine/` 下 200+ 研究脚本也写盘，但**不在熔断范围**：它们可重跑、产物可弃、不喂生产。
熔断只覆盖注册表点名的 11 个生产下游。这条要写进报告，防止有人误以为"全库都有了保护"。

### 接口补充
```python
WRITE_BLOCK = {"权威时间轴", "X规则线", "影子盘"}
DEGRADE_MARK = {"作战单9:25", "面板20:40", "日度状态包", "深档名单", "周期仪"}
EXEMPT_WRITERS = {"盘前自检", "晨报", "line_health", "data_health", "回测族"}

def allow(writer: str, ref_date: str) -> tuple[bool, str]:
    """EXEMPT 恒 True；WRITE_BLOCK 命中阻断项 → False；DEGRADE_MARK → True 但附 stale 标记。
    未登记的 writer → raise（新增生产下游必须先登记，防绕过）。"""
```
