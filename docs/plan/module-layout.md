# 目标模块布局与依赖规则（module-layout）

> 目的：现在 494 个脚本、`0.15` 散在 109 个文件、14 个模拟脚本各写各的——**接手 AI 无从下手**。
> 本文定义**目标代码树 + 单向依赖 + 每个模块的契约**，以及**如何从现状迁移过去而不打断生产**。

---

## 1. 目标代码树

```
engine/
  core/            基础（无业务知识）: 日期/交易日历/序列工具/统计/IO
      dates.py         交易日历（官方 query_trade_dates 为真源，缓存；禁止用增量文件尾部当"今天"）
      series.py        前复权/不复权读取、对齐、切片、复权锚校验
      stats.py         HAC(Newey-West)、日历时间组合、DSR、block bootstrap、功效
      io.py            原子写(写临时文件再 rename)、utf-8-sig 读、JSONL 追加
  data/            数据访问层（唯一允许直接读 data/ 的地方）
      kcache.py        日K读取 + 新鲜度断言
      m60.py           分钟线读取
      events.py        公告/预增/两融/分红/HiThink 读取
      dq.py            DQ 断言（覆盖率/新鲜度/缺口/异常价/零成交）
      sources.py       双源交叉与 failover
      snapshots.py     PIT 快照与哈希
  taxfee/          费率与税费唯一真源 ★所有成本必须走这里
      __init__.py      fee(buy/sell, amount, code) / dividend_tax(持有期) / roundtrip_cost()
  portfolio/       组合层
      ledger.py        逐笔账本（现金守恒）、持仓、资金占用、净值曲线
      allocator.py     跨线资金分配与优先级
      cash_yield.py    打新 + 逆回购/货基收益
      attribution.py   P&L 归因（alpha/beta/成本/滑点/漏单/择时）
  risk/            风控层
      correlation.py   多线相关性（全期 + rolling）
      budget.py        回撤预算与波动率目标
      stress.py        历史极端窗口压力测试
  recon/           中台
      import_broker.py 券商成交 CSV 导入
      reconcile.py     逐笔对账与差异归类
  registry/        治理
      state.py         策略状态机（IDEA→…→DEAD）+ 生产调用守卫
      gates.py         四件套体检强制门
      retire.py        退役判据自动降级
  repro/           可复现
      manifest.py      params_hash + 数据快照日 + 代码版本 写入结果文件
      track.py         MLflow 包装
  monitor/         运维
      alerts.py        告警分级与冷却
      dq_jobs.py       周期性 DQ 检查（供 cron 调用）
  research/        研究工具（非生产）
      eventstudy.py    事件研究（统一入口，含日历时间/HAC/DSR）
      bootstrap.py     重抽样置信区间
      power.py         功效分析
  lines/           生产线（每条线一个模块，只允许 import 上面的层）
      pead_pool.py     预增低位池（现有 engine/pead_pool.py 迁入）
      limitdown_deep.py 深档跌停线
      gold.py          金股线
      rebalance.py     调样抢跑
      dividend_anchor.py 股息锚
      xrules.py        X规则线
      reversal.py      反转族（ICU）
ui/
  tearsheet.py     QuantStats/pyfolio 报告
  dashboard/       现有 docs/index.html 生成器（保留静态产物）
tests/
  golden/          关键数字冻结（回归）
  test_*.py        单测（每模块至少 1 个正例 + 1 个反例）
```

---

## 2. 单向依赖（只许向下，违反即事故）

```
lines/  ──▶  portfolio/  risk/  registry/  recon/  research/
                │          │        │          │
                ▼          ▼        ▼          ▼
             taxfee/ ────────────▶ core/
data/  ◀── monitor/ (只读断言)
repro/ 被所有层调用（纯记录，不产生业务逻辑）
```

**硬规则**
1. `core/` 不得 import 任何上层（只能标准库 + numpy/pandas）。
2. `lines/` 之间**不得互相 import**；跨线共享逻辑必须下沉到 `core/` 或 `portfolio/`。
3. 任何费用/税费只能来自 `taxfee/`；**`lines/` 与 `portfolio/` 里再出现 `0.15` 这类字面量视为 bug**。
4. `data/` 是唯一允许直接读 `data/*.json` 的地方（其他层经过 `data/` 的接口）。
5. 生产调用必须过 `registry/` 守卫：非 `LIVE`（或影子期 `SHADOW` 记账模式）的线不得出票。

---

## 3. 迁移策略（不打断生产）

现在 63 个 cron + 494 脚本在跑，**不能推倒重来**。规则：

- **只加不删**：新模块落地后，旧脚本改为 `from engine.<new> import ...`，一次一个文件；旧文件保留到该文件的所有调用点迁完。
- **先薄后厚**：`taxfee/`（1.5 天）→ `portfolio/ledger.py`（3 天）→ 再谈其他；每步都能单独验收。
- **口径迁移必须留对照**：迁移某文件时，同时跑旧实现与新实现，输出差异表；差异超过 0.1pp 必须解释（写进 AGENTS.md）。
- **迁移进度记在 `backlog.yaml` 的 PLAT-05**（口径迁移台账），完成一个勾一个。
- **生产脚本入口不变**：`/opt/data/scripts/stock_*.py` 的 wrapper 保持文件名与输出格式，内部实现替换（cron 的 `script` 字段零改动）。

---

## 4. 每个模块的验收基线（最低标准）

| 模块 | 最低验收 |
|---|---|
| `core/dates.py` | 与官方日历全年对齐；长假/月末/首日用例 |
| `core/series.py` | 前复权/不复权双读；复权锚漂移检测（哨兵） |
| `taxfee/` | 最低佣金 5 元、印花税、红利税三档税级；边界用例 |
| `portfolio/ledger.py` | 逐笔现金守恒断言；跨线合并净值可复现历史模拟 |
| `risk/correlation.py` | 4 线相关性 + rolling；与手算核对 |
| `recon/` | 一周真实对账单跑通，差异全部归类 |
| `registry/state.py` | 111 条有初始状态；非 LIVE 调用被拒 |
| `data/dq.py` | 能复现 #261 的 70% 覆盖率场景并报警 |
| `repro/manifest.py` | 任一结果文件可读出 params_hash + 快照日 + 代码版本 |
| `lines/*` | 与原脚本数字一致（±0.1pp），且**不出现新的成本字面量** |

---

## 5. 与现有目录的关系（不要混）

- `engine/`（现有 134 个脚本）＝**过渡区**：逐步迁入上面的子包；
  迁移完成的文件在文件头加一行 `# migrated -> engine/<pkg>/<mod>.py`，便于清点。
- `fenjue/tmp/`（210 个）与 `/opt/data/tmp/`＝**探索区**：结论级脚本必须迁进 `engine/research/`（PLAT-03）。
- `docs/`＝**产物区**（面板、报告、本蓝图）；`reports/`＝研究输出。
