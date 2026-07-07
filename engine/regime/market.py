"""
MarketRegime — assesses the current market risk environment.

Loads regime configuration from fenjue.yaml and returns the active regime,
position cap, and sector-weight multipliers for use by the scoring engine
and execution planner.

Usage:
    regime = MarketRegime("/opt/data/fenjue/config/fenjue.yaml")
    result = regime.assess(tier_counts={"S": 4, "A": 6, "B": 12})
    # → {"regime": "risk_on", "max_position": 1.0, "sector_multiplier": 1.15, ...}
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


class MarketRegime:
    """Read regime config and return the current market environment assessment."""

    # ── regime-detection thresholds ───────────────────────────────────────
    # S池>=3 或 A池>=8        → risk_on
    # A池>=3 或 S池>=1        → risk_neutral
    # 有数据但不够任一门槛      → risk_off
    # 完全没有数据             → risk_neutral (default)
    # ───────────────────────────────────────────────────────────────────────

    def __init__(self, config_path: str | Path) -> None:
        """Load regime configuration from fenjue.yaml.

        Args:
            config_path: Absolute path to fenjue.yaml.
        """
        import yaml

        self._config_path = Path(config_path)
        with open(self._config_path, encoding="utf-8") as fh:
            config = yaml.safe_load(fh) or {}
        self._regimes: dict[str, dict[str, float]] = config.get("regime") or {}

    def assess(self, tier_counts: dict[str, int] | None = None) -> dict[str, Any]:
        """Return the current market regime assessment based on daily tier counts.

        Args:
            tier_counts: Dict mapping tier letter ("S"/"A"/"B"/…) →
                         count of stocks in that tier on the latest scoring date.
                         If None or empty, defaults to risk_neutral.

        Returns:
            dict with keys:
                regime            — regime name (risk_on | risk_neutral | risk_off | crisis)
                max_position      — maximum position as fraction of portfolio (0.0–1.0)
                sector_multiplier — sector-weight adjustment factor
                tier_counts       — the input tier_counts (echoed for API consumers)
                capital_style     — aggressive | balanced | defensive
        """
        tier_counts = tier_counts or {}

        s_count = tier_counts.get("S", 0)
        a_count = tier_counts.get("A", 0)

        # Threshold-based regime detection (single source of truth)
        if s_count >= 3 or a_count >= 8:
            regime_name = "risk_on"
        elif a_count >= 3 or s_count >= 1:
            regime_name = "risk_neutral"
        elif any(tier_counts.values()):
            regime_name = "risk_off"
        else:
            regime_name = "risk_neutral"  # default when no data

        params = self._regimes.get(regime_name, {"max_position": 0.6, "sector_multiplier": 1.0})

        return {
            "regime": regime_name,
            "max_position": params.get("max_position", 0.6),
            "sector_multiplier": params.get("sector_multiplier", 1.0),
            "tier_counts": dict(tier_counts),
            "capital_style": self._capital_style(regime_name),
        }

    # ── internal ──────────────────────────────────────────────────────────

    @staticmethod
    def _capital_style(regime_name: str) -> str:
        """Map regime name to capital-allocation style."""
        return {
            "risk_on": "aggressive",
            "risk_neutral": "balanced",
            "risk_off": "defensive",
            "crisis": "defensive",
        }.get(regime_name, "balanced")
