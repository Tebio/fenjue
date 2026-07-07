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

from engine.regime.market import MarketRegime


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

    def get_plan(
        self, code: str, regime: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Return a multi-step position-building plan.

        Position sizing is driven by the current market regime. Each regime
        maps to a fixed three-tranche allocation (or an empty list for crisis).

        Args:
            code:         6-digit stock code.
            regime:       Optional pre-computed regime dict from MarketRegime.assess().
                          If omitted, MarketRegime is called internally.

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
        """
        if regime is None:
            mr = MarketRegime(str(self._config_path))
            regime = mr.assess()

        regime_name: str = regime.get("regime", "risk_neutral")

        # ── per-regime tranche allocation ──────────────────────────────
        # Each tuple is (step, action, position_pct, trigger, price_range)
        _TRANCHES: dict[str, list[tuple[int, str, float, str, str]]] = {
            "risk_on": [
                (1, "initial", 0.40, "entry_signal", "market_open ± 1%"),
                (2, "add", 0.30, "confirmation", "pullback_to_5ma"),
                (3, "final", 0.30, "breakout", "new_high_close"),
            ],
            "risk_neutral": [
                (1, "initial", 0.30, "entry_signal", "market_open ± 1%"),
                (2, "add", 0.20, "confirmation", "pullback_to_5ma"),
                (3, "final", 0.10, "breakout", "new_high_close"),
            ],
            "risk_off": [
                (1, "initial", 0.15, "entry_signal", "market_open ± 1%"),
                (2, "add", 0.10, "confirmation", "pullback_to_5ma"),
                (3, "final", 0.05, "breakout", "new_high_close"),
            ],
            "crisis": [],
        }

        tranches = _TRANCHES.get(regime_name, _TRANCHES["risk_neutral"])

        plan: list[dict[str, Any]] = []
        for step, action, pct, trigger, price_range in tranches:
            plan.append({
                "step": step,
                "action": action,
                "position_pct": pct,
                "trigger": trigger,
                "price_range": price_range,
            })
        return plan

    # ── internal ──────────────────────────────────────────────────────────

    def _load_config(self) -> None:
        """Parse YAML and extract regime section for position caps."""
        with open(self._config_path, encoding="utf-8") as fh:
            config = yaml.safe_load(fh) or {}
        self._regimes = config.get("regime") or {}
