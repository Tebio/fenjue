# K3 施工单：O-01~O-08 裁决落地 + PLAT-00 收尾（2026-10-21）

## 背景与授权

用户授权「主 agent 与 K3 商量做决定」。主 agent 已逐条复核你的建议书（research/O-decisions-brief-20261021.md），**8 条倾向全部采纳**，一处执行批注：

- O-01 止血顺序：**面板双模板最优先**（每日 9 班活泄漏），gitignore+迁移次之，历史沉没接受

## 落地动作

### 1. DECISIONS.md：OPEN → FROZEN 迁移
- O-01/02/03/05/06/07/08 共 7 条：从 OPEN 表移入 FROZEN 表，每条内容=倾向 + 一句话理由 + 作废条件（直接取自你的建议书，作废条件改写为反证条件格式与现有 FROZEN 条目对齐）
- O-04：**不转 FROZEN**——保留在 OPEN 表，加注「2026-10-21 裁决：证据不足，等 PORT-03 容量曲线；期间单槽 ≤10 万锚不动」
- 每条 FROZEN 编号沿用 D-XX 序列（接续现有最大编号）

### 2. AGENTS.md 追加 #356
内容：裁决账——8 条去向（7 FROZEN + 1 暂缓）、建议书指针（research/O-decisions-brief-20261021.md）、主 agent 复核全采纳、O-01 执行顺序批注、PLAT-00 卡点解除。

### 3. backlog.yaml 联动
- PLAT-00：evidence 更新（裁决已落地，引用 #356）；status: blocked → 按 PLAT-00 原始定义完成收尾（见第 4 步）后改 done
- O-04 关联条目（RISK-02/04、PORT-03）不动，等容量曲线

### 4. PLAT-00 收尾（它的定义：确认三份契约文档与裁决一致 + verify.sh 跑绿）
- 通读 INTERFACES.md / CONSTRAINTS.md / DECISIONS.md（裁决后版本），确认无互相矛盾；有矛盾列出来报告，不擅自改
- 跑 `bash scripts/verify.sh` 全量 + `python -m pytest tests -q`，记录输出

### 5. 验证与 commit
- pytest 25 passed 零新增失败 + verify.sh exit 0 是硬门槛
- commit message：`docs(AGENTS): #356 O-01~O-08 裁决落地（7 FROZEN + O-04 暂缓）+ PLAT-00 收尾`
- **不要 push**（推送由主 agent 决定）

## 纪律

- 先读 `/opt/data/skills/fenjue-dev/SKILL.md`，按「第一步」读权威文档
- AGENTS.md 只追加 #356，已有条目一字不动
- DECISIONS.md 的 OPEN 表条目是**移动**不是删除——内容完整搬进 FROZEN（倾向+理由+反证条件）
- 本单只动文档（DECISIONS/AGENTS/backlog），不改代码
- 验收数字（pytest/verify）必须实跑贴出

## 产出

- 改后的 DECISIONS.md、AGENTS.md、backlog.yaml
- 报告末尾贴：FROZEN 新增条数、OPEN 剩余条数、pytest/verify 输出末行、commit hash
