"""
FenJue Decision Engine — modular scoring, industry mapping, market regime,
and execution planning for the FenJue investment research lab.

Subpackages:
    scoring   — Six-dimensional stock scoring (ScoringEngine)
    mapping   — Industry/supply-chain mapping (IndustryMapper)
    regime    — Market regime assessment (MarketRegime)
    execution — Position-building execution plans (ExecutionPlanner)
"""

from engine.scoring.scorer import ScoringEngine
from engine.mapping.industry import IndustryMapper
from engine.regime.market import MarketRegime
from engine.execution.planner import ExecutionPlanner

__all__ = [
    "ScoringEngine",
    "IndustryMapper",
    "MarketRegime",
    "ExecutionPlanner",
]
