"""
IndustryMapper — maps stock codes to industry themes, supply chains, and materials.

Loads the industry_tree from fenjue.yaml and builds a reverse index so every stock
code can be traced back to its theme → chain → material path.  This is the
foundation for the "industry_trend" dimension in the scoring engine.

Usage:
    mapper = IndustryMapper("/opt/data/fenjue/config/fenjue.yaml")
    chains = mapper.map_chain("600141")
    # → [{"theme": "AI材料", "chain": "磷化铟衬底", "material": "高纯磷", "weight": 1.05}]

    score = mapper.get_industry_score("600141")    # → 9  (0-10)
    weight = mapper.get_weight("AI材料")             # → 1.05
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


# ── heat level → base score mapping ──────────────────────────────────────────
_HEAT_SCORE: dict[str, int] = {
    "★★★★★": 10,
    "★★★★☆": 8,
    "★★★☆☆": 6,
    "★★☆☆☆": 4,
    "★☆☆☆☆": 2,
}


class IndustryMapper:
    """Load the YAML industry_tree and provide stock-code → industry lookups."""

    def __init__(self, config_path: str | Path) -> None:
        """Load fenjue.yaml and build the code → chain reverse index.

        Args:
            config_path: Absolute path to fenjue.yaml.
        """
        self._config_path = Path(config_path)
        self._tree: dict[str, Any] = {}
        self._code_index: dict[str, list[dict[str, Any]]] = {}
        self._load_tree()
        self._build_index()

    # ── public API ────────────────────────────────────────────────────────

    def load_tree(self) -> dict[str, Any]:
        """Return the raw industry_tree dict from YAML."""
        return self._tree

    def map_chain(self, code: str) -> list[dict[str, Any]]:
        """Return all supply-chain paths for a stock code.

        Each entry: {theme, chain, material, weight}.
        A code may appear under multiple chains or materials.
        """
        return self._code_index.get(code, [])

    def get_industry_score(self, code: str) -> int:
        """Return the industry-trend score (0-10) for a stock code.

        Derived from the theme's heat level (★ count) multiplied by its
        weight factor, then clamped to [0, 10].
        """
        entries = self.map_chain(code)
        if not entries:
            return 0
        # Use the first theme's score (most codes appear under one theme).
        theme = entries[0]["theme"]
        theme_info = self._tree.get(theme, {})
        heat = theme_info.get("heat", "")
        weight = theme_info.get("weight", 1.0)
        base = _HEAT_SCORE.get(heat, 5)
        raw = round(base * weight)
        return max(0, min(10, raw))

    def get_weight(self, theme: str) -> float:
        """Return the sector weight multiplier for a theme."""
        theme_info = self._tree.get(theme, {})
        return float(theme_info.get("weight", 1.0))

    # ── internal ──────────────────────────────────────────────────────────

    def _load_tree(self) -> None:
        """Parse the YAML config and extract the industry_tree section."""
        with open(self._config_path, encoding="utf-8") as fh:
            config = yaml.safe_load(fh) or {}
        self._tree = config.get("industry_tree") or {}

    def _build_index(self) -> None:
        """Build reverse mapping: stock code → [{theme, chain, material, weight}]."""
        self._code_index.clear()
        for theme_name, theme_info in self._tree.items():
            weight = theme_info.get("weight", 1.0)
            chains = theme_info.get("chains") or {}
            for chain_name, materials in chains.items():
                for material_name, codes in (materials or {}).items():
                    for code in codes:
                        # Normalise to string — YAML integers become str keys
                        code_str = str(code)
                        entry = {
                            "theme": theme_name,
                            "chain": chain_name,
                            "material": material_name,
                            "weight": weight,
                        }
                        self._code_index.setdefault(code_str, []).append(entry)
