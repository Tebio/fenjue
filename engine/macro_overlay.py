"""
宏观事件叠加层 (Macro Overlay) — V2.4 新模块。
每天从宏观事件计算评分，调整 MarketRegime 的仓位上限和产业乘数。

使用:
    overlay = MacroOverlay()
    score = overlay.score([("战争", -2), ("油价", -2), ("AI CapEx", -1)])
    regime["max_position"] *= overlay.adjust(score)  # 例: 0.6 → 0.48

原则:
    - 不替代 MarketRegime，只做线性调整
    - 事件可手动录入，也可从新闻源自动采集（V2.5）
    - 调整幅度保守：macro -4 只再降 20%
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MacroEvent:
    label: str
    score: int          # -3 到 +3: -3=大空, 0=中性, +3=大利好
    category: str = ""  # war, rate, fx, oil, capex, policy

    def __post_init__(self):
        self.score = max(-3, min(3, self.score))


class MacroOverlay:
    """宏观事件评分 → MarketRegime 调整系数。"""

    # 事件维度权重
    DIM_WEIGHTS: dict[str, float] = {
        "war":    1.0,   # 战争/地缘
        "rate":   0.8,   # 利率/美债
        "fx":     0.6,   # 汇率
        "oil":    0.7,   # 油价/大宗
        "capex":  0.9,   # AI 资本开支
        "policy": 0.5,   # 政策/产业
    }

    def __init__(self):
        self.events: list[MacroEvent] = []
        self._history: list[dict[str, Any]] = []

    # ── scoring ──────────────────────────────────────────────

    def score(self, events: list[tuple[str, int, str]] | None = None) -> dict[str, Any]:
        """
        计算宏观评分。

        Args:
            events: [(label, score_int, category_str), ...] 例: [("美伊冲突", -2, "war")]

        Returns:
            {score, adjustment, breakdown, position_pct_adj}
        """
        if events:
            self.events = [MacroEvent(label=e[0], score=e[1], category=e[2]) for e in events]

        raw = sum(e.score * self.DIM_WEIGHTS.get(e.category, 0.7) for e in self.events)

        # 归一化到 [-1, +1]
        max_possible = sum(abs(e.score) * self.DIM_WEIGHTS.get(e.category, 0.7) for e in self.events) + 0.001
        normalized = raw / max_possible  # [-1, +1]

        # adjustment: 宏观差 → 仓位再打折 (保守: 1.0 → 0.8 最大降幅)
        adjustment = 1.0 + normalized * 0.2  # normalized=-1 → 0.8, normalized=+1 → 1.2

        self._history.append({
            "raw": raw, "normalized": normalized,
            "adjustment": adjustment, "events": [(e.label, e.score, e.category) for e in self.events],
        })

        return {
            "raw_score": round(raw, 2),
            "normalized": round(normalized, 3),
            "adjustment": round(adjustment, 3),
            "position_pct_adj": f"{int(adjustment*100)}%",
            "breakdown": {e.label: e.score for e in self.events},
            "interpretation": self._interpret(normalized),
        }

    def _interpret(self, norm: float) -> str:
        if norm < -0.5:
            return "宏观显著利空，仓位应额外缩减"
        elif norm < -0.2:
            return "宏观偏冷，适度降低风险暴露"
        elif norm > 0.5:
            return "宏观显著利好，可适当提高仓位"
        elif norm > 0.2:
            return "宏观偏暖，标准仓位运行"
        return "宏观中性，不受事件干扰"

    # ── regime adjustment ────────────────────────────────────

    def adjust_regime(self, regime: dict[str, Any]) -> dict[str, Any]:
        """将宏观调整应用到 MarketRegime 输出。"""
        result = self.score()
        adj = result["adjustment"]

        new_regime = dict(regime)
        orig_max = regime.get("max_position", 0.6)
        new_regime["max_position"] = round(orig_max * adj, 2)
        new_regime["macro_overlay"] = {
            "score": result["raw_score"],
            "adjustment": adj,
            "events": result["breakdown"],
            "interpretation": result["interpretation"],
        }
        return new_regime


# ── daily preset (2026-07-08) ───────────────────────────────

def todays_events():
    """今日宏观事件。可每日手动更新或从 API 自动采集。"""
    return [
        ("美伊冲突升级",      -2, "war"),
        ("AI CapEx 消化期",    -1, "capex"),
        ("韩股暴跌拖累",      -1, "war"),
        ("美元走强",          -1, "fx"),
        ("人民币贬值压力",    -1, "fx"),
        ("油价上涨",          -1, "oil"),
        ("军工订单预期上升",  +1, "war"),  # 战争中军工反而利好
        ("AI 上游材料国产替代", +2, "capex"),  # 结构性利好
        ("10年美债收益率回落", +1, "rate"),
    ]
