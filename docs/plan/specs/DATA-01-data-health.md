# DATA-01 · 数据面监控机（data_health）

## 目标（一句话，可判定）
新增 `engine/data_health.py` —— 与 `engine/line_health.py` 同构的**数据源生命周期监控机**：
读声明式注册表 → 体检全部数据集的时效/存在性 → 落三输出 + 幂等状态 + 晨报段，
使「数据断供」在下游被静默消费之前就变成一条可见的 fatal 告警。

## 非目标（明确不做，防蔓延）
- 不做常驻 daemon、不做实时监控、不做 Grafana 式看板（焚诀形态是 cron + 静态产物 + 看门狗纪律）
- **不自动补数、不自动重跑生产者**（只读+落盘+提案，纪律同 line_health #278）
- 不在本期收编 `build_daily_state.py` 里 24 处局部 `freshness()` 调用（P1 单独做，避免与新建引擎混改）
- 不新增任何 cron job（P0 由既有 9:25 作战单与 20:40 面板消费）
- 不改任何信号线规则、不改评分、不改 regimer 判定

## 现状证据（写清"为什么现在不对"）
1. `data/big_kcache/*.json` 2026-10-19 三个 cron 班全挂（解释器 ABI：cp313 numpy 被 python3.14 加载），
   数据冻在 10-16；下游深档名单/影子盘/周期仪**照常运行、不报错**，直到人工发现。
2. `engine/regime_daily_append.py` 旧 `_intended_day()` 把 10-19（交易日）判成假日，
   重刷 10-16 后 `exit 0`、cron 报 **ok**，权威时间轴静默停更两天。
3. `engine/build_daily_state.py:74` 的 `freshness()` 是**局部函数**，24 处硬编码调用各自传参，
   无统一注册表、无严重级别、无消费者联动。
4. 现存三个孤立闸：`regime_daily_append.coverage()`、`check_unadj_fresh.py`、`capacity_ma60_gate.py`，
   各查各的、互不知情，也没有任何一处会告诉 `line_health`「你的输入不可信」。
5. `engine/line_health.py` 在数据断供时会照常用旧数据算滚动 edge，把「数据缺失」误判为「策略衰减」。
6. 交易日被当假日的根因是「谁都在自己数天数」——滞后判定必须以 `engine/trade_calendar.py` 为唯一基准。

## 输入 / 输出
- 输入：`data/datasets_registry.yaml`（新建，声明式注册表）
- 输出（路径必须符合 `INTERFACES.md I0`）：
  - `data/data_health.json`（机器可读全量，`_meta` 带 `version`/`date`/`generated_at`）
  - `data/data_health_state.json`（阈值机状态，同日重跑覆盖当日记录，不重复计数）
  - `data/data_health_report.md`（晨报/作战单段落）
  - `data/health/YYYY-MM-DD.json`（时序快照，用于「本月滞后几次」类趋势）
  - `engine/freshness_core.py`（时效判定唯一出处：`status`/`lag_trading_days` 逻辑）
- 调用：`python engine/data_health.py [--report] [--only KEY ...] [--ref-date YYYY-MM-DD]`

## 接口契约（demo 签名，未实现）
```python
# engine/freshness_core.py
STATUSES = ("ok", "stale", "fatal_lag", "missing", "unregistered", "unknown_date")

def trading_days_between(d_from: str, d_to: str) -> int:
    """按官方交易日历计滞后（禁止用自然日差）。日历不可用 → raise，不许猜。"""

def assess(key: str, spec: dict, ref_date: str, root: Path) -> dict:
    """返回 {key,path,date,status,severity,lag,cadence,max_lag,blocks,owner,reason}
    status 判定：文件/目录缺失→missing；日期解析不出→unknown_date；
    未注册但被列入必注册集→unregistered；lag>max_lag→fatal_lag(severity=fatal) 或 stale(warn/info)；
    否则 ok。date_expr 支持 "[-1].date"、"[-1].date|jsonl"、"_meta.date"、目录模式取最近写入者末 bar。"""

# engine/data_health.py
def check_all(ref_date: str | None = None, only: list[str] | None = None) -> dict:
    """{_meta:{version,date,generated_at,registry_version}, items:{key:{...}}, summary:{ok,warn,fatal,...}}"""

def main(argv=None) -> int:
    """写四输出；stdout 仅新增 fatal 触发时打印（Watchdog 纪律：无触发零输出）。
    退出码：0=无 fatal；1=存在 fatal_lag/missing（cron 报红）。"""
```

