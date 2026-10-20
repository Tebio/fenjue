# 数据契约对标基线（外部成品项目）

**用途**：派单给 K3 / 任何施工方时，作为"设计契约"的唯一外部参照。要求施工方**抄契约、不抄架构**。
**取材**：dbt、Dagster、OpenLineage 的官方文档原文（2026-10-20 抓取），每条附原文与我们的对应关系。

---

## 0. 为什么是这三个，不是什么

| 候选 | 判 | 理由 |
|---|---|---|
| **dbt** | 采 | `sources.freshness` 的 `warn_after`/`error_after` 两级语义与我们的 DEGRADE_MARK/WRITE_BLOCK **同构** |
| **Dagster** | 采 | `@asset_check(blocking=...)` + `AssetCheckSeverity.ERROR` 定义了"检查失败 ⇒ 下游不执行"的官方语义，就是我们的拒写 |
| **OpenLineage** | 采（轻） | dataset/job/run 三元组 + facets 是血缘事实标准，用来校验我们的 `lineage.yaml` 结构没跑偏 |
| Dagster 全仓代码 | **不采** | 重框架 + 图调度，我们是"独立脚本 + YAML 注册表"，架构不同，硬抄会把项目带进沟里 |
| Great Expectations / Soda | 缓 | 断言库，我们已有 golden + verify.sh，引入是重复建设 |

**铁律**：抄的是**语义契约**（什么条件算什么状态、默认值、互斥规则），不是代码结构。

---

## 1. 两级新鲜度 —— dbt `freshness`

**官方原文（docs.getdbt.com/reference/resource-configs/freshness）**：
- `warn_after`：How old the most recent data can be before a freshness check reports a warning. Requires both `count` and `period`.
- `error_after`：How old the most recent data can be before a freshness check reports an error.
- `loaded_at_field`：Column dbt queries to determine the most recent loaded timestamp. **Required when adapter metadata is unavailable.**
- 「**One or both of `warn_after` and `error_after` can be provided. If neither is set, dbt will not check freshness for that resource.**」
- 「Each of `warn_after` and `error_after` requires both `count` and `period`; setting only one issues a parse warning but causes an error when `dbt freshness` runs.」

**我们的对应（`data/datasets_registry.yaml` + `engine/freshness_core.py`）**：

| dbt | 我们 | 状态 |
|---|---|---|
| `warn_after` → 警告 | `DEGRADE_MARK`（照写 + data_stale + 横幅） | 已有，语义一致 |
| `error_after` → 错误 | `WRITE_BLOCK`（拒写 + exit 1） | 已有，语义一致 |
| 两者都不配 → 不检查 | `EXEMPT` / 未纳管（`unregistered` 计数） | 已有，语义一致 |
| `count` + `period` 缺一 → 本地 warn、运行时报错 | 我们的 `unknown_date` / `missing` 分类 | 已有，更细 |

**裁决**：同构，不引入 dbt 命名。要吸收的是它的一条默认值纪律——**"不配就不检查"必须显式可见**（我们的 `unregistered` 计数就是这个作用，`data_health` summary 里已有）。

---

## 2. 阻断语义 —— Dagster asset checks

**官方原文（docs.dagster.io/api/dagster/asset-checks）**：
- `blocking` (bool)：「When enabled, runs that include this check and any downstream assets that depend on asset will wait for this check to complete before starting the downstream assets. **If the check fails with severity AssetCheckSeverity.ERROR, then the downstream assets won't execute.**」

**关键结构**：Dagster 把"**等不等**"（`blocking`）和"**拦不拦**"（`severity`）拆成两个正交维度。

**我们的对应**：
| Dagster | 我们 | 差异 |
|---|---|---|
| `blocking=True`（下游要等检查完） | 无对应，也不需要 | 我们是同步脚本，没有并发调度，不存在"等" |
| `severity=ERROR` + blocking → 下游不执行 | `WRITE_BLOCK`（拒写 + exit 1） | 一致 |
| `severity=WARN` → 下游照跑但留痕 | `DEGRADE_MARK`（照写 + data_stale + 横幅） | 一致 |

