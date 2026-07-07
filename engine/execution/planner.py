"""
ExecutionPlanner — generates position-building execution plans.

Reads the regime-based position caps from fenjue.yaml and produces a
step-by-step plan for entering a position, split across multiple tranches.

Usage:
    planner = ExecutionPlanner("/opt/data/fenjue/config/fenjue.yaml")
    plan = planner.get_plan("600141")
    # → [{"step": 1, "action": "initial", "position_pct": 0.20, ...}, ...]
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class ExecutionPlanner:
    """Generate staged position-building plans for a given stock code."""

    def __init__(self, config_path: str | Path) -> None:
        """Load position-strategy configuration from fenjue.yaml.

        Args:
            config_path: Absolute path to fenjue.yaml.
        """
        self._config_path = Path(config_path)
        self._regimes: dict[str, dict[str, float]] = {}
        self._load_config()

    def get_plan(self, code: str) -> list[dict[str, Any]]:
        """Return a multi-step position-building plan.

        The plan splits the max position into staggered entries so execution
        respects the current risk regime.

        Args:
            code: 6-digit stock code.

        Returns:
            List of step dicts, each with:
                step         — 1-based sequence number
                action       — 'initial' | 'add' | 'final'
                position_pct — fraction of total portfolio for this tranche
                trigger      — what triggers this step (reserved hook)
                price_range  — target price range (reserved hook)

        TODO (hook):
            - Pull real-time price range from technical analysis (support/resistance)
            - Add volatility-based sizing (ATR)
            - Integrate with MarketRegime for dynamic cap
        """
        regime_name = "risk_neutral"  # ← hardcoded; hook for real regime later
        regime = self._regimes.get(regime_name, {"max_position": 0.6})
        max_pct = float(regime.get("max_position", 0.6))

        if max_pct <= 0:
            return []

        # Default three-tranche plan: 40% / 35% / 25% of max position
        plan = [
            {
                "step": 1,
                "action": "initial",
                "position_pct": round(max_pct * 0.40, 4),
                "trigger": "entry_signal",
                "price_range": "market_open ± 1%",
            },
            {
                "step": 2,
                "action": "add",
                "position_pct": round(max_pct * 0.35, 4),
                "trigger": "confirmation",
                "price_range": "pullback_to_5ma",
            },
            {
                "step": 3,
                "action": "final",
                "position_pct": round(max_pct * 0.25, 4),
                "trigger": "breakout",
                "price_range": "new_high_close",
            },
        ]
        return plan

    # ── internal ──────────────────────────────────────────────────────────

    def _load_config(self) -> None:
        """Parse YAML and extract regime section for position caps."""
        with open(self._config_path, encoding="utf-8") as fh:
            config = yaml.safe_load(fh) or {}
        self._regimes = config.get("regime") or {}
