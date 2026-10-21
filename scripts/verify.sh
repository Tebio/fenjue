#!/usr/bin/env bash
# scripts/verify.sh — 总闸：一次跑完"计划自检 + 语法检查 + 单测 + 回归"
# 用法：bash scripts/verify.sh [--fast]
# 退出码：0=全绿；1=有失败项（--fast 跳过回归）
set -uo pipefail
cd "$(dirname "$0")/.." || exit 2
FAST=0; [ "${1:-}" = "--fast" ] && FAST=1

# 选一个有 pyyaml 的解释器
PY=""
# 2026-10-20：加 fenjue .venv —— 原候选都不含它，容器里 python3 是 3.14 无 yaml，
# 导致本闸长期跑不起来（#330 ABI 环境同源问题）。
# 2026-10-21（#353）：fenjue .venv 提为首选——本闸测的是 fenjue 代码，需要 fenjue 的
# numpy ABI（cp313）；/opt/hermes/.venv 哪天装了 yaml 但 numpy ABI 不对时会选出
# 「能 import yaml 却跑不动测试」的解释器。候选探测只验 yaml 不验 numpy，顺序就是防线。
for cand in "$PWD/.venv/bin/python" /opt/hermes/.venv/bin/python python3; do
  if command -v "$cand" >/dev/null 2>&1 && "$cand" -c "import yaml" >/dev/null 2>&1; then PY="$cand"; break; fi
done
[ -z "$PY" ] && { echo "❌ 找不到带 pyyaml 的 python（试过 .venv/bin/python, /opt/hermes/.venv/bin/python, python3）"; exit 1; }
echo "使用解释器: $PY"

FAIL=0
echo; echo "=== 1/4 计划自检 (plan_lint) ==="
if [ -f docs/plan/tools/plan_lint.py ]; then
  "$PY" docs/plan/tools/plan_lint.py || FAIL=1
else
  echo "SKIP: docs/plan/tools/plan_lint.py 不存在"; FAIL=1
fi

echo; echo "=== 2/4 语法检查 (py_compile engine/ + scripts/) ==="
OK=0; BAD=0
for d in engine scripts; do
  [ -d "$d" ] || continue
  while IFS= read -r -d '' f; do
    if "$PY" -m py_compile "$f" 2>/dev/null; then OK=$((OK+1)); else echo "  ❌ $f"; BAD=$((BAD+1)); fi
  done < <(find "$d" -maxdepth 1 -name '*.py' -print0)
done
echo "  py_compile OK: $OK files / FAIL: $BAD"
[ "$BAD" -gt 0 ] && FAIL=1
# 仓库内探索脚本（tmp/）只提示不阻塞
if [ -d tmp ]; then
  TBAD=0
  while IFS= read -r -d '' f; do "$PY" -m py_compile "$f" 2>/dev/null || TBAD=$((TBAD+1)); done < <(find tmp -name '*.py' -print0)
  [ "$TBAD" -gt 0 ] && echo "  ⚠️  tmp/ 探索脚本有 $TBAD 个编译失败（不阻塞）"
fi

echo; echo "=== 3/4 单元测试 (pytest) ==="
if "$PY" -c "import pytest" >/dev/null 2>&1 && [ -d tests ]; then
  "$PY" -m pytest -q tests || FAIL=1
else
  echo "SKIP: 尚未建立 tests/ 或未安装 pytest（PLAT-04 建立后生效）"
fi

echo; echo "=== 4/4 回归基线 (golden) ==="
if [ "$FAST" = "1" ]; then
  echo "SKIP: --fast"
elif [ -d tests/golden ]; then
  "$PY" -m tests.golden.check || FAIL=1
else
  echo "SKIP: 尚未建立 tests/golden/（PLAT-04 建立后生效）"
fi

echo
if [ "$FAIL" = "0" ]; then echo "✅ verify.sh 全绿"; else echo "❌ verify.sh 有失败项（见上）"; fi
exit "$FAIL"
