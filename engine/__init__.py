"""
FenJue Decision Engine — modular scoring, industry mapping, market regime,
moneyflow analysis, and execution planning for the FenJue investment research lab.

Subpackages:
    scoring   — Six-dimensional stock scoring (ScoringEngine)
    mapping   — Industry/supply-chain mapping (IndustryMapper)
    regime    — Market regime assessment (MarketRegime)
    moneyflow — Margin trading data & money flow analysis (MarginTracker)
    execution — Position-building execution plans (ExecutionPlanner)
"""

from engine.scoring.scorer import ScoringEngine
from engine.moneyflow import MoneyFlowEngine
from engine.mapping.industry import IndustryMapper
from engine.regime.market import MarketRegime
from engine.moneyflow.margin import MarginTracker
from engine.execution.planner import ExecutionPlanner

__all__ = [
    "ScoringEngine",
    "MoneyFlowEngine",
    "IndustryMapper",
    "MarketRegime",
    "MarginTracker",
    "ExecutionPlanner",
]
