"""
FeedbackEngine — track predictions, validate returns, auto-correct weights.

Logs every ScoringEngine prediction to data/feedback/{date}.json, verifies
30-day returns, computes hit rates, diagnoses misses, and nudges dimension
weights via the fenjue.yaml config file.

Usage:
    engine = FeedbackEngine("/opt/data/fenjue/config/fenjue.yaml")
    engine.log_prediction("600141", score_dict)
    engine.verify("600141", current_price=18.50, date_30d_ago="2026-06-08")
    engine.hit_rate(months=3)
    engine.analyze_miss("600141")
    engine.adjust_weight("industry_trend", -0.02)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml


@dataclass
class FeedbackRecord:
    """A single prediction with optional verification fields.

    Fields filled at log time:
        code, date, predicted_score, predicted_tier, predicted_verdict,
        entry_price

    Fields filled at verify time:
        actual_return_30d, actual_return_90d, hit
    """

    code: str
    date: str                              # YYYY-MM-DD
    predicted_score: float
    predicted_tier: str                    # S | A | B
    predicted_verdict: str
    entry_price: float | None = None       # price at prediction time
    actual_return_30d: float | None = None  # filled 30d later (pct)
    actual_return_90d: float | None = None
    hit: bool | None = None
    notes: str = ""


class FeedbackEngine:
    """Log predictions to JSON, verify against market returns, adjust weights."""

    SIX_DIMS = [
        "industry_trend", "capital_flow", "institutional",
        "margin", "quantitative", "expectation",
    ]

    def __init__(self, config_path: str | Path) -> None:
        self._config_path = Path(config_path)
        # data/feedback/ relative to the fenjue project root
        self._feedback_dir = (
            Path(__file__).resolve().parent.parent / "data" / "feedback"
        )
        self._feedback_dir.mkdir(parents=True, exist_ok=True)

    # ── public API ────────────────────────────────────────────────────────

    def log_prediction(
        self, code: str, score_dict: dict[str, Any],
    ) -> FeedbackRecord:
        """Save a prediction to ``data/feedback/{date}.json``.

        Args:
            code:       6-digit stock code (e.g. ``"600141"``).
            score_dict: output of ``ScoringEngine.score_stock()``.
                        May additionally contain ``price`` for the entry price.

        Returns:
            The ``FeedbackRecord`` that was persisted.
        """
        today = date.today().isoformat()
        record = FeedbackRecord(
            code=code,
            date=today,
            predicted_score=float(score_dict.get("total", 0.0)),
            predicted_tier=str(score_dict.get("tier", "B")),
            predicted_verdict=str(score_dict.get("verdict", "")),
            entry_price=(
                float(score_dict["price"])
                if score_dict.get("price") is not None
                else None
            ),
        )
        self._append_record(record)
        return record

    def verify(
        self,
        code: str,
        current_price: float,
        date_30d_ago: str,
        *,
        entry_price: float | None = None,
    ) -> FeedbackRecord | None:
        """Compare a 30-day-old prediction with actual performance.

        Finds the first *unverified* record for *code* on *date_30d_ago*,
        computes ``actual_return_30d`` as percentage gain/loss, and sets
        ``hit`` according to whether the signal direction was correct.

        **Hit rules:**

        * Predicted S / A (bullish) → hit when return > 0.
        * Predicted B (neutral / avoid) → hit when return ≤ 0.

        Args:
            code:          stock code.
            current_price: today's price.
            date_30d_ago:  ISO date string (``YYYY-MM-DD``) of the prediction.
            entry_price:   override entry price; uses record's ``entry_price``
                           when omitted.

        Returns:
            Updated ``FeedbackRecord``, or ``None`` if no matching unverified
            prediction exists.
        """
        records = self._load_records(date_30d_ago)
        for rec in records:
            if rec.code != code:
                continue
            if rec.actual_return_30d is not None:
                continue  # already verified

            price = entry_price or rec.entry_price
            if price and price > 0:
                rec.actual_return_30d = round(
                    (current_price - price) / price * 100, 2
                )

            # ── hit determination ──────────────────────────────────
            if rec.actual_return_30d is not None:
                if rec.predicted_tier in ("S", "A"):
                    rec.hit = rec.actual_return_30d > 0
                else:
                    rec.hit = rec.actual_return_30d <= 0

            self._save_records(date_30d_ago, records)
            return rec
        return None

    def hit_rate(self, months: int = 3) -> dict[str, Any]:
        """Compute hit-rate statistics over the last *months*.

        Args:
            months: lookback window (default 3).

        Returns:
            dict with:

            * ``total_predictions`` — all records in window
            * ``verified``         — records with ``hit is not None``
            * ``hits``             — verified records where ``hit is True``
            * ``hit_rate``         — hits / verified (``None`` when 0 verified)
            * ``by_tier``          — per-tier breakdown
        """
        cutoff = date.today() - timedelta(days=months * 30)
        all_records: list[FeedbackRecord] = []
        for fpath in sorted(self._feedback_dir.glob("*.json")):
            try:
                file_date = date.fromisoformat(fpath.stem)
            except ValueError:
                continue
            if file_date >= cutoff:
                all_records.extend(self._load_records(fpath.stem))

        verified = [r for r in all_records if r.hit is not None]
        hits = [r for r in verified if r.hit]

        by_tier: dict[str, dict[str, int]] = {}
        for r in verified:
            tier = r.predicted_tier
            if tier not in by_tier:
                by_tier[tier] = {"total": 0, "hits": 0}
            by_tier[tier]["total"] += 1
            if r.hit:
                by_tier[tier]["hits"] += 1

        return {
            "total_predictions": len(all_records),
            "verified": len(verified),
            "hits": len(hits),
            "hit_rate": (
                round(len(hits) / len(verified), 4) if verified else None
            ),
            "by_tier": {
                tier: {
                    "total": v["total"],
                    "hits": v["hits"],
                    "rate": (
                        round(v["hits"] / v["total"], 4)
                        if v["total"] else None
                    ),
                }
                for tier, v in by_tier.items()
            },
        }

    def analyze_miss(self, code: str) -> dict[str, Any]:
        """Diagnose why predictions for *code* missed.

        Categories:

        * **产业逻辑** — strong conviction (S/A) but fell > 5%
        * **时机判断** — direction correct but entry too early
        * **估值判断** — rated B but stock surged > 10%

        Args:
            code: stock code.

        Returns:
            dict with ``miss_count``, ``reasons``, ``suggested_fixes``.
        """
        all_records: list[FeedbackRecord] = []
        for fpath in sorted(self._feedback_dir.glob("*.json")):
            all_records.extend(self._load_records(fpath.stem))

        misses = [r for r in all_records if r.code == code and r.hit is False]
        reasons: list[str] = []

        for r in misses:
            ret = r.actual_return_30d
            if ret is None:
                continue
            if r.predicted_tier in ("S", "A") and ret < -5:
                reasons.append(
                    f"[{r.date}] 产业逻辑判断错误 — 看好但跌{abs(ret):.1f}%"
                )
            elif r.predicted_tier in ("S", "A") and ret < 0:
                reasons.append(
                    f"[{r.date}] 时机判断偏差 — 方向对但入场过早 (跌{abs(ret):.1f}%)"
                )
            elif r.predicted_tier == "B" and ret > 10:
                reasons.append(
                    f"[{r.date}] 估值判断保守 — 错过{ret:.1f}%涨幅"
                )
            else:
                reasons.append(
                    f"[{r.date}] 综合偏差 — 多维度信号失真 (收益{ret:+.1f}%)"
                )

        return {
            "code": code,
            "miss_count": len(misses),
            "reasons": reasons,
            "suggested_fixes": self._suggest_fixes(misses),
        }

    def adjust_weight(
        self, dimension: str, correction: float,
    ) -> dict[str, float]:
        """Nudge one dimension's weight by a small delta, re-normalise others.

        Reads current weights from ``fenjue.yaml``, applies *correction*
        (typically ±0.02), scales remaining dimensions proportionally so the
        sum stays at 1.0, then writes back.

        Args:
            dimension:  one of the six dimension keys.
            correction: adjustment in ``[-0.05, 0.05]``.

        Returns:
            New weights dict.

        Raises:
            ValueError: unknown dimension or correction out of bounds.
        """
        if dimension not in self.SIX_DIMS:
            raise ValueError(
                f"Unknown dimension '{dimension}'. "
                f"Must be one of: {', '.join(self.SIX_DIMS)}"
            )
        if not (-0.05 <= correction <= 0.05):
            raise ValueError("correction must be in [-0.05, 0.05]")

        current = self._read_weights()
        current[dimension] = round(current[dimension] + correction, 4)

        # Re-normalise so sum == 1.0
        other_dims = [d for d in self.SIX_DIMS if d != dimension]
        other_sum = sum(current[d] for d in other_dims)
        if other_sum > 0:
            scale = (1.0 - current[dimension]) / other_sum
            for d in other_dims:
                current[d] = round(current[d] * scale, 4)

        self._write_weights(current)
        return current

    # ── internal ──────────────────────────────────────────────────────────

    def _append_record(self, record: FeedbackRecord) -> None:
        records = self._load_records(record.date)
        records.append(record)
        self._save_records(record.date, records)

    def _load_records(self, date_str: str) -> list[FeedbackRecord]:
        fpath = self._feedback_dir / f"{date_str}.json"
        if not fpath.exists():
            return []
        data = json.loads(fpath.read_text(encoding="utf-8"))
        return [FeedbackRecord(**item) for item in data]

    def _save_records(
        self, date_str: str, records: list[FeedbackRecord],
    ) -> None:
        fpath = self._feedback_dir / f"{date_str}.json"
        fpath.write_text(
            json.dumps(
                [asdict(r) for r in records],
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

    def _read_weights(self) -> dict[str, float]:
        with open(self._config_path, encoding="utf-8") as fh:
            config = yaml.safe_load(fh) or {}
        return dict(config.get("scoring", {}).get("weights", {}))

    def _write_weights(self, weights: dict[str, float]) -> None:
        config_text = self._config_path.read_text(encoding="utf-8")
        config = yaml.safe_load(config_text) or {}
        config.setdefault("scoring", {})["weights"] = weights

        with open(self._config_path, "w", encoding="utf-8") as fh:
            yaml.dump(
                config, fh, allow_unicode=True,
                default_flow_style=False, sort_keys=False,
            )

    @staticmethod
    def _suggest_fixes(
        misses: list[FeedbackRecord],
    ) -> list[str]:
        """Generate weight-adjustment suggestions from miss patterns."""
        suggestions: list[str] = []
        has_industry = any(
            r.predicted_tier in ("S", "A")
            and r.actual_return_30d is not None
            and r.actual_return_30d < -5
            for r in misses
        )
        has_timing = any(
            r.predicted_tier in ("S", "A")
            and r.actual_return_30d is not None
            and -5 <= r.actual_return_30d < 0
            for r in misses
        )
        has_missed_upside = any(
            r.predicted_tier == "B"
            and r.actual_return_30d is not None
            and r.actual_return_30d > 10
            for r in misses
        )
        if has_industry:
            suggestions.append(
                "下调 industry_trend 权重 (-0.02) — 产业逻辑信号过强导致误判"
            )
        if has_timing:
            suggestions.append(
                "调整 capital_flow 或 expectation 权重 — 时机判断需优化"
            )
        if has_missed_upside:
            suggestions.append(
                "提高 quantitative 权重 (+0.02) — 量化信号未充分捕捉趋势"
            )
        if not suggestions:
            suggestions.append("样本不足，继续积累数据后分析")
        return suggestions
