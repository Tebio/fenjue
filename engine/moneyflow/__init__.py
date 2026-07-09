"""MoneyFlowEngine — 资金流向分析子引擎。

三条独立评价轴之一:
    Research Score  → 公司值不值得长期关注
    Capital Health  → 当前资金结构是否健康 (本模块)
    Execution       → 仓位建议

Sub-modules:
    margin      — MarginTracker: 融资融券数据 + 评分
    dragon      — DragonTracker: 龙虎榜数据 + 评分
    institution — InstitutionTracker: 机构持仓 (占位)
"""

from __future__ import annotations

from engine.moneyflow.margin import MarginTracker
from engine.moneyflow.dragon import DragonTracker
from engine.moneyflow.institution import InstitutionTracker


class MoneyFlowEngine:
    """聚合融资/龙虎榜/机构三个来源,输出 Capital Health 评级."""

    def __init__(self):
        self.margin = MarginTracker()
        self.dragon = DragonTracker()
        self.institution = InstitutionTracker()

    def assess(self, code: str, quote_data: dict | None = None) -> dict:
        """评估资金健康度。

        Returns:
            dict with keys:
                margin_score       — int 1-10
                dragon_score       — int 1-10
                institution_score  — int 1-10
                capital_health     — str label (crisis/danger/neutral/healthy/optimal)
                capital_health_stars — int 1-5
                details            — list[str] 解释文本
        """
        qd = quote_data or {}
        ms = self.margin.score(code, qd)
        ds = self.dragon.score(code)
        ins = self.institution.score(code)

        avg = (ms + ds + ins) / 3.0
        if avg >= 9:
            stars, label = 5, "optimal"
        elif avg >= 7:
            stars, label = 4, "healthy"
        elif avg >= 6:
            stars, label = 3, "neutral"
        elif avg >= 4:
            stars, label = 2, "danger"
        else:
            stars, label = 1, "crisis"

        details = []
        if ms <= 3:
            details.append(f"融资强平风险(融{ms})")
        elif ms >= 8:
            details.append(f"融资资金稳定(融{ms})")
        if ds >= 8:
            details.append(f"龙虎榜净买入(龙{ds})")
        elif ds <= 3:
            details.append(f"龙虎榜净卖出(龙{ds})")

        return {
            "margin_score": ms,
            "dragon_score": ds,
            "institution_score": ins,
            "capital_health": label,
            "capital_health_stars": stars,
            "details": details,
        }
