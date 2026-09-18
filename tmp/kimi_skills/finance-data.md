---
name: finance-data
description: 付费源统一取数入口（ifind / Wind / S&P CapIQ，用用户自有网关与 key）。触发：一致预期/盈利预测/EPS预测/财报日期/公告/业务分部/电话会实录/可比公司/三表/K线
---

# finance-data：付费数据源统一取数入口

取数只走 `scripts/finance_fetch.py`：场景 + 标的，一次调用出数（统一 JSON 信封，
`ok=false` 是诚实失败不是用法错误）。路由表在 `routing.json`（机器 SSOT），
降级链在脚本进程内执行，只认真实失败（报错 / 空 / 不覆盖），不预先跳级。

**本 skill 只收链内含付费网关层的场景**（ifind / wind / sp_data）。每个场景的链都是
「免费层 ↔ 付费层」混合：免费层零配置直接出数；付费层未配置 key 时自动跳过、
诚实降级，不阻塞。纯免费场景（新闻快讯、SEC filing 列表、公司行动等）不在此列，
由各 skill 自带脚本或公开披露原文覆盖。

## key 配置（付费层，用用户自己的网关与 key）

- `DATASOURCE_BASE_URL` + `DATASOURCE_API_KEY` 环境变量；或 `~/.kimi/datasource.json`
  （`baseUrl` / `apiKey`）。**无内置默认网关**——未配置时付费层按失败降级，
  信封里如实标注，绝不静默。
- 协议：`POST {base}/call_data_source_tool`，见 `scripts/sources/gateway.py` 文件头。

## 调用纪律

- **一律用绝对路径**调脚本：`python3 "<skill 目录>/scripts/finance_fetch.py" ...`，不假设 cwd。
- **多期取数给足 timeout**：冷缓存 30–90s（热缓存秒级），Bash timeout 设 120s 以上——
  超时杀掉 ≠ 取数失败。
- 拿不准场景：`--list-scenarios` 打印 routing.json 实时清单（新场景只加 routing.json）。
- 拿不准工具能力：`--describe-tools` 汇集全部适配器 META（覆盖上限/复权口径/合规/成本/已知坑，
  本地毫秒返回）；单个适配器也可 `python3 <adapter>.py --describe`。

## 场景速查（`<market>.<need>`，market = `us|cn|hk`）

| scenario | 取什么 | 链（免费 ↔ 付费） |
|---|---|---|
| `cn.income` / `hk.income` | A股/港股利润表 | 东财 ↔ ifind |
| `cn.bs` / `cn.cf` / `hk.bs` / `hk.cf` | A股/港股资产负债/现金流 | 东财 ↔ ifind |
| `us.income` / `us.bs` / `us.cf` | 美股三表（R-file 直出，含 EPS 段） | SEC ↔ S&P |
| `cn.segments` | A股主营构成（半年频） | 东财 ↔ ifind |
| `hk.segments` | 港股业务分部（占比×总营收还原） | ifind（无免费结构化源） |
| `quote` | 行情快照（`--valuation` 加估值档） | yahoo/gtimg ↔ ifind |
| `cn.kline` / `hk.kline` | K线（默认前复权） | gtimg ↔ ifind ≤3 年 |
| `cn.consensus` | A股一致预期（mean + 机构家数） | 同花顺 ↔ ifind ↔ Wind |
| `hk.consensus` | 港股一致预期（逐券商中位数） | etnet ↔ Wind |
| `us.consensus` | 美股一致预期（结构化共识） | S&P CapIQ |
| `cn.events` / `hk.events` / `us.events` | 披露日程/下一期财报日期 | Wind / Wind / S&P |
| `cn.announcements` | A股公告列表 | ifind ↔ 巨潮官方原文 |
| `hk.announcements` | 港股公告（语义检索） | Wind |
| `us.transcripts` | 美股业绩电话会实录 | S&P CapIQ |
| `peers` | 可比公司 + 估值倍数（默认收敛 5 家） | S&P CapIQ |

别名：`cn.financials`→`cn.income`、`hk.financials`→`hk.income`、`us.financials`→`us.income`、
`cn.quote`/`hk.quote`/`us.quote`→`quote`、`us.peers`→`peers`。

## 口径与出数纪律

取数与口径见 `data-routing/SKILL.md`（家数 < 3 不出一致预期、锚只认 `period_end_date`、
FY1 EPS ≤ 0 不出正 PE、标财年不标日历年、复权口径靠对账认定）。本 skill 的例外：无——
本 skill 就是执行层，判据一条不松。各适配器 META（`--describe-tools`）里的覆盖上限
是「覆盖即降级」的机器依据；成本（¥/次）标在 META 与 routing.json 各层，
调用方按需收敛（如 peers 默认 5 家上限）。

参数形态与报错处理冻结在 `spec/ifind.md` / `spec/sp_data.md`（上游端点清单派生版；
`--refresh-spec <datasource>` 可重拉网关文档覆盖，维护用）。
