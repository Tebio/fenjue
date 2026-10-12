# SPEC · SEC-01 公开仓库剥离持仓与台账（P0，0.5 天）

## 目标
公开仓库 `github.com/Tebio/fenjue` 不再包含**真实持仓、资金、台账**类文件；面板与脚本照常工作。

## 非目标
- 不改变仓库可见性本身（是否转私仓由用户裁决；本 spec 只做"内容剥离"）
- 不动 `engine/` 代码

## 现状证据
`curl -I https://github.com/Tebio/fenjue` → 200（无鉴权可读）；`git ls-files` 共 33,096 个文件，其中 `data/` 32,275 个；
`config/watchlist.json`（真实持仓/成本/关键位）、`data/pead_pool_ledger.jsonl`、`data/ops_briefing_ledger.jsonl`、
`data/position_zones_*.json` 等均已公开。凭证扫描干净（无 key 泄露）。

## 输入
- `git ls-files` 全量清单
- 面板生成器：`engine/dashboard_build.py`（读取路径清单）
- 脚本读取路径：`engine/console.py`、`engine/stock_ops_briefing.py`（盘前作战单）

## 输出
1. `.gitignore` 增补（至少）：
   ```
   config/watchlist.json
   data/private/
   data/*ledger*.jsonl
   data/position*
   data/ops_briefing*
   ```
2. 私有载体二选一（**推荐 A**）：
   - A. 仓库内 `data/private/`（整个目录被 ignore）+ 脚本改读该路径
   - B. 独立私有 git 仓库/加密归档（`data/private` 作为 submodule 或外部目录）
3. 迁移脚本：`docs/plan/scripts/migrate_private.py`（把命中文件 `git mv` 到 `data/private/` 并改脚本常量）

## 契约
- **公开面**：只保留方法论、已证伪结论、代码、非敏感研究产物
- **私有面**：持仓、成本、资金槽位、台账 JSONL、委托单、对账输出
- 面板仍走 GitHub Pages，但**渲染时不含私有字段**（生成器分两个模板：public / private）

## 验收（正反例）
- 正例：`git ls-files | grep -E "watchlist|ledger|position"` → 输出为空
- 正例：`python3 engine/dashboard_build.py --check` 仍能构建面板（读私有路径成功）
- 反例：把 `config/watchlist.json` 放回公开路径 → 构建脚本或 CI 检查必须**报错拒绝**
- 额外：`git log --diff-filter=D --name-only` 中，历史提交仍含旧内容 → 记录并告知用户（**历史无法自动擦除**，需要 BFG/filter-repo 才能清除；由用户决定是否做）

## 依赖 / 风险
- 依赖：无
- 风险：脚本里存在硬编码路径（`grep -rn "watchlist\|ledger" engine/ scripts/` 必须先跑一遍找全）
- 风险：历史提交已公开 → 本 spec 只能阻止**增量**泄露

## 工期
迁移 0.3 天 + 验收 0.2 天
