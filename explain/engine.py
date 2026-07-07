"""
ExplainEngine — traceable score attribution for FenJue's six-dimension scoring.

Every dimension in a composite score is broken down into:
    - raw score (0-10)
    - weight in the formula
    - weighted contribution (= raw × weight)
    - source text explaining how the score was derived

This makes every score auditable, debuggable, and human-readable.

Usage:
    explainer = ExplainEngine()
    result = explainer.explain("600141", score_dict)
    # → {"total": 6.85, "breakdown": [{...}, ...]}
"""

from __future__ import annotations

from typing import Any


class ExplainEngine:
    """Generate structured explanations for a stock's composite score."""

    def explain(self, code: str, score_dict: dict[str, Any]) -> dict[str, Any]:
        """Build a traceable breakdown of the composite score.

        Args:
            code:       6-digit stock code.
            score_dict: Output from ScoringEngine.score_stock(), expected keys:
                        industry, flow, inst, margin, quant, expect, total,
                        weights (dict of yaml_key→weight), tier, verdict, confidence.

        Returns:
            dict with keys:
                total     — composite score (float)
                breakdown — list of {dimension, score, weight, contribution, source}
        """
        weights: dict[str, float] = score_dict.get("weights", {})

        # Map output dimension keys → YAML weight keys
        _WEIGHT_KEY: dict[str, str] = {
            "industry": "industry_trend",
            "flow":     "capital_flow",
            "inst":     "institutional",
            "margin":   "margin",
            "quant":    "quantitative",
            "expect":   "expectation",
        }

        dimensions = [
            ("industry", "产业趋势", "industry_tree YAML → heat × weight"),
            ("flow",     "资金流向", "turnover rate bucket scoring"),
            ("inst",     "机构动向", "default placeholder; real hook TBD"),
            ("margin",   "融资情绪", "default placeholder; real hook TBD"),
            ("quant",    "量化信号", "default placeholder; real hook TBD"),
            ("expect",   "预期兑现", "20-day return percentile scoring"),
        ]

        breakdown: list[dict[str, Any]] = []
        for key, label, source in dimensions:
            raw = int(score_dict.get(key, 0))  # scores are integers 0-10
            weight = float(weights.get(_WEIGHT_KEY.get(key, key), 0))
            contribution = round(raw * weight, 4)
            breakdown.append(
                {
                    "dimension": key,
                    "label": label,
                    "score": raw,
                    "weight": weight,
                    "contribution": contribution,
                    "source": source,
                }
            )

        return {
            "total": score_dict.get("total", 0),
            "tier": score_dict.get("tier", "B"),
            "verdict": score_dict.get("verdict", ""),
            "confidence": score_dict.get("confidence", 50),
            "breakdown": breakdown,
        }
