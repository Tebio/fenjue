"""
Macro → Industry Mapping (V2.6a)
宏观事件自动映射到产业权重调整。

原理:
    地缘冲突 → 油价↑ → 化工受益 → 兴发×1.05
    AI CapEx↓ → HBM降权 → 雅克×0.97, 长电×0.96

使用:
    mapper = MacroIndustryMapper()
    mapper.load_events(registry)
    adjustments = mapper.map()  # → {"AI材料": 1.05, "半导体": 0.94, ...}
"""
from __future__ import annotations
from typing import Any


# ── event → industry mapping rules ───────────────────────────

EVENT_INDUSTRY_RULES: dict[str, list[tuple[str, float]]] = {
    # category name → [(industry, multiplier_adjustment), ...]
    "geopolitics": [
        ("军工电子", +0.15),   # 战争 → 军工受益
        ("AI材料",   +0.05),   # 资源安全关注上升
        ("新能源",   -0.05),   # 风险偏好下降
    ],
    "ai_capex": [
        ("AI材料",   +0.10),   # 上游材料反而受益（国产替代）
        ("半导体",   -0.08),   # HBM/封装直接受损
        ("机器人",   -0.03),   # 次生影响
    ],
    "commodity": [
        ("AI材料",   +0.08),   # 大宗涨价→化工受益
        ("新能源",   +0.05),   # 油价高→新能源替代逻辑
        ("半导体",   -0.03),   # 成本上升
    ],
    "fx": [
        ("AI材料",   +0.02),   # 人民币贬值利好出口型化工
        ("半导体",   -0.05),   # 进口成本上升
    ],
    "rate": [
        ("AI材料",   +0.03),   # 利率下行利好成长
        ("半导体",   +0.05),   # 科技股受益
    ],
    "tech_breakthrough": [
        ("AI材料",   +0.12),   # 材料技术突破直接利好
        ("半导体",   +0.08),
        ("机器人",   +0.10),
    ],
    "policy_domestic": [
        ("军工电子", +0.10),   # 军工订单
        ("AI材料",   +0.05),   # 产业政策
        ("半导体",   +0.05),
    ],
}


class MacroIndustryMapper:
    """宏观事件 → 产业权重修正。"""

    def __init__(self, base_weights: dict[str, float] | None = None):
        self.base_weights = base_weights or {
            "AI材料": 1.05, "半导体": 1.00, "机器人": 0.85,
            "军工电子": 1.00, "新能源": 0.70,
        }
        self.events: list[dict[str, Any]] = []

    def load_events(self, events: list[dict[str, Any]]):
        """从 EventRegistry.breakdown() 加载活跃事件。"""
        self.events = events

    def map(self) -> dict[str, dict[str, Any]]:
        """返回每个产业的修正权重和解释。

        Returns:
            {"AI材料": {"weight": 1.12, "adjustment": +0.07, "reasons": [...]}, ...}
        """
        result: dict[str, dict[str, Any]] = {}
        for ind, base in self.base_weights.items():
            result[ind] = {"weight": base, "adjustment": 0.0, "reasons": []}

        for evt in self.events:
            cat = evt.get("category", "")
            score = evt.get("score", 0)
            label = evt.get("label", "")
            rules = EVENT_INDUSTRY_RULES.get(cat, [])
            for ind, adj in rules:
                if ind not in result:
                    result[ind] = {"weight": 1.0, "adjustment": 0.0, "reasons": []}
                # 调整 = 规则系数 × 事件归一化得分 × 衰减
                impact = adj * (abs(score) / 4.5)  # 归一化: max score ~4.5
                result[ind]["adjustment"] += impact
                if abs(impact) > 0.005:
                    result[ind]["reasons"].append({
                        "event": label,
                        "impact": round(impact, 3),
                        "direction": "up" if impact > 0 else "down",
                    })

        # Apply adjustments
        for ind, data in result.items():
            adj = data["adjustment"]
            # Cap at ±15%
            adj = max(-0.15, min(0.15, adj))
            data["weight"] = round(data["weight"] + adj, 3)
            data["adjustment"] = round(adj, 3)

        return result

    def sector_multiplier_effect(self) -> float:
        """宏观对整体行业配置的偏向。"""
        mapped = self.map()
        w_sum = sum(d["weight"] for d in mapped.values())
        base_sum = sum(self.base_weights.values())
        return round(w_sum / base_sum - 1, 4)
