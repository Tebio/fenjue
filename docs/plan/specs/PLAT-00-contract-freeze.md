# SPEC · PLAT-00 契约冻结（P0，G0 第一件事，1 天）

## 目标
在**任何业务代码动工之前**，把"接口面"钉死并可自检：`INTERFACES.md`（数据契约）、`CONSTRAINTS.md`（硬约束）、
`DECISIONS.md`（冻结决策）、`VERIFY.md`（验证契约）与 `docs/plan/tools/plan_lint.py` 全部就位且跑绿。

## 非目标
- **不写任何业务代码**（不建 `taxfee/`、不建 `portfolio/`）
- 不修改任何现有生产脚本

## 现状证据（为什么必须做）
- 自己的框架先出病：`PLAT-05` 悬空引用（`module-layout.md` 提到、backlog 未定义）；
  **14 条 P0/P1 无 spec** → 按"没 spec 不许开工"的规矩，它们全是死结（自查输出见 `AGENTS.md #268`）
- 历史病根：口径散落 109 个文件（#262-C）、每线一套模拟脚本（14 个）——**契约不统一时，新模块会再造一套**

## 输入
- `docs/plan/*.md`（本次新建的六份文档）
- `docs/plan/backlog.yaml`
- 用户对 `DECISIONS.md` OPEN 条目的裁决（`O-01`…`O-08`）

## 输出
1. `INTERFACES.md` / `CONSTRAINTS.md` / `DECISIONS.md` / `VERIFY.md` 就位且**内容与用户裁决一致**
2. `docs/plan/tools/plan_lint.py`：零错误（`L1` 悬空引用=0、`L3` gate 完整、`L4` 依赖完整）
3. `scripts/verify.sh`：可一次跑完"计划自检 + 语法检查 + 单测 + 回归"，当前状态下**如实报告 SKIP**
4. `backlog.yaml`：所有条目带 `gate` 字段；`PLAT-00`/`PLAT-05` 已定义
5. `AGENTS.md` 追加编号条目（记录 G0 完成 + OPEN 裁决结果）

## 验收
- 正例：`python3 docs/plan/tools/plan_lint.py` → 退出码 0，输出 `items=46 ... ✅ 全绿`
- 正例：`bash scripts/verify.sh` → 语法检查全部通过并打印统计（`py_compile OK: N files`），单测/回归如实 `SKIP`（尚未建立）
- 反例：故意在文档里写一个不存在的 id（如 `XXX-99`）→ `plan_lint` 必须报 `[L1] 悬空引用` 且退出码非 0  <!-- lint-ignore -->
- 反例：故意删掉某条 P0 的 spec → `plan_lint` 必须报 `[L2]` 错误（不是警告）
- 对照：`DECISIONS.md` 的 FROZEN 条目数 ≥ 15，且每条都有"反证条件"（不允许空）
- 耗时：`plan_lint` < 5s；`verify.sh`（不含回归）< 60s

## 回滚方式
文档改动纯增量：`git checkout -- docs/plan` 即回到旧状态；`verify.sh` 与 `plan_lint.py` 为新增文件，删除即回滚。

## 依赖 / 风险
- 依赖：用户裁决 `DECISIONS.md` 的 8 个 OPEN 条目（其中 `O-01`/`O-02`/`O-03` 会直接影响 G0/G1 内容）
- 风险：文档与实际实现漂移 → 用 `plan_lint` 每次 CI/手工跑一次来兜（L1/L3/L4 就是为漂移设计的）

## 工期
0.5 天（文档对齐用户裁决）+ 0.5 天（自检工具跑绿与验收）