**裁决**：我们的 `WRITE_BLOCK` 把"等"和"拦"合成了一件事，在当前架构下是正确的（无可等待方）。**不要**为了对齐 Dagster 造出 blocking 维度。
要抄的是它的一条明确性：**"没通过 = 下游不执行"必须是硬阻断，不是提示**。我们的 `breaker` 已经这么做了（拒写且 exit 1，e2e 验证过 timeline md5 一字节未变）。

---

## 3. 配置互斥校验 —— 双方共同的纪律

**dbt 原文**：`loaded_at_query` 与 `loaded_at_field` 同时设置在同一资源上 → **parse error**（不是警告，是拒绝解析）。
**Dagster 原文**：`additional_ins` / `additional_deps` 不得包含 asset 参数本身。

**我们的对应**：`docs/plan/tools/plan_lint.py` 的 `[L0]` 段-格式一致性断言（`items` 必有 status；`not_doing` 必有 reason 且不得有 status/priority）。

**裁决**：**同类纪律**——配置层面能静态判定的矛盾，必须在解析期报错，不能留到运行期。
今日实证：`backlog.yaml` 六个条目错位在 `not_doing:` 段，旧 lint 按 id 查不看段，全判绿。[L0] 上线后人为错位立刻判红。

---

## 4. 血缘结构 —— OpenLineage

**它的事实标准结构**：`Run`（一次执行）× `Job`（做什么）× `Dataset`（读写什么），Dataset 带 `facets`（schema/ownership/dataQuality 等原子元数据片）。

**我们的 `data/lineage.yaml`**：
```yaml
datasets:
  big_kcache:
    direct: [深档名单, 影子盘, 周期仪, 权威时间轴, X规则线]   # ← 下游（job 侧）
downstreams:
  影子盘: {producer: engine/claims_shadow.py, trigger: {cron: ...}, artifacts: [{glob: ...}]}
```

**对照**：
| OpenLineage | 我们 | 说明 |
|---|---|---|
| `Dataset` | `datasets.<key>` | 一致 |
| `Job` | `downstreams.<名>` + `producer` | 一致（我们的 job = 一个脚本） |
| `Run` | 无 | **不需要**：脚本仓库没有 run 元数据服务，跑一次写一份产物就是 run 的全部事实 |
| input/output 方向 | `direct`（我影响谁）+ `producer`（我产出什么） | 方向相反但等价，因为我们同时做了 `impact()` 和反向产物断言 |

**裁决**：结构对齐，不引入 run 维度（YAGNI）。要吸收的是它"**facets 必须原子且可校验**"的纪律——对应我们的三条机械断言（producer 脚本必须存在 / artifacts glob 必须命中 / trigger 必须在 cron 查到或指向记载 manual 的文档行）。

---

## 5. 静态依赖推断 —— 有同类先例，K3 的"闭包层"方案不孤

K3 否决"运行时 IO hook"、主张"按 detector 的**闭包**推断（函数实际引用了哪些全局 → 全局来自哪个数据文件）"，这不是自创：

- **dbt**：`manifest.json` 通过**静态解析** `ref()` / `source()` 构建 DAG，不靠运行时观测。
- **Bazel / Buck**：`deps` 是**声明式静态**的，构建器据此剪枝；运行时观测只用于校验。
- **Python 生态**：`modulegraph` / `pipdeptree` / `vulture` 都在做静态可达性分析。

**裁决**：K3 方向正确且有先例。**运行时观测只作周度兜底断言**（"静态推导的 inputs 并集 ⊆ 实际观测到的文件并集"），不进生产路径——这与 Bazel 的"静态为主、观测校验"完全一致。

**反例（明确不抄）**：OpenLineage 的运行时 emit 模式（`emit_dataset_lineage`）依赖用户显式发事件，在我们这里等于让每个脚本自己上报——必然漏报，且和"声明式注册表 + 静态校验"的既有路线冲突。

---

## 6. 一句话给施工方

> 凡是 dbt / Dagster / OpenLineage 已经用一句话定义了语义的地方（什么算 warning、什么算 error、不配怎么办、矛盾配置怎么办），**先抄它们的定义，再映射到我们的命名**；不许自己发明第三种状态。
> 架构层面（框架 vs 脚本仓库、run 元数据、并发调度）**全部不抄**。
