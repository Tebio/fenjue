#!/usr/bin/env python3
"""docs/plan/tools/plan_lint.py — 计划自检（防止"框架自己烂掉"）

检查项：
  L1 悬空引用：docs/plan 与 AGENTS.md 里出现的 <AREA>-NN 必须都在 backlog.yaml 定义
             （该行含 `lint-ignore` 时跳过，用于 spec 里的"反例假 id"）
  L2 规格覆盖：**当前阶段门及已过门**的 P0/P1 条目必须有 specs/<ID>*.md（错误）；
             同范围内 P2 缺 spec 为警告；未到门的条目只做 info（-v 显示）
  L3 gate 完整：每条 item 必须有 gate ∈ {G0,G1,G2,G3}
  L4 依赖存在：depends_on 必须指向已定义 id
  L5 优先级合法：priority ∈ {P0,P1,P2}
  L6 not_doing 非空（防止"不做清单"被清空）

当前阶段门读 `docs/plan/STATE.yaml` 的 current_gate。
用法：python3 docs/plan/tools/plan_lint.py [-v|--strict]
退出码：0=无错误；1=有错误（--strict 时警告也算错）
"""
import re
import sys
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[3]
PLAN = ROOT / "docs" / "plan"
BACKLOG = PLAN / "backlog.yaml"
STATE = PLAN / "STATE.yaml"
GATE_ORDER = ["G0", "G1", "G2", "G3"]
ID_RE = re.compile(r"\b([A-Z]{2,5})-(\d{2})\b")
PRIOS = {"P0", "P1", "P2"}

try:
    import yaml
except ImportError:
    print("需要 pyyaml：用 /opt/hermes/.venv/bin/python 或 pip install pyyaml")
    sys.exit(2)


def main() -> int:
    verbose = any(a in ("-v", "--verbose") for a in sys.argv)
    strict = "--strict" in sys.argv
    data = yaml.safe_load(BACKLOG.read_text(encoding="utf-8"))
    items, not_doing = data["items"], data.get("not_doing", [])
    ids = {i["id"] for i in items} | {n["id"] for n in not_doing}
    current = "G0"
    if STATE.exists():
        current = yaml.safe_load(STATE.read_text(encoding="utf-8")).get("current_gate", "G0")
    cur_rank = GATE_ORDER.index(current) if current in GATE_ORDER else 0

    errors, warns, infos = [], [], []

    # L1 悬空引用
    docs = [p for p in PLAN.rglob("*.md")] + [p for p in (PLAN / "tools").glob("*.py")] + [ROOT / "AGENTS.md", BACKLOG]
    for p in docs:
        for n, line in enumerate(p.read_text(errors="replace").splitlines(), 1):
            if "lint-ignore" in line:
                continue
            for m in ID_RE.finditer(line):
                if m.group(0) not in ids:
                    errors.append(f"[L1] 悬空引用 {m.group(0)} 于 {p.relative_to(ROOT)}:{n}")

    specs = {p.name for p in (PLAN / "specs").glob("*.md")}

    for i in items:
        iid, prio, gate = i["id"], i.get("priority"), i.get("gate")
        has_spec = any(s.startswith(iid) for s in specs)
        # L3 gate
        if gate not in GATE_ORDER:
            errors.append(f"[L3] {iid} gate 缺失或非法：{gate!r}")
            continue
        # L2 规格覆盖（按门分级）
        in_scope = GATE_ORDER.index(gate) <= cur_rank
        if not has_spec:
            if in_scope and prio in ("P0", "P1"):
                errors.append(f"[L2] {iid}（{prio}，{gate} 在范围内）缺 spec —— 开工前必须先写")
            elif in_scope:
                warns.append(f"[L2] {iid}（{prio}）缺 spec")
            else:
                infos.append(f"[L2] {iid}（{prio}，{gate} 未到门）缺 spec")
        # L4 依赖
        for dep in i.get("depends_on") or []:
            if dep not in ids:
                errors.append(f"[L4] {iid} 依赖不存在：{dep}")
        # L5 优先级
        if prio not in PRIOS:
            errors.append(f"[L5] {iid} priority 非法：{prio!r}")

    if not not_doing:
        errors.append("[L6] not_doing 为空（不做清单被清空）")

    print(f"plan_lint: items={len(items)} not_doing={len(not_doing)} specs={len(specs)} current_gate={current}")
    if verbose:
        for x in infos:
            print("  ℹ️ ", x)
    if verbose or warns:
        for w in warns:
            print("  ⚠️ ", w)
    for e in errors:
        print("  ❌", e)
    if not errors:
        print("  ✅ 全绿（悬空引用 / 当前门规格覆盖 / gate / 依赖 / 优先级）")
    if errors or (strict and warns):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
