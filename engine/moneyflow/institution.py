"""
InstitutionTracker — 机构资金跟踪（暂为占位）。

TODO (hook):
    - 北向资金 (沪股通/深股通) 持仓变化
    - 基金季报持仓数据
    - 机构调研/大宗交易信号
"""

from __future__ import annotations


class InstitutionTracker:
    """Placeholder institution-flow tracker — always returns neutral."""

    def score(self, code: str) -> int:
        """Return a neutral institutional score (5) for now."""
        _ = code
        return 5
