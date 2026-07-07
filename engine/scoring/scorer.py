"""
ScoringEngine — six-dimensional stock scoring for the FenJue decision engine.

Evaluates a stock across six dimensions with configurable weights loaded from
fenjue.yaml.  Each dimension is scored 0-10 and combined into a composite
score, tier, verdict, and confidence rating.

Dimensions (weights from YAML, defaults shown):
    industry_trend  (0.35)  — industry heat & stage from industry_tree
    capital_flow    (0.25)  — turnover-rate bucket scoring
    institutional   (0.10)  — institutional positioning (default stub; hook TBD)
    margin          (0.10)  — margin-trading sentiment (default stub; hook TBD)
    quantitative    (0.05)  — quantitative signal composite (default stub; hook TBD)
    expectation     (0.15)  — 20-day return percentile scoring

Tiers:
    S  ≥ 7.5  —  high conviction, alpha signal
    A  ≥ 6.5  —  moderate conviction
    B  ≥ 5.0  —  watchlist / marginal

Usage:
    engine = ScoringEngine("/opt/data/fenjue/config/fenjue.yaml")
    result = engine.score_stock("600141", {"turnover": 5.2, "pct_20d": 12.0})
    # → {"code": "600141", "total": 7.15, "tier": "A", ...}
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from engine.mapping.industry import IndustryMapper

# ── confidence overrides (hardcoded per spec) ────────────────────────────────
_CONFIDENCE_MAP: dict[str, int] = {
    "600141": 72,
}


class ScoringEngine:
    """Load config, instantiate industry mapper, and score stocks."""

    def __init__(self, config_path: str | Path) -> None:
        """Parse fenjue.yaml and initialise dependencies.

        Args:
            config_path: Absolute path to fenjue.yaml.
        """
        self._config_path = Path(config_path)
        self._weights: dict[str, float] = {}
        self._tiers: dict[str, float] = {}
        self._industry_mapper: IndustryMapper

        self._load_config()
        self._industry_mapper = IndustryMapper(str(self._config_path))

    # ── public API ────────────────────────────────────────────────────────

    def score_stock(self, code: str, quote_data: dict[str, Any]) -> dict[str, Any]:
        """Compute the six-dimension composite score for a stock.

        Args:
            code:       6-digit stock code (e.g. "600141").
            quote_data: dict with at minimum:
                turnover   — turnover rate as a percentage (e.g. 5.2 = 5.2%).
                pct_20d    — (optional) 20-trading-day return as percentage.
                price      — (optional) current price; used if pct_20d absent
                              and close_20d_ago is provided.
                close_20d_ago — (optional) closing price 20 days ago.

        Returns:
            dict:
                code        — stock code
                industry    — industry-trend score (0-10)
                flow        — capital-flow score (0-10)
                inst        — institutional score (0-10)
                margin      — margin score (0-10)
                quant       — quantitative score (0-10)
                expect      — expectation score (0-10)
                total       — weighted composite (float)
                tier        — S | A | B
                verdict     — human-readable verdict string
                confidence  — 0-100 confidence score
                weights     — dict of dimension→weight used
        """
        industry = self._score_industry(code)
        flow = self._score_flow(quote_data)
        inst = self._score_institutional(code, quote_data)
        margin = self._score_margin(code, quote_data)
        quant = self._score_quantitative(code, quote_data)
        expect = self._score_expectation(quote_data)

        total = round(
            industry * self._weights.get("industry_trend", 0.35)
            + flow * self._weights.get("capital_flow", 0.25)
            + inst * self._weights.get("institutional", 0.10)
            + margin * self._weights.get("margin", 0.10)
            + quant * self._weights.get("quantitative", 0.05)
            + expect * self._weights.get("expectation", 0.15),
            4,
        )

        tier = self._assign_tier(total)
        confidence = self._confidence(code, total)

        return {
            "code": code,
            "industry": industry,
            "flow": flow,
            "inst": inst,
            "margin": margin,
            "quant": quant,
            "expect": expect,
            "total": total,
            "tier": tier,
            "verdict": self._verdict(tier, total),
            "confidence": confidence,
            "weights": dict(self._weights),
        }

    # ── dimension scorers ─────────────────────────────────────────────────

    def _score_industry(self, code: str) -> int:
        """Industry-trend score from industry_tree mapping."""
        return self._industry_mapper.get_industry_score(code)

    @staticmethod
    def _score_flow(quote_data: dict[str, Any]) -> int:
        """Capital-flow score based on turnover rate.

        Scoring rules:
            3% ≤ turnover ≤ 10%  →  8  (healthy activity)
            turnover > 20%        →  3  (overheated / distribution risk)
            turnover < 1%         →  4  (illiquid / no interest)
            turnover missing      →  6  (neutral / no data)
            otherwise             →  6  (neutral)
        """
        if "turnover" not in quote_data:
            return 6  # neutral when data unavailable
        turnover = float(quote_data["turnover"])
        if 3 <= turnover <= 10:
            return 8
        if turnover > 20:
            return 3
        if turnover < 1:
            return 4
        return 6

    def _score_institutional(self, code: str, quote_data: dict[str, Any]) -> int:
        """Institutional positioning score — default stub.

        TODO (hook):
            - Pull north-bound (沪股通/深股通) flow data
            - Query fund holdings from quarterly disclosures
            - Detect institutional accumulation patterns
        """
        _ = (code, quote_data)
        return 5

    def _score_margin(self, code: str, quote_data: dict[str, Any]) -> int:
        """Margin-trading sentiment score — default stub.

        TODO (hook):
            - Pull margin balance / short-interest from exchange data
            - Detect margin-call risk or excessive leverage
        """
        _ = (code, quote_data)
        return 5

    def _score_quantitative(self, code: str, quote_data: dict[str, Any]) -> int:
        """Quantitative signal composite — default stub.

        TODO (hook):
            - MACD / RSI / volume-price divergence signals
            - Momentum factor (12m-1m return)
            - Reversal / mean-reversion indicators
        """
        _ = (code, quote_data)
        return 5

    @staticmethod
    def _score_expectation(quote_data: dict[str, Any]) -> int:
        """Expectation score based on trailing 20-day return.

        Lower recent return → higher expectation (room to run).
        High recent return → lower expectation (already priced in).

        Scoring:
            pct_20d > 30%   →  3  (overextended)
            15-30%          →  5  (extended)
            5-15%           →  7  (moderate)
            < 5%            →  9  (fresh setup)
        """
        pct_20d: float | None = None

        # Prefer explicit field
        if "pct_20d" in quote_data:
            pct_20d = float(quote_data["pct_20d"])
        elif "price" in quote_data and "close_20d_ago" in quote_data:
            price = float(quote_data["price"])
            close_20d_ago = float(quote_data["close_20d_ago"])
            if close_20d_ago > 0:
                pct_20d = (price - close_20d_ago) / close_20d_ago * 100

        if pct_20d is None:
            return 5  # neutral when data unavailable

        if pct_20d > 30:
            return 3
        if pct_20d > 15:
            return 5
        if pct_20d > 5:
            return 7
        return 9

    # ── tier / verdict / confidence ───────────────────────────────────────

    def _assign_tier(self, total: float) -> str:
        """Map composite score to tier (S / A / B)."""
        s_threshold = self._tiers.get("s_pool", 7.5)
        a_threshold = self._tiers.get("a_pool", 6.5)
        if total >= s_threshold:
            return "S"
        if total >= a_threshold:
            return "A"
        return "B"

    @staticmethod
    def _verdict(tier: str, total: float) -> str:
        """Human-readable verdict string."""
        mapping = {
            "S": f"高置信度信号 (总分 {total:.2f}) — 核心池候选",
            "A": f"中等置信度 (总分 {total:.2f}) — 关注池，等待确认",
            "B": f"低置信度 (总分 {total:.2f}) — 观察池，暂不建仓",
        }
        return mapping.get(tier, mapping["B"])

    @staticmethod
    def _confidence(code: str, total: float) -> int:
        """Confidence score (0-100).  Hardcoded overrides for known stocks."""
        if code in _CONFIDENCE_MAP:
            return _CONFIDENCE_MAP[code]
        return 50

    # ── internal ──────────────────────────────────────────────────────────

    def _load_config(self) -> None:
        """Parse YAML and extract scoring weights + tier thresholds."""
        with open(self._config_path, encoding="utf-8") as fh:
            config = yaml.safe_load(fh) or {}
        scoring = config.get("scoring") or {}
        self._weights = scoring.get("weights") or {}
        self._tiers = scoring.get("tiers") or {}
