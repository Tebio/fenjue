# daily_state · 权威日态包 schema v1.0（2026-10-16，#295）

> 目的：**单一事实源**。每天收盘后把「环境/触发/健康/KNN/持仓/簇」拼成一个包，消费端（preflight、晨报、面板、cron 编排器）**只读这个包**，不再各自去读八个上游产物的不同版本。
> 定位：**新增消费层，不改任何既有契约**（`docs/plan/INTERFACES.md` 仍 FROZEN；本包只引用其 I0/I8 通用约定，不修改任何已冻结字段）。
> 纪律：**只拼合，不重算任何信号**；缺源写 `unknown` 不猜；同日重跑覆盖（幂等）。

---

## 1. 文件与生命周期

| 项 | 规则 |
|---|---|
| 路径 | `data/daily_state/<YYYY-MM-DD>.json`（date = **已完成交易日**，BJT） |
| 生成 | `.venv/bin/python engine/build_daily_state.py [--date YYYY-MM-DD]`（默认=指数产物最新交易日） |
| 幂等 | 同日重跑：原子覆盖整包（`.tmp` → `os.replace`），不追加、不重复计数 |
| 编码 | UTF-8 无 BOM；原子写（I0） |
| git | **入库**（事实源须可审计）；`.gitignore` 的 `2026*.json` 通配已开例外（见 §6） |
| 体积 | 单包 ≈40–80KB（触发名单压缩成紧凑数组，不搬全量 1000+ 行原始产物） |

## 2. 顶层结构

```json
{
  "_meta":  { ... I8 可复现锚 + sources 版本 },
  "date":   "2026-10-15",
  "trading_day": { "latest": "2026-10-15", "next": "2026-10-16", "is_trading_day": true },
  "regime": { "axis": {...}, "age_entry": {...}, "env": {...} },
  "lines":  { "health": {...}, "triggers": {...}, "hits_index": {...} },
  "knn":    { "date": "...", "learn_rows": 0, "hist_quantiles": {...}, "scores": [...] },
  "cluster":{ "xrules": {...}, "deep_low_n": 0, "cluster_gate": 5, "pass": false },
  "holdings": { "positions": [...], "alerts": [...] },
  "freshness": { "<source>": {"file","mtime","date_field","date","status"} },
  "unknown": [ "缺失/过期源的清单（消费端看到 unknown 就知道哪里没数据）" ],
  "sections": { "regime": [...], "cluster": [...], "holdings": [...],
                "health": [...], "freshness": [...], "one_line": "..." }
}
```

**字段来源（一一对应既有产物，不发明）**

| 包内路径 | 上游产物 | 备注 |
|---|---|---|
| `regime.axis` | `data/regime_timeline_hcap.json[-1]` | hcap 轴=dict 列表，勿按 tuple 解包 |
| `regime.age_entry` | `data/regime_age.json`（`ages[today]` 或 `today`） | 段龄 |
| `regime.env` | `engine/env_state.py: env_state()` | **环境量唯一源**（趋势门/杠杆门/四象限/下阶段/贴水/温度/节日窗） |
| `lines.health` | `data/line_health.json` | 34 条线的 status/grade/score + 计数 + 危重名单 + T1–T7 触发 + 提案数 |
| `lines.triggers.*` | `docs/ops-state.json`(deep_low/b5/focus/positions_alert) · `data/reversal_confirmed.json`(executable) · `data/watch_pool.json`(pool) · `data/pead_pool_state.json`(holdings/pending) · `data/gold_current.json`(solo_fresh) | 当日各线触发**清单**（逐源带日期与新鲜度） |
| `lines.hits_index` | 由上面五源归并 | `{code: [src,...]}` 反查索引（消费端 O(1) 命中判断；preflight 用它替代逐源扫描） |
| `knn` | `data/similarity_daily_<date>.json` | 落盘则嵌入（`scores` 只留**当日在触发名单里的票**，压缩字段；全量仍在原产物） |
| `cluster` | `data/xrules_state.json` + ops-state deep_low 计数 | 簇门 ≥5 判过门 |
| `holdings` | `config/watchlist.json`(positions/levels) + ops-state positions_alert | 持仓哨兵关键位 |
| `freshness` | 每个源的 `mtime` + 其自带日期字段 | 见 §4 |

## 3. 触发名单压缩格式（控制体积）

`reversal_confirmed.executable` 原为 1000+ 条全字段，包内压缩成数组：

```json
{"source":"reversal_confirmed","date":"2026-10-16","n":1012,
 "rows":[["603986","兆易创新",-4.9,2.44,4]]}
```

行序固定 `[code, name, close_chg, open_chg, ladder]`（缺值 `null`）。`reversal_confirmed` 有**独立新鲜度**：其日期常为包日 `date + 1 交易日`（9:32 竞价确认名单是「次日执行」件），新鲜度判据=「≥ 包日」而不是「等于包日」。

## 4. 新鲜度戳（本包的核心价值）

每个源记 `{file, mtime(BJT), date_field, date, status}`，`status ∈ {ok, stale, missing}`：
- `ok`：源日期 ≥ 包日期（状态制池如 `watch_pool` 无单日日期，按其 `updated` 判）；
- `stale`：源日期 < 包日期（**消费端必须显示过期，不得当今日用**）；
- `missing`：文件不存在。

`freshness` 里任一 `stale/missing` 的源同步进顶层 `unknown[]`。**这是 #261（kcache 墙钟事故）那类「下游照跑吃陈数据」的结构性防线**：编排器/cron 只查这个数组，不必逐文件 stat。

## 5. 消费端接口

```bash
# 全包
.venv/bin/python engine/build_daily_state.py            # 生成/覆盖今日包
# 段落接口（晨报、推送文案直接取，不自己拼字符串）
.venv/bin/python engine/build_daily_state.py --section regime|cluster|holdings|health|freshness|one_line [--date D]
# 体检 CLI 优先读包（缺包/过期自动回落直连）
.venv/bin/python engine/preflight.py 601398 --from-state [PATH]
```

`--from-state` 语义：**`regime` / `命中存活线` / `簇状态` / `持仓哨兵` 四段从包读**（渲染代码与直连版共用同一函数，故逐段一致，有对拍验收）；**`KNN 单票投票` / `黑名单` / `位置带` 仍直连**——理由：KNN 是**任意票即时打分**（960 万行学习集，包无法预热全部票；包内只放当日触发票分数），黑名单/位置带依赖交易日级外部产物且不受日态包覆盖。这两段的「包化」列入待裁决清单（§6）。

## 6. 已知边界与待裁决

1. **`.gitignore` 例外**：仓库原有 `2026*.json` 通配会把 `data/daily_state/2026-*.json` 一并忽略；已加 `!data/daily_state/` 例外（本包必须入库才可审计）。
2. **KNN/黑名单/位置带 三段未包化**（见 §5），是否把 KNN 触发票分数纳入 preflight 优先读 → **待裁决**。
3. **其余消费端清单待裁决**：`ops_briefing.py`（9:25 作战单）、`dashboard_build.py`（面板「线健康榜」tab 由 t_0c770543 做）、盘中雷达、`line_health_report.md` 引用链——**目前均仍直连**，逐条改成「优先包/回落直连」需用户点头。
4. 包**不含**私有面（持仓成本/资金/台账）之外的敏感内容；`holdings` 只带关键位与备注，与 `config/watchlist.json` 公开性一致（I7）。
