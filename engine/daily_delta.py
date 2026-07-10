#!/usr/bin/env python3
"""Daily Delta — compare today vs yesterday six-dimensional scores.

Reads score snapshots from research/data/scores/, builds a code→name
lookup from pool files, and computes per-stock score changes across the
six dimensions: industry, flow, institutional, margin, quantitative,
expectation.

Usage as module:
    from engine.daily_delta import DailyDelta
    delta = DailyDelta()
    report = delta.generate(delta_date="2026-07-09")
    print(report)

Usage as CLI:
    python3 engine/daily_delta.py [YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

# Project root relative to this file: engine/daily_delta.py → fenjue/
ROOT = Path(__file__).resolve().parent.parent
SCORES_DIR = ROOT / "research" / "data" / "scores"
REPORTS_DIR = ROOT / "reports"

# Hardcoded fallback code→name map — populated from fenjue.yaml industry_tree
# and project dashboards. When a stock name can't be resolved from pool files
# or the scores JSON itself, this mapping is used as a last resort.
_FALLBACK_NAMES: dict[str, str] = {
    "600141": "兴发集团",
    "002428": "云南锗业",
    "600206": "有研新材",
    "002409": "雅克科技",
    "600584": "长电科技",
    "002384": "东山精密",
    "688716": "中研股份",
    "600072": "中船科技",
    "603722": "阿科力",
    "000858": "五粮液",
    "600519": "贵州茅台",
    "300750": "宁德时代",
}

# Six dimensions mapped from internal key → Chinese label
DIM_LABELS: dict[str, str] = {
    "industry": "产业",
    "flow": "资金",
    "inst": "机构",
    "margin": "融资",
    "quant": "量化",
    "expect": "预期",
}

# Order for output display
DIM_ORDER = ["industry", "flow", "inst", "margin", "quant", "expect"]

# Threshold for showing a dimension change
DELTA_THRESHOLD = 0.1


class DailyDelta:
    """Compare today vs yesterday dimension scores and format a summary."""

    def __init__(self, pool_dir: str | Path | None = None) -> None:
        self._pool_dir = Path(pool_dir) if pool_dir else ROOT
        self._name_map: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(
        self,
        delta_date: str | None = None,
        scores_dir: str | Path | None = None,
    ) -> str:
        """Generate the Daily Delta section for a given date.

        Args:
            delta_date: Date string YYYY-MM-DD (default: today).
            scores_dir: Override scores directory.

        Returns:
            Formatted markdown-style daily delta report string.
        """
        today = self._resolve_date(delta_date)
        yesterday = today - timedelta(days=1)

        scores_path = Path(scores_dir) if scores_dir else SCORES_DIR

        today_data = self._load_scores(scores_path, today)
        if today_data is None:
            return f"[Daily Delta] 今日({today.isoformat()})评分数据不存在。\n"

        yesterday_data = self._load_scores(scores_path, yesterday)
        if yesterday_data is None:
            return "📊 日变化 (Daily Delta)\n────────────────────────\n暂无昨日数据\n"

        today_stocks = self._index_stocks(today_data)
        yesterday_stocks = self._index_stocks(yesterday_data)
        self._ensure_name_map(today_stocks)

        lines = self._compute_deltas(today_stocks, yesterday_stocks)
        if not lines:
            return "📊 日变化 (Daily Delta)\n────────────────────────\n今日无变化或标的为空\n"

        return "📊 日变化 (Daily Delta)\n────────────────────────\n" + "\n".join(lines) + "\n"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_date(delta_date: str | None) -> date:
        if delta_date:
            return date.fromisoformat(delta_date)
        return date.today()

    @staticmethod
    def _load_scores(scores_dir: Path, d: date) -> dict[str, Any] | None:
        path = scores_dir / f"{d.isoformat()}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    @staticmethod
    def _index_stocks(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
        """Build code→stock dict from a scores snapshot."""
        stocks = data.get("stocks") or data.get("scores") or []
        result: dict[str, dict[str, Any]] = {}
        for s in stocks:
            code = str(s.get("code", "")).zfill(6)
            if not code or len(code) != 6:
                continue
            result[code] = s
        return result

    def _ensure_name_map(self, stocks: dict[str, dict[str, Any]]) -> None:
        """Build code→name mapping from pool files."""
        if self._name_map:
            return  # already built

        # First, pull names from the stock entries themselves (if available)
        for code, s in stocks.items():
            name = s.get("name", "")
            if name:
                self._name_map[code] = name

        # Fallback: load from latest pool file
        pool_files = sorted(
            self._pool_dir.glob("pool_*.json"), reverse=True
        )
        for pf in pool_files:
            try:
                pool = json.loads(pf.read_text(encoding="utf-8"))
                for r in pool.get("results", []):
                    c = str(r.get("code", "")).zfill(6)
                    n = r.get("name", "")
                    if c and n and c not in self._name_map:
                        self._name_map[c] = n
            except (json.JSONDecodeError, OSError):
                continue

    def _get_name(self, code: str) -> str:
        name = self._name_map.get(code)
        if name:
            return name
        return _FALLBACK_NAMES.get(code, code)

    def _compute_deltas(
        self,
        today: dict[str, dict[str, Any]],
        yesterday: dict[str, dict[str, Any]],
    ) -> list[str]:
        """Compare today vs yesterday scores and format change lines."""
        lines: list[str] = []

        # Sort by |delta| descending
        deltas: list[tuple[str, float, dict[str, float]]] = []

        for code, t in today.items():
            y = yesterday.get(code)
            if y is None:
                continue

            today_total = round(float(t.get("total", 0)), 2)
            yesterday_total = round(float(y.get("total", 0)), 2)
            diff = round(today_total - yesterday_total, 2)

            if abs(diff) <= DELTA_THRESHOLD:
                continue

            dim_deltas: dict[str, float] = {}
            for dim in DIM_ORDER:
                tv = float(t.get(dim, 0))
                yv = float(y.get(dim, 0))
                dv = round(tv - yv, 2)
                if abs(dv) > DELTA_THRESHOLD:
                    dim_deltas[dim] = dv

            deltas.append((code, diff, dim_deltas))

        # Sort by absolute delta descending
        deltas.sort(key=lambda x: abs(x[1]), reverse=True)

        for code, total_diff, dim_deltas in deltas:
            name = self._get_name(code)
            today_total = round(float(today[code].get("total", 0)), 2)
            yesterday_total = round(float(yesterday[code].get("total", 0)), 2)

            # Only show dimensions that actually changed
            if dim_deltas:
                dim_parts: list[str] = []
                for dim in DIM_ORDER:
                    if dim in dim_deltas:
                        arrow = self._arrow(dim_deltas[dim])
                        dim_parts.append(f"{DIM_LABELS.get(dim, dim)}{arrow}")
                dim_str = "(" + " ".join(dim_parts) + ")"
            else:
                dim_str = ""

            sign = "+" if total_diff >= 0 else ""
            line = f"{name:<8} {yesterday_total:.1f} → {today_total:.1f}  {sign}{total_diff:.1f}"
            if dim_str:
                line += f"  {dim_str}"
            lines.append(line)

        return lines

    @staticmethod
    def _arrow(delta: float) -> str:
        if delta > 0.05:
            return "↑"
        if delta < -0.05:
            return "↓"
        return "→"


# ------------------------------------------------------------------
# CLI entry point
# ------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate Daily Delta: compare today vs yesterday scores"
    )
    parser.add_argument(
        "date",
        nargs="?",
        default=None,
        help="Date to run delta for (YYYY-MM-DD). Default: today.",
    )
    parser.add_argument(
        "--scores-dir",
        default=str(SCORES_DIR),
        help=f"Scores directory path (default: {SCORES_DIR})",
    )
    parser.add_argument(
        "--pool-dir",
        default=str(ROOT),
        help="Directory containing pool_*.json files for name lookup",
    )
    parser.add_argument(
        "--out",
        default="",
        help="Write output to file instead of stdout",
    )
    args = parser.parse_args()

    delta = DailyDelta(pool_dir=args.pool_dir)
    report = delta.generate(
        delta_date=args.date or None,
        scores_dir=args.scores_dir,
    )

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report, encoding="utf-8")
        print(f"Daily Delta written to {out_path}")
    else:
        print(report)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
