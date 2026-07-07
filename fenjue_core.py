#!/usr/bin/env python3
"""Small, dependency-free data/cache layer for the Fenjue research tools."""

from __future__ import annotations

import json
import math
import os
import sqlite3
import time
import urllib.parse
import urllib.request
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable


ROOT = Path(os.environ.get("FENJUE_ROOT", "/opt/data/fenjue"))
DB_PATH = Path(os.environ.get("FENJUE_DB", ROOT / "data" / "fenjue.sqlite3"))
MAIN_PREFIXES = ("600", "601", "603", "605", "000", "001", "002", "003")


def normalize_code(code: str) -> str:
    digits = "".join(ch for ch in str(code) if ch.isdigit())
    if len(digits) < 6:
        raise ValueError(f"invalid stock code: {code}")
    return digits[-6:]


def is_main_board(code: str) -> bool:
    return normalize_code(code).startswith(MAIN_PREFIXES)


def symbol(code: str) -> str:
    code = normalize_code(code)
    return ("sh" if code.startswith("6") else "sz") + code


def asset_key(value: str) -> str:
    raw = str(value).strip().lower()
    if len(raw) == 8 and raw[:2] in {"sh", "sz"} and raw[2:].isdigit():
        return raw
    return normalize_code(raw)


def asset_symbol(value: str) -> str:
    key = asset_key(value)
    return key if key.startswith(("sh", "sz")) else symbol(key)


