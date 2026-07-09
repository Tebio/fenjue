"""
DragonTracker — 龙虎榜数据获取与评分。

数据源: 东方财富龙虎榜API
https://datacenter.eastmoney.com/securities/api/data/v1/get

Returns daily billboard (龙虎榜) buy/sell seat data and computes a
capital-flow sentiment score (1-10) for a given stock code.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen
from urllib.error import URLError

logger = logging.getLogger(__name__)

API_URL = (
    "https://datacenter.eastmoney.com/securities/api/data/v1/get"
    "?reportName=RPT_DAILYBILLBOARD_DETAILSNEW"
    "&columns=ALL"
    "&filter=(SECURITY_CODE=%22{code}%22)"
    "&pageSize=5"
    "&sortTypes=-1"
    "&sortColumns=TRADE_DATE"
)


class DragonTracker:
    """Fetch 龙虎榜 data from EastMoney and compute a billboard score."""

    def __init__(self, cache_dir: str = "data/moneyflow/") -> None:
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    # ── public API ────────────────────────────────────────────────────────

    def fetch_latest(self, code: str) -> dict[str, Any] | None:
        """Return the most recent billboard entry for *code*, or *None*.

        Returns
        -------
        dict | None
            {
                "date":       str   ("2025-07-09"),
                "buy_total":  float (万元),
                "sell_total": float (万元),
                "net_amount": float (万元, buy_total - sell_total),
                "buy_seats":  [{"name": str, "amount": float, "type": str}, …],
                "sell_seats": [{"name": str, "amount": float, "type": str}, …],
            }
        """
        raw = self._api_fetch(code)
        if not raw or not raw.get("result") or not raw["result"].get("data"):
            return None

        data = raw["result"]["data"]
        if not data:
            return None

        # API returns rows sorted by TRADE_DATE desc — take the first
        latest = data[0]
        return self._parse_entry(latest)

    def score(self, code: str) -> int:
        """Compute a 1-10 dragon-tiger board score.

        Rules
        -----
        - 净买入 > 1亿    → 9
        - 净买入 > 5000万 → 8
        - 净买卖平衡       → 6
        - 净卖出 > 5000万 → 4
        - 净卖出 > 1亿    → 2
        - 不上榜/无数据    → 5
        """
        entry = self.fetch_latest(code)
        if entry is None:
            return 5

        net = entry.get("net_amount", 0) or 0  # 万元

        if net > 10_000:
            return 9
        if net > 5_000:
            return 8
        if net >= -5_000:
            return 6  # 平衡区域
        if net > -10_000:
            return 4
        return 2

    # ── internal helpers ──────────────────────────────────────────────────

    def _api_fetch(self, code: str) -> dict[str, Any] | None:
        """Raw HTTP GET to the EastMoney data-centre API."""
        url = API_URL.format(code=code)
        req = Request(url, headers={"User-Agent": "fenjue/1.0"})
        try:
            with urlopen(req, timeout=15) as resp:
                body = resp.read().decode("utf-8")
            return json.loads(body)
        except (URLError, json.JSONDecodeError, OSError) as exc:
            logger.warning("DragonTracker API fetch failed for %s: %s", code, exc)
            return None

    @staticmethod
    def _parse_entry(row: dict[str, Any]) -> dict[str, Any]:
        """Convert a single API row into the standardised return dict."""

        def _safe_float(val: Any) -> float:
            try:
                return float(val) if val is not None else 0.0
            except (ValueError, TypeError):
                return 0.0

        buy_total = _safe_float(row.get("BUYER_TRADE_AMT"))       # 买方成交金额(万元)
        sell_total = _safe_float(row.get("SELLER_TRADE_AMT"))     # 卖方成交金额(万元)
        net_amount = buy_total - sell_total

        # Parse seat details from comma-separated fields
        buy_seats = DragonTracker._parse_seats(
            row.get("BUYER_SECU_CODE", ""),
            row.get("BUYER_TRADE_AMT_DETAIL", ""),
        )
        sell_seats = DragonTracker._parse_seats(
            row.get("SELLER_SECU_CODE", ""),
            row.get("SELLER_TRADE_AMT_DETAIL", ""),
        )

        trade_date = row.get("TRADE_DATE", "")
        # Normalise date: API may return "2025-07-09 00:00:00" or epoch ms
        if trade_date and " " in str(trade_date):
            trade_date = str(trade_date).split(" ")[0]
        elif trade_date and str(trade_date).isdigit() and len(str(trade_date)) >= 10:
            try:
                trade_date = datetime.fromtimestamp(
                    int(str(trade_date)[:10])
                ).strftime("%Y-%m-%d")
            except (ValueError, OSError):
                pass

        return {
            "date": str(trade_date),
            "buy_total": buy_total,
            "sell_total": sell_total,
            "net_amount": round(net_amount, 2),
            "buy_seats": buy_seats,
            "sell_seats": sell_seats,
        }

    @staticmethod
    def _parse_seats(
        names_raw: str,
        amounts_raw: str,
    ) -> list[dict[str, Any]]:
        """Parse comma-separated seat names + amounts into a list."""
        names = [n.strip() for n in names_raw.split(",") if n.strip()]
        amounts = [a.strip() for a in amounts_raw.split(",") if a.strip()]
        seats: list[dict[str, Any]] = []
        for i, name in enumerate(names):
            amount = float(amounts[i]) if i < len(amounts) else 0.0
            seat_type = DragonTracker._classify_seat(name)
            seats.append({"name": name, "amount": amount, "type": seat_type})
        return seats

    @staticmethod
    def _classify_seat(name: str) -> str:
        """Classify a seat name into a type label."""
        if "机构" in name:
            return "机构"
        if "深股通" in name or "沪股通" in name or "北上" in name:
            return "北向"
        if "游资" in name or "营业部" in name:
            return "游资"
        return "其他"
