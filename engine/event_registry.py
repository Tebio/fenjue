"""
Macro Event Registry V2.5 — 事件自动衰减，不再人工打分。
每个事件有：类别权重 × 严重度 × 时间衰减 = 自动评分。

使用:
    reg = EventRegistry()
    reg.add("中东冲突", category="geopolitics", severity=3, ttl_days=30)
    reg.tick()  # 每天调用一次，衰减所有事件
    reg.active_events  # → [("中东冲突", -2.7, "day 1/30"), ...]
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar


# ── category config ──────────────────────────────────────────

@dataclass
class Event:
    """单个宏观事件。"""

    # 类别方向映射：-1=利空, +1=利好, 0=双向/自动判断
    CATEGORY_DIRECTION: ClassVar[dict[str, int]] = {
        "tech_breakthrough": 1,
        "policy_domestic": 1,
        "seasonal": 1,
        "geopolitics": -1,
        "inflation": -1,
        "rate_hike": -1,
        "supply_shock": -1,
        "demand_shock": -1,
        "ai_capex": 0,
        "rate": 0,
        "fx": 0,
        "supply_chain": 0,
        "policy_foreign": 0,
        "commodity": 0,
    }

    label: str
    category: str
    severity: int          # 1=低 2=中 3=高
    ttl_days: int          # 过期天数
    direction: int = 0     # -1=利空 0=自动判断/双向 +1=利好
    created: datetime = field(default_factory=datetime.now)

    @property
    def age_days(self) -> float:
        return (datetime.now() - self.created).total_seconds() / 86400

    @property
    def decay(self) -> float:
        if self.ttl_days <= 0:
            return 1.0
        import math
        return math.exp(-self.age_days * 5 / self.ttl_days)

    @property
    def alive(self) -> bool:
        return self.age_days < self.ttl_days or self.decay > 0.01

    def score(self, category_weights: dict[str, float]) -> float:
        if self.direction != 0:
            d = self.direction
        else:
            d = self.CATEGORY_DIRECTION.get(self.category, 0)
        w = category_weights.get(self.category, 0.5)
        return d * w * (self.severity / 3.0) * self.decay * 3


CATEGORY_WEIGHTS = {
    "geopolitics":      1.5,   # 地缘政治——影响最大
    "ai_capex":         1.2,   # AI 资本开支
    "inflation":        0.8,   # 通胀/油价
    "rate":             0.8,   # 利率/美债
    "fx":               0.6,   # 汇率
    "supply_chain":     0.9,   # 供应链
    "policy_domestic":  0.7,   # 国内政策
    "policy_foreign":   0.6,   # 海外政策
    "tech_breakthrough": 1.0,  # 技术突破
    "seasonal":         0.3,   # 季节性因素
    "commodity":        0.8,   # 大宗商品
}


class EventRegistry:
    """宏观事件注册表，自动时间衰减。"""

    def __init__(self):
        self.events: list[Event] = []
        self._tick_count: int = 0

    def add(self, label: str, category: str, severity: int = 2, ttl_days: int = 14, direction: int = 0):
        """注册一个新事件。"""
        self.events.append(Event(label=label, category=category,
                                  severity=severity, ttl_days=ttl_days, direction=direction))

    def tick(self) -> float:
        """每日调用，清理过期事件，返回当前宏观总分。"""
        self._tick_count += 1
        self.events = [e for e in self.events if e.alive]
        return self.net_score()

    def net_score(self) -> float:
        """当前活跃事件的加权总分。"""
        return sum(e.score(CATEGORY_WEIGHTS) for e in self.events)

    def breakdown(self) -> list[dict[str, Any]]:
        """当前活跃事件的明细。"""
        return [
            {
                "label": e.label,
                "category": e.category,
                "severity": e.severity,
                "age_days": round(e.age_days, 1),
                "ttl_days": e.ttl_days,
                "decay": round(e.decay, 3),
                "score": round(e.score(CATEGORY_WEIGHTS), 2),
            }
            for e in self.events
        ]

    def regime_impact(self) -> dict[str, Any]:
        """返回对 MarketRegime 的修正建议。"""
        net = self.net_score()
        if net > 1.0:
            override = "risk_on"
            cap_adj = 1.0
            note = "宏观显著利好"
        elif net > -0.5:
            override = None
            cap_adj = 1.0
            note = "宏观中性"
        elif net > -2.0:
            override = "risk_off"
            cap_adj = 0.65
            note = "宏观偏冷，收紧仓位"
        else:
            override = "crisis"
            cap_adj = 0.35
            note = "宏观危机，避险为主"

        return {
            "net_score": round(net, 2),
            "regime_override": override,
            "position_cap_adj": cap_adj,
            "note": note,
            "active_count": len(self.events),
        }


# ── today's registry (2026-07-08) ────────────────────────────

def todays_registry() -> EventRegistry:
    """今日事件注册表。双向事件需手动指定 direction。"""
    reg = EventRegistry()
    reg.add("中东冲突升级",       "geopolitics",       severity=3, ttl_days=30)           # auto: -1
    reg.add("韩股暴跌(芯片拖累)", "ai_capex",          severity=2, ttl_days=14, direction=-1)
    reg.add("AI CapEx 消化期",    "ai_capex",          severity=2, ttl_days=21, direction=-1)
    reg.add("油价上涨(战争驱动)", "commodity",         severity=2, ttl_days=7,  direction=-1)
    reg.add("美元走强",           "fx",                severity=1, ttl_days=14, direction=-1)
    reg.add("10年美债回落",       "rate",              severity=1, ttl_days=10, direction=+1)
    reg.add("AI 上游材料国产替代", "tech_breakthrough", severity=2, ttl_days=90)           # auto: +1
    reg.add("军工订单预期上升",    "policy_domestic",   severity=1, ttl_days=30)           # auto: +1
    return reg