def db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    with closing(db()) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS daily_bars (
                code TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL,
                amount REAL,
                source TEXT NOT NULL,
                adjusted TEXT NOT NULL DEFAULT 'qfq',
                updated_at INTEGER NOT NULL,
                PRIMARY KEY (code, trade_date, adjusted)
            );
            CREATE INDEX IF NOT EXISTS idx_daily_date ON daily_bars(trade_date);

            CREATE TABLE IF NOT EXISTS quote_snapshots (
                trade_date TEXT NOT NULL,
                quote_time TEXT NOT NULL,
                code TEXT NOT NULL,
                name TEXT,
                open REAL,
                prev_close REAL,
                price REAL,
                high REAL,
                low REAL,
                volume REAL,
                amount REAL,
                pct REAL,
                source TEXT NOT NULL,
                raw_json TEXT,
                PRIMARY KEY (trade_date, quote_time, code, source)
            );
            CREATE INDEX IF NOT EXISTS idx_quote_date ON quote_snapshots(trade_date, quote_time);

            CREATE TABLE IF NOT EXISTS strategy_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy TEXT NOT NULL,
                run_at TEXT NOT NULL,
                sample_start TEXT,
                sample_end TEXT,
                sample_count INTEGER NOT NULL,
                metrics_json TEXT NOT NULL,
                config_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS evidence (
                trade_date TEXT NOT NULL,
                code TEXT NOT NULL,
                evidence_type TEXT NOT NULL,
                score REAL NOT NULL DEFAULT 0,
                payload_json TEXT NOT NULL,
                source TEXT NOT NULL,
                available_at TEXT NOT NULL,
                PRIMARY KEY (trade_date, code, evidence_type, source)
            );

            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at INTEGER NOT NULL
            );
            """
        )
        conn.commit()


def request_text(url: str, *, encoding: str = "utf-8", timeout: int = 10) -> str:
    referer = "https://finance.sina.com.cn/" if "sina" in url else "https://finance.qq.com/"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 FenjueLab/1.0",
            "Referer": referer,
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read().decode(encoding, errors="replace")


def fetch_tencent_daily(code: str, start: str, end: str, count: int = 1600) -> list[dict]:
    """Fetch qfq daily bars. This is a free fallback, not an exchange SLA feed."""
    code = asset_key(code)
    market_symbol = asset_symbol(code)
    start_day = date.fromisoformat(start)
    end_day = date.fromisoformat(end)
    windows = []
    cursor = start_day
    while cursor <= end_day:
        window_end = min(end_day, cursor + timedelta(days=700))
        windows.append((cursor.isoformat(), window_end.isoformat()))
        cursor = window_end + timedelta(days=1)
    rows = []
    for window_start, window_end in windows:
        param = f"{market_symbol},day,{window_start},{window_end},640,qfq"
        url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=" + urllib.parse.quote(param, safe=",")
        payload = json.loads(request_text(url))
        item = (payload.get("data") or {}).get(market_symbol) or {}
        rows.extend(item.get("qfqday") or item.get("day") or [])
    output = []
    for row in rows:
        if len(row) < 6:
            continue
        volume = float(row[5]) if row[5] not in ("", None) and not isinstance(row[5], dict) else None
        amount = (
            float(row[6])
            if len(row) > 6 and row[6] not in ("", None) and not isinstance(row[6], dict)
            else None
        )
        output.append(
            {
                "code": code,
                "trade_date": row[0],
                "open": float(row[1]),
                "close": float(row[2]),
                "high": float(row[3]),
                "low": float(row[4]),
                "volume": volume,
                "amount": amount,
                "source": "tencent",
                "adjusted": "qfq",
            }
        )
    return output


def upsert_daily(rows: Iterable[dict]) -> int:
    values = list(rows)
    if not values:
        return 0
    now = int(time.time())
    with closing(db()) as conn:
        conn.executemany(
            """
            INSERT INTO daily_bars
                (code, trade_date, open, high, low, close, volume, amount, source, adjusted, updated_at)
            VALUES
                (:code, :trade_date, :open, :high, :low, :close, :volume, :amount, :source, :adjusted, :updated_at)
            ON CONFLICT(code, trade_date, adjusted) DO UPDATE SET
                open=excluded.open, high=excluded.high, low=excluded.low, close=excluded.close,
                volume=excluded.volume, amount=excluded.amount, source=excluded.source,
                updated_at=excluded.updated_at
            """,
            [{**row, "updated_at": now} for row in values],
        )
        conn.commit()
    return len(values)


def ensure_daily(
    code: str,
    years: int = 5,
    refresh_days: int = 7,
    backfill: bool = False,
) -> list[dict]:
    init_db()
    code = asset_key(code)
    end = date.today()
    start = end - timedelta(days=max(365, years * 370))
    with closing(db()) as conn:
        row = conn.execute(
            "SELECT MIN(trade_date) AS first_date, MAX(trade_date) AS last_date "
            "FROM daily_bars WHERE code=? AND adjusted='qfq'",
            (code,),
        ).fetchone()
    stale = not row or not row["last_date"]
    if row and row["last_date"]:
        stale = (end - date.fromisoformat(row["last_date"])).days >= refresh_days
    incomplete = bool(
        backfill
        and row
        and row["first_date"]
        and date.fromisoformat(row["first_date"]) > start + timedelta(days=45)
    )
    if stale or incomplete:
        rows = fetch_tencent_daily(code, start.isoformat(), end.isoformat(), years * 260 + 80)
        upsert_daily(rows)
    return load_daily(code, start.isoformat(), end.isoformat())


def load_daily(code: str, start: str = "2000-01-01", end: str = "2999-12-31") -> list[dict]:
    code = asset_key(code)
    with closing(db()) as conn:
        rows = conn.execute(
            """
            SELECT code, trade_date, open, high, low, close, volume, amount, source
            FROM daily_bars
            WHERE code=? AND adjusted='qfq' AND trade_date BETWEEN ? AND ?
            ORDER BY trade_date
            """,
            (code, start, end),
        ).fetchall()
    return [dict(row) for row in rows]


def parse_sina_quotes(text: str) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for line in text.splitlines():
        if '="' not in line:
            continue
        left, raw = line.split('="', 1)
        code = left.rsplit("_", 1)[-1][-6:]
        fields = raw.rstrip('";').split(",")
        if len(fields) < 32 or not fields[0]:
            continue
        try:
            prev_close = float(fields[2])
            price = float(fields[3])
            if price <= 0 or prev_close <= 0:
                continue
            result[code] = {
                "code": code,
                "name": fields[0],
                "open": float(fields[1]),
                "prev_close": prev_close,
                "price": price,
                "high": float(fields[4]),
                "low": float(fields[5]),
                "volume": float(fields[8]),
                "amount": float(fields[9]),
                "pct": (price - prev_close) / prev_close * 100,
                "trade_date": fields[30],
                "quote_time": fields[31],
                "source": "sina",
            }
        except (ValueError, IndexError):
            continue
    return result


def parse_tencent_quotes(text: str) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for line in text.splitlines():
        if '="' not in line:
            continue
        _, raw = line.split('="', 1)
        fields = raw.rstrip('";').split("~")
        if len(fields) < 38 or not fields[1]:
            continue
        try:
            code = normalize_code(fields[2])
            price = float(fields[3])
            prev_close = float(fields[4])
            result[code] = {
                "code": code,
                "name": fields[1],
                "open": float(fields[5]),
                "prev_close": prev_close,
                "price": price,
                "high": float(fields[33]),
                "low": float(fields[34]),
                "volume": float(fields[36]) * 100,
                "amount": float(fields[37]) * 10000,
                "pct": (price - prev_close) / prev_close * 100 if prev_close else 0,
                "trade_date": fields[30][:8],
                "quote_time": fields[30][8:],
                "source": "tencent",
            }
        except (ValueError, IndexError):
            continue
    return result


def fetch_realtime(codes: Iterable[str], *, verify: bool = True) -> dict[str, dict]:
    normalized = list(dict.fromkeys(normalize_code(code) for code in codes))
    sina_symbols = ",".join(symbol(code) for code in normalized)
    try:
        sina = parse_sina_quotes(
            request_text(
                "https://hq.sinajs.cn/list=" + sina_symbols,
                encoding="gbk",
                timeout=8,
            )
        )
    except Exception:
        sina = {}
    if not verify:
        return sina
    tencent_symbols = ",".join(symbol(code) for code in normalized)
    try:
        tencent = parse_tencent_quotes(
            request_text(
                "https://qt.gtimg.cn/q=" + tencent_symbols,
                encoding="gbk",
                timeout=8,
            )
        )
    except Exception:
        tencent = {}
    for code, row in sina.items():
        peer = tencent.get(code)
        row["verified_by"] = []
        if peer and peer["price"] > 0:
            drift = abs(row["price"] - peer["price"]) / peer["price"]
            row["verified_by"].append("tencent")
            row["price_drift"] = drift
            row["quality"] = "ok" if drift <= 0.002 else "conflict"
        else:
            row["quality"] = "single_source"
    for code, row in tencent.items():
        if code not in sina:
            row["verified_by"] = []
            row["quality"] = "fallback"
            sina[code] = row
    return sina


def save_snapshot(quotes: dict[str, dict]) -> int:
    if not quotes:
        return 0
    init_db()
    rows = []
    for row in quotes.values():
        rows.append(
            {
                **row,
                "raw_json": json.dumps(row, ensure_ascii=False, separators=(",", ":")),
            }
        )
    with closing(db()) as conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO quote_snapshots
                (trade_date, quote_time, code, name, open, prev_close, price, high, low,
                 volume, amount, pct, source, raw_json)
            VALUES
                (:trade_date, :quote_time, :code, :name, :open, :prev_close, :price, :high, :low,
                 :volume, :amount, :pct, :source, :raw_json)
            """,
            rows,
        )
        conn.commit()
    return len(rows)


