"""
MarketRegime — assesses the current market risk environment.

Loads regime configuration from fenjue.yaml and returns the active regime,
position cap, and sector-weight multipliers for use by the scoring engine
and execution planner.

Currently returns a hard-coded "Risk-Neutral" regime; real-time data hooks
are reserved for future integration (e.g. VIX proxy, turnover breadth, etc.).

Usage:
    regime = MarketRegime("/opt/data/fenjue/config/fenjue.yaml")
    result = regime.assess()
    # → {"regime": "risk_neutral", "max_position": 0.6, "sector_multiplier": 1.05}
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class MarketRegime:
    """Read regime config and return the current market environment assessment."""

    def __init__(self, config_path: str | Path) -> None:
        """Load regime configuration from fenjue.yaml.

        Args:
            config_path: Absolute path to fenjue.yaml.
        """
        self._config_path = Path(config_path)
        self._regimes: dict[str, dict[str, float]] = {}
        self._load_config()

    def assess(self) -> dict[str, Any]:
        """Return the current market regime assessment.

        Returns:
            dict with keys:
                regime           — regime name (risk_on | risk_neutral | risk_off | crisis)
                max_position     — maximum position as fraction of portfolio (0.0-1.0)
                sector_multiplier — sector-weight adjustment factor
                sector_weights   — reserved; currently empty dict (hook)

        TODO (hook):
            Replace hardcoded "risk_neutral" with real-time regime detection:
            - Monitor VIX / China VIX proxy (iVX)
            - Track turnover breadth (% of stocks above 20-day MA)
            - Incorporate north-bound flow sentiment
            - Feed into a simple rule-based or ML classifier
        """
        regime_name = "risk_neutral"  # ← hardcoded default; real hook goes here
        defaults = {"max_position": 0.6, "sector_multiplier": 1.0}
        params = self._regimes.get(regime_name, defaults)

        return {
            "regime": regime_name,
            "max_position": params.get("max_position", 0.6),
            "sector_multiplier": params.get("sector_multiplier", 1.0),
            "sector_weights": {},            # hook: per-sector adjustments
        }

    # ── internal ──────────────────────────────────────────────────────────

    def _load_config(self) -> None:
        """Parse YAML and extract the regime section."""
        with open(self._config_path, encoding="utf-8") as fh:
            config = yaml.safe_load(fh) or {}
        self._regimes = config.get("regime") or {}