## 验收
- **正例**：`python engine/data_health.py --ref-date 2026-10-19` 后
  - `data/data_health.json` 存在且 `items.big_kcache.status == "ok"`、`lag == 0`（10-19 数据已补齐 94.4%）
  - `items.emotion_series.status == "ok"`（2131 行，末端 2026-10-19）
  - `summary` 各项计数之和 == 注册表条目数
- **反例**（必须报错/降级，不许静默通过）：
  - 构造一个 `max_lag: 0 / severity: fatal` 的假数据集（临时 yaml 片段，路径指向不存在文件）→
    `status == "missing"` 且退出码 1，且 `data_health_report.md` 出现该 key
  - 把某个 `date_expr` 写错（如 `"[-1].nope"`）→ `status == "unknown_date"`，**禁止**降级成 ok
  - 断言：任一 `severity: fatal` 的条目 `blocks` 为空 → 引擎必须报配置错误退出 2
- **对照**：对 `big_kcache`/`ops-state`/`regime_timeline_hcap`/`emotion_series` 四项，
  与 `build_daily_state.freshness()` 的 `status`（ok/stale）逐一比对，差异必须为空或逐条写出解释
- **耗时上限**：`--ref-date` 全量体检 < 60s，内存 < 300MB（禁止加载宇宙矩阵、禁止 baostock 抓数）
- **协议自检**：新增 golden case `data_health_snapshot`，断言
  (a) 每个注册条目都能解析出日期；(b) fatal 必带 blocks；
  (c) blocks 里每个下游名必须存在于 spec 的消费者清单；
  (d) `big_kcache`/`emotion_series`/`regime_timeline_hcap`/`ops_state`/`kcache` 必须在注册表内（防新数据集绕过注册）

## 回滚方式
全部为新增文件（`engine/data_health.py`、`engine/freshness_core.py`、`data/datasets_registry.yaml`、四输出），
唯一改动既有文件是 `engine/ops_briefing.py` 增加一行渲染（可 `git revert` 单文件）。
`ops_briefing` 侧必须 `try/except` 包裹：`data_health.json` 缺失时静默跳过，绝不让作战单发不出。

## 依赖 / 风险
- 依赖条目：PLAT-00（契约冻结）、`engine/trade_calendar.py`、`engine/line_health.py`（形态参照）
- 已知风险：
  1. `date_expr` 写错会静默返 None → 已用 `unknown_date` + golden 断言 (a) 兜住
  2. 退市/停牌 186 只票使 `big_kcache` 覆盖率天花板 ≈94.4% → 本期 freshness 只看**末端日期**不看覆盖率（覆盖率闸留在 regime 侧，P1 做白名单再合并）
  3. 9:25 作战单是每日必发推送 → 渲染必须 fail-soft，不许抛异常
  4. 注册表会腐 → 一期只注册真实在用的 10 个数据集，宁少勿滥

## 工期
1.0 人日：注册表+core 0.3 / 引擎三输出 0.3 / ops_briefing 接线 0.1 / golden+对照 0.3

## 裁决修订（2026-10-20 复核，主 agent 打回后落定）

**R1 · `unknown_date` 对致命数据集必须阻断。** 初版 `FATAL_STATUSES` 只含
`fatal_lag/missing/unregistered`，于是 fatal 级数据集 `date_expr` 写错时
`status=unknown_date` 而退出码仍为 0，cron 报绿——「解析不出」被静默吞掉，
与 #330「数据不可信不许翻译成今天没事」直接冲突。
落定：新增 `freshness_core.is_blocking(status, severity)` 作**唯一口径**
（missing/unregistered/fatal_lag 一律阻断；unknown_date 仅 `severity=fatal` 阻断；
warn/info 的 unknown_date 只进报告不阻断）。引擎四处判定点
（state 机 `fatal_active`/`fatal_days`、报告 🚨 段、退出码）与 `ops_briefing`
渲染必须全部调它，禁止任何消费者另写一份状态元组。

**R2 · 退出码契约补充**：0 = 无阻断项；1 = 存在阻断项；2 = 配置错误或基建不可用
（日历缓存缺失、fatal 条目 blocks 为空等）。`degraded` 段须排除已阻断项，避免同一故障在两段重复出现。