def ema(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    alpha = 2 / (period + 1)
    output = [values[0]]
    for value in values[1:]:
        output.append(alpha * value + (1 - alpha) * output[-1])
    return output


def rolling_mean(values: list[float], period: int) -> list[float | None]:
    output: list[float | None] = []
    total = 0.0
    for index, value in enumerate(values):
        total += value
        if index >= period:
            total -= values[index - period]
        output.append(total / period if index + 1 >= period else None)
    return output


def indicators(rows: list[dict]) -> list[dict]:
    closes = [float(row["close"]) for row in rows]
    ma5 = rolling_mean(closes, 5)
    ma20 = rolling_mean(closes, 20)
    dif = [a - b for a, b in zip(ema(closes, 12), ema(closes, 26))]
    dea = ema(dif, 9)
    hist = [2 * (a - b) for a, b in zip(dif, dea)]
    output = []
    for index, row in enumerate(rows):
        output.append(
            {
                **row,
                "ma5": ma5[index],
                "ma20": ma20[index],
                "dif": dif[index],
                "dea": dea[index],
                "macd_hist": hist[index],
            }
        )
    return output


def record_run(strategy: str, rows: list[dict], metrics: dict, config: dict) -> None:
    init_db()
    dates = [row.get("signal_date") for row in rows if row.get("signal_date")]
    with closing(db()) as conn:
        conn.execute(
            """
            INSERT INTO strategy_runs
                (strategy, run_at, sample_start, sample_end, sample_count, metrics_json, config_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                strategy,
                datetime.now().isoformat(timespec="seconds"),
                min(dates) if dates else None,
                max(dates) if dates else None,
                len(rows),
                json.dumps(metrics, ensure_ascii=False, separators=(",", ":")),
                json.dumps(config, ensure_ascii=False, separators=(",", ":")),
            ),
        )
        conn.commit()


def retention(days_intraday: int = 120, years_daily: int = 5) -> dict:
    init_db()
    quote_cutoff = (date.today() - timedelta(days=days_intraday)).isoformat()
    daily_cutoff = (date.today() - timedelta(days=years_daily * 370)).isoformat()
    with closing(db()) as conn:
        q = conn.execute("DELETE FROM quote_snapshots WHERE trade_date < ?", (quote_cutoff,)).rowcount
        d = conn.execute("DELETE FROM daily_bars WHERE trade_date < ?", (daily_cutoff,)).rowcount
        conn.commit()
        conn.execute("PRAGMA optimize")
    return {"quote_rows_deleted": q, "daily_rows_deleted": d}


def summarize_returns(values: list[float]) -> dict:
    if not values:
        return {"count": 0}
    ordered = sorted(values)
    count = len(values)
    return {
        "count": count,
        "win_rate": sum(value > 0 for value in values) / count,
        "avg_return": sum(values) / count,
        "median_return": ordered[count // 2],
        "max_return": max(values),
        "min_return": min(values),
        "profit_factor": (
            sum(value for value in values if value > 0)
            / abs(sum(value for value in values if value < 0))
            if any(value < 0 for value in values)
            else math.inf
        ),
    }
