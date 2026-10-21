# OPT-01 注意力与 cron 减法审计 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把现状 75 个 cron 班按「是否直接关系钱」分类，产出可暂停清单（保留回滚不删），让「每日需人参与动作 ≤ 3 个」可执行。

**Architecture:** 纯分析+文档任务，不改任何 job 状态。三步：盘点（jobs.json + executions.db 近 30 天实测）→ 依赖扫描（防 #261 断链）→ 分类成文（md + yml + AGENTS 编号）。任何「暂停」动作不在本计划内——清单由用户签字后另行执行。

**Tech Stack:** python3（json/sqlite3 标准库）、/opt/data/cron/jobs.json、/opt/data/cron/executions.db

**Spec:** `docs/plan/specs/OPT-01-cron-diet.md`

## Global Constraints

- **不删除、不暂停任何 job**——本计划只产出文档（spec 非目标第 1 条）
- 不动排程时刻（spec 非目标第 2 条）
- 分类判据用 spec 的四分类写死口径：钱相关→保留 / 研究相关→降频 / 运维→保留且必须静默 / 重复装饰→暂停候选
- 每条「暂停候选」必须通过依赖扫描：产出文件不被任何其他 job 读取（spec 反例第 1 条，#261 教训）
- cron 班数按**现状**（75 个，2026-10-21），不是 spec 写的 63（spec 落笔后 fix5 加了新班）
- 解释器：/opt/data/fenjue/.venv/bin/python；涉及 baostock 的脚本需 PYTHONPATH=/opt/data/python-libs

## Review Focus

1. **上游断链**：暂停候选的产出文件被下游 job 读取 → Task 2 的依赖扫描必须抓到（spec 反例）
2. **「用户每天真的会看」误杀**：推送面 job（日报/雷达/操作台）不能仅因「研究相关」就进暂停候选 → Task 3 每条暂停候选必须写「暂停后谁会缺什么」
3. **数据面班误伤**：fix5 新上的 fund/cap 班是数据面回填，分类时归「运维/钱相关」不归「研究相关」
4. **一次性班残留**：已 completed 的一次性班（如影子收官审计）不该出现在「每日推送面」计数里 → Task 1 盘点时标注
5. **静默设计 vs 故障**：X规则线 silent 是设计静默（evidence 已实证），分类时别把「近 30 天无推送」直接当「不产钱」

---

### Task 1: 全量盘点（现状 75 班 + 近 30 天执行/推送实测）

**Files:**
- Create: `/opt/data/cache/scratch/opt01_inventory.json`

**Interfaces:**
- Produces: `{id, name, schedule, script, deliver, enabled, last_status, failure_streak, exec_30d, push_30d, one_shot}` 列表

- [ ] **Step 1: 提取 jobs.json 全量班表**

Run: `.venv/bin/python -c` 读 /opt/data/cron/jobs.json，提取每班的 id/name/schedule/script/deliver/enabled/last_status/failure_streak
Expected: 班数 == `hermes cron list | grep -c "Schedule:"` 的输出（两边对账，不一致要解释）

- [ ] **Step 2: executions.db 补近 30 天执行与推送数据**

Run: sqlite 查 executions.db，按 job_id 聚合 exec_30d（执行次数）与 push_30d（deliver 非 local 且有实际推送的次数）
Expected: 每班都有 exec_30d 数值（0 也是值）；查询输出落进 opt01_inventory.json

- [ ] **Step 3: 标注一次性班与已暂停班**

规则：schedule 含具体日期且已过 / status 为 completed 一次性 → one_shot=true；enabled=false → 标注 paused 原因（从 evidence/台账查：博客打磨 8-24 起停、周期仪到期自终止、转折 paused 回滚保险、雷达上午被 9:45 合并班取代）
Expected: opt01_inventory.json 落盘，班数 75，字段齐全

### Task 2: 依赖扫描（防 #261 断链）

**Files:**
- Create: `/opt/data/cache/scratch/opt01_depmap.json`

**Interfaces:**
- Consumes: Task 1 的班表
- Produces: `{产出文件 → [读取它的 job 列表]}` 映射

- [ ] **Step 1: 建产出文件清单**

对每个班：从其 script 文件 grep 它写哪些文件（`data/` 下的 json/jsonl/md/txt）
Run: 遍历 /opt/data/scripts/ + fenjue/engine/ 中被班调用的脚本，grep `open(..., 'w')` / `json.dump` / `write_text` 的目标路径
Expected: 每个班至少产出 0+ 文件路径；写不出的标注「产出未知-需人工看」

- [ ] **Step 2: 建消费关系**

对每个产出文件：grep 全部班脚本谁在读它（`open(..., 'r')` / `json.load` / `read_text`）
Expected: opt01_depmap.json 落盘；每个产出文件有 consumers 列表（空列表=无人读=暂停安全）

- [ ] **Step 3: 交叉核对已知关键链**

手工核对 5 条承重链在 depmap 里齐全：kcache 三班→data_health；fund 两片→data_health/freshness；regime 班→xrules 班（xrules 读 regime 产出）；影子盘班→结算班；体检班→全部数据源注册表
Expected: 5 条都在；缺任何一条说明 grep 漏了，回去补

### Task 3: 分类成文（md + yml）

**Files:**
- Create: `docs/plan/attention-budget.md`
- Create: `docs/plan/attention-budget.yml`

**Interfaces:**
- Consumes: Task 1 班表 + Task 2 依赖图
- Produces: spec 要求的全字段分类表

- [ ] **Step 1: 按 spec 四分类判据逐班归类**

75 班每班给：类型 + 建议（保留/降频/暂停候选）+ 理由（一句话，引用 exec_30d/push_30d/依赖数据）
硬规则：暂停候选 ⇒ depmap 里其产出文件 consumers 为空（否则打回改为保留并注明「上游不可停」）
Expected: 无「未分类」；钱相关/研究相关/运维/重复装饰四类齐全

- [ ] **Step 2: 写「每日需人参与动作」清单**

目标 ≤ 3 个：盘前确认 / 9:25 下单 / 盘后对账。逐班核对哪些班会产生「需要人响应」的推送，确认其余全部可归入「只异常推送」或「静默」
Expected: 清单 ≤ 3 条，每条对应到具体班 id

- [ ] **Step 3: 每条暂停候选写「暂停后谁会缺什么」**

Expected: attention-budget.md 落盘（人读）+ attention-budget.yml 落盘（机器读，同一份数据）

### Task 4: 台账与验收

**Files:**
- Modify: `AGENTS.md`（追加新编号 #357）
- Modify: `docs/plan/backlog.yaml`（OPT-01 evidence + status）

- [ ] **Step 1: AGENTS.md 追加 #357**

内容：分类原则（四分类写死口径）、班数对账（63→75 的由来）、暂停候选清单指针（attention-budget.md）、依赖扫描防断链机制、待用户签字

- [ ] **Step 2: backlog.yaml 更新 OPT-01**

status: todo → review（等用户签字暂停清单才 done）；evidence 记实测数字

- [ ] **Step 3: 全量验证**

Run: `cd /opt/data/fenjue && .venv/bin/python -m pytest tests -q && bash scripts/verify.sh`
Expected: 25 passed / exit 0（本计划只动文档，不应有红）

- [ ] **Step 4: Commit**

```bash
git add docs/plan/attention-budget.md docs/plan/attention-budget.yml AGENTS.md docs/plan/backlog.yaml
git commit -m "docs(OPT-01): 注意力减法审计——75班四分类+可暂停清单（待用户签字）"
```
不 push（主 agent 决定）

---

## Self-Review 记录

- Spec 覆盖：输出三项（md/yml/AGENTS 编号）→ Task 3/4；验收四正例 → Task 3 Step 1/2/3 + Task 4 Step 3；两反例 → Task 2（断链扫描）+ Global Constraints（不删）✅
- 步骤粒度：每步一个命令/一个产物，无 TBD ✅
- 类型一致：Task 间通过 json 文件传递，字段名一致 ✅
- Review Focus 五条均有对应步骤 ✅
- 比例：计划 ≈ 2× spec，审计类任务合理（无代码 transcript）✅
