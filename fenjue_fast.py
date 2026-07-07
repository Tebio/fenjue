#!/usr/bin/env python3
"""Fast Fenjue live scanner.

Design:
  - Build the expensive T-1 pool after close with build_pool.py.
  - At 09:40, load that pool and fetch Sina realtime quotes in batches.
  - Enforce main-board only at the final gate.

This is for live/near-live use. Historical replay should use fen_replay.py,
because using a same-day close pool is lookahead bias.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

if "/opt/data/python-libs" not in sys.path:
    sys.path.insert(0, "/opt/data/python-libs")

import requests
from fenjue_core import fetch_realtime


DEFAULT_POOL_DIR = Path(os.environ.get("FENJUE_POOL_DIR", "/opt/data/fenjue"))
MAIN_PREFIXES = ("600", "601", "603", "605", "000", "001", "002", "003")


def clear_proxy_env() -> None:
    for key in list(os.environ.keys()):
        if "proxy" in key.lower():
            os.environ.pop(key, None)
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"


def is_main_board(code: str) -> bool:
    return str(code).zfill(6).startswith(MAIN_PREFIXES)


def to_sina(code: str) -> str:
    code = str(code).zfill(6)
    return ("sh" if code.startswith("6") else "sz") + code


def load_pool(
    pool_dir: Path,
    pool_date: str | None = None,
    pool_lookback: int | None = None,
) -> tuple[Path, list[dict]]:
    if pool_date:
        path = pool_dir / f"pool_{pool_date.replace('-', '')}.json"
        files = [path]
    else:
        files = sorted(pool_dir.glob("pool_2026*.json"), reverse=True)
        if not files:
            raise SystemExit("No pool_*.json found. Run build_pool.py after close first.")
        lookback = pool_lookback if pool_lookback is not None else int(os.environ.get("FENJUE_POOL_LOOKBACK", "3"))
        files = files[: max(1, lookback)]
    merged: dict[str, dict] = {}
    for idx, path in enumerate(files):
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        rows = data.get("results", [])
        source_date = str(data.get("date") or path.stem.replace("pool_", ""))
        for row in rows:
            code = str(row.get("code", "")).zfill(6)
            if not is_main_board(code):
                continue
            candidate = dict(row)
            candidate["code"] = code
            candidate["pool_source_date"] = source_date
            candidate["pool_age"] = idx
            # Keep the newest pool row, but remember the strongest recent turnover.
            if code in merged:
                old = merged[code]
                old["recent_pool_amount_yi"] = max(float(old.get("recent_pool_amount_yi") or old.get("amount_yi") or 0), float(candidate.get("amount_yi") or 0))
                old["recent_pool_pct_max"] = max(float(old.get("recent_pool_pct_max") or old.get("pct") or 0), float(candidate.get("pct") or 0))
                continue
            candidate["recent_pool_amount_yi"] = float(candidate.get("amount_yi") or 0)
            candidate["recent_pool_pct_max"] = float(candidate.get("pct") or 0)
            merged[code] = candidate
    path = files[0]
    rows = list(merged.values())
    rows = [r for r in rows if is_main_board(str(r.get("code", "")))]
    return path, rows


def load_snapshot(snapshot_dir: Path, tag: str, snapshot_date: str | None = None) -> tuple[Path | None, dict[str, dict]]:
    day = (snapshot_date or datetime.now().strftime("%Y%m%d")).replace("-", "")
    path = snapshot_dir / f"snapshot_{day}_{tag}.json"
    if not path.exists():
        return None, {}
    data = json.loads(path.read_text(encoding="utf-8"))
    quotes = data.get("quotes", {})
    return path, quotes if isinstance(quotes, dict) else {}


def fetch_quotes(codes: list[str], batch_size: int = 700) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for i in range(0, len(codes), batch_size):
        batch_rows = fetch_realtime(codes[i : i + batch_size], verify=True)
        for code, row in batch_rows.items():
            result[code] = {
                "code": code,
                "name": row["name"],
                "open": row["open"],
                "prev_close": row["prev_close"],
                "price": row["price"],
                "high": row["high"],
                "low": row["low"],
                "volume": row["volume"],
                "amount_yi": row["amount"] / 1e8,
                "pct": row["pct"],
                "date": row["trade_date"],
                "time": row["quote_time"],
                "data_quality": row.get("quality", "unknown"),
                "verified_by": row.get("verified_by", []),
            }
    return result


def fetch_sina_symbols(symbols: list[str]) -> dict[str, dict]:
    """Fetch arbitrary Sina symbols, including indices such as sh000001."""
    session = requests.Session()
    session.trust_env = False
    headers = {
        "Referer": "https://finance.sina.com.cn/",
        "User-Agent": "Mozilla/5.0",
    }
    url = "https://hq.sinajs.cn/list=" + ",".join(symbols)
    resp = session.get(url, headers=headers, timeout=10)
    resp.encoding = "gbk"
    result: dict[str, dict] = {}
    for line in resp.text.splitlines():
        if '="' not in line:
            continue
        left, raw = line.split('="', 1)
        symbol = left.rsplit("_", 1)[-1]
        fields = raw.rstrip('";').split(",")
        if len(fields) < 4 or not fields[0]:
            continue
        try:
            open_p = float(fields[1])
            prev_close = float(fields[2])
            price = float(fields[3])
        except ValueError:
            continue
        if price <= 0 or prev_close <= 0:
            continue
        result[symbol] = {
            "symbol": symbol,
            "name": fields[0],
            "price": price,
            "pct": (price - prev_close) / prev_close * 100,
        }
    return result


def market_gate() -> tuple[bool, str]:
    indices = fetch_sina_symbols(["sh000001", "sz399001"])
    sh = indices.get("sh000001")
    sz = indices.get("sz399001")
    if not sh and not sz:
        return False, "大盘闸门：指数快照获取失败，默认观望。"
    parts = []
    red = False
    for item in (sh, sz):
        if not item:
            continue
        red = red or item["pct"] > 0
        parts.append(f"{item['name']} {item['pct']:+.2f}%")
    return red, "大盘闸门：" + "；".join(parts) + ("；红盘通过。" if red else "；未红，观望。")


def rank_candidates(
    pool: list[dict],
    quotes: dict[str, dict],
    args: argparse.Namespace,
    early_quotes: dict[str, dict] | None = None,
) -> list[dict]:
    early_quotes = early_quotes or {}
    rows = []
    for stock in pool:
        code = str(stock.get("code", "")).zfill(6)
        if not is_main_board(code):
            continue
        q = quotes.get(code)
        if not q:
            continue
        if q.get("data_quality") == "conflict":
            continue
        ma5 = float(stock.get("ma5") or 0)
        ma20 = float(stock.get("ma20") or 0)
        price = float(q["price"])
        above_ma5 = ma5 > 0 and price > ma5
        above_ma20 = ma20 > 0 and price > ma20
        if not (above_ma5 or above_ma20):
            continue
        pct = float(q["pct"])
        early = early_quotes.get(code, {})
        early_pct = float(early.get("pct") or 0)
        early_amount_yi = float(early.get("amount_yi") or 0)
        pct_accel = pct - early_pct if early else 0.0
        amount_after_early_yi = max(0.0, float(q["amount_yi"]) - early_amount_yi) if early else 0.0
        ma5_gap = (price - ma5) / ma5 * 100 if ma5 else 0.0
        ma20_gap = (price - ma20) / ma20 * 100 if ma20 else 0.0
        open_price = float(q["open"] or 0)
        high = float(q["high"] or 0)
        low = float(q["low"] or 0)
        open_to_now = (price - open_price) / open_price * 100 if open_price else 0.0
        range_pos = (price - low) / (high - low) if high > low else 0.5
        if pct < args.min_pct or pct > args.max_pct:
            continue
        if ma20_gap > args.max_ma20_gap:
            continue
        rows.append(
            {
                "code": code,
                "name": stock.get("name") or q["name"],
                "sector": stock.get("sector", ""),
                "price": price,
                "pct": pct,
                "early_pct": early_pct,
                "pct_accel": pct_accel,
                "amount_yi": q["amount_yi"],
                "early_amount_yi": early_amount_yi,
                "amount_after_early_yi": amount_after_early_yi,
                "open": open_price,
                "high": high,
                "low": low,
                "open_to_now": open_to_now,
                "range_pos": range_pos,
                "ma5_gap": ma5_gap,
                "ma20_gap": ma20_gap,
                "line_signal": "MA5+MA20" if above_ma5 and above_ma20 else ("MA5" if above_ma5 else "MA20"),
                "pool_amount_yi": float(stock.get("amount_yi") or 0),
                "quote_time": f"{q.get('date','')} {q.get('time','')}".strip(),
                "data_quality": q.get("data_quality", "snapshot"),
            }
        )
    if not rows:
        return []

    sector_amount = defaultdict(float)
    sector_count = Counter()
    for r in rows:
        sector_amount[r["sector"]] += r["amount_yi"]
        sector_count[r["sector"]] += 1

    max_amount = max((r["amount_yi"] for r in rows), default=1) or 1
    max_after_early_amount = max((r["amount_after_early_yi"] for r in rows), default=1) or 1
    max_sector_amount = max(sector_amount.values(), default=1) or 1
    max_sector_count = max(sector_count.values(), default=1) or 1

    for r in rows:
        sweet_spot = max(0, 6.5 - abs(r["pct"] - 4.8)) / 6.5
        # Attack style: strongest board candidates usually have sector
        # co-movement, real turnover, and price holding near the intraday high.
        ma20_sweet = max(0, 18 - abs(r["ma20_gap"] - 8)) / 18
        not_too_extended = (1 - min(max(r["ma20_gap"] / args.max_ma20_gap, 0), 1)) * 0.5 + 0.5
        range_strength = min(max(r["range_pos"], 0), 1)
        open_to_now_strength = min(max((r["open_to_now"] + 2) / 8, 0), 1)
        early_strength = min(max((r["early_pct"] - 0.5) / 4, 0), 1) if early_quotes else 0
        accel_strength = min(max((r["pct_accel"] + 0.5) / 4, 0), 1) if early_quotes else 0
        after_early_amount_strength = (r["amount_after_early_yi"] / max_after_early_amount) if early_quotes else 0
        r["sector_candidates"] = sector_count[r["sector"]]
        r["sector_amount_yi"] = sector_amount[r["sector"]]
        r["score"] = (
            (r["amount_yi"] / max_amount) * 24
            + sweet_spot * 9
            + ma20_sweet * 7
            + (r["sector_amount_yi"] / max_sector_amount) * 26
            + (r["sector_candidates"] / max_sector_count) * 11
            + range_strength * 5
            + open_to_now_strength * 3
            + not_too_extended * 3
            + early_strength * 4
            + accel_strength * 4
            + after_early_amount_strength * 4
        )
    rows.sort(key=lambda x: (x["score"], x["amount_yi"]), reverse=True)
    return rows


def limit_up_price(prev_close: float, code: str) -> float:
    """Approximate A-share main-board limit-up price."""
    if prev_close <= 0:
        return 0.0
    # ST shares are normally 5%, but name-based detection is enough here.
    return round(prev_close * 1.10 + 1e-8, 2)


def rank_attack_candidates(rows: list[dict], limit: int = 12) -> list[dict]:
    """Rank board-attack candidates separately from trend/low-absorb candidates."""
    attack = []
    if not rows:
        return []
    max_amt = max((r["amount_yi"] for r in rows), default=1) or 1
    max_after = max((r["amount_after_early_yi"] for r in rows), default=1) or 1
    for r in rows:
        prev_close = r["price"] / (1 + r["pct"] / 100) if r["pct"] > -99 else 0
        limit_price = limit_up_price(prev_close, r["code"])
        to_limit_pct = (limit_price - r["price"]) / r["price"] * 100 if limit_price and r["price"] else 99
        open_pct = (r["open"] - prev_close) / prev_close * 100 if prev_close and r["open"] else r["early_pct"]
        high_pct = (r["high"] - prev_close) / prev_close * 100 if prev_close and r["high"] else r["pct"]
        near_limit = max(0.0, min(1.0, (10.2 - max(to_limit_pct, 0)) / 10.2))
        auction = max(0.0, min(1.0, (open_pct - 1.0) / 5.0))
        intraday_push = max(0.0, min(1.0, (r["pct"] - open_pct + 1.0) / 6.0))
        high_push = max(0.0, min(1.0, (high_pct - open_pct + 1.0) / 7.0))
        hold_high = max(0.0, min(1.0, r["range_pos"]))
        money = max(0.0, min(1.0, r["amount_yi"] / max_amt))
        after_money = max(0.0, min(1.0, r["amount_after_early_yi"] / max_after))
        sector_heat = max(0.0, min(1.0, r["sector_candidates"] / 6))
        # Penalize one-word limit opens that immediately leak; prefer close to high.
        leak_penalty = max(0.0, min(1.0, (open_pct - r["pct"]) / 5.0)) if open_pct > r["pct"] else 0.0
        extension_penalty = max(0.0, min(1.0, (r["ma20_gap"] - 35) / 25))
        attack_score = (
            near_limit * 24
            + auction * 12
            + intraday_push * 12
            + high_push * 10
            + hold_high * 12
            + money * 10
            + after_money * 8
            + sector_heat * 8
            - leak_penalty * 10
            - extension_penalty * 8
        )
        rr = dict(r)
        rr.update(
            {
                "attack_score": attack_score,
                "limit_price": limit_price,
                "to_limit_pct": to_limit_pct,
                "open_pct": open_pct,
                "high_pct": high_pct,
                "attack_tag": "近板/回封观察" if to_limit_pct <= 2.0 or high_pct >= 9.3 else ("冲板跟踪" if r["pct"] >= 5.0 else "早盘强承接"),
            }
        )
        if r["pct"] >= 1.5 and open_pct >= 1.0 and high_pct >= 4.5 and r["amount_yi"] >= 1.0:
            attack.append(rr)
    attack.sort(key=lambda x: (x["attack_score"], x["amount_yi"]), reverse=True)
    return attack[:limit]


def main() -> int:
    parser = argparse.ArgumentParser(description="Fast live Fenjue scanner")
    parser.add_argument("--pool-date", default="", help="Pool date like 20260508. Empty = latest pool.")
    parser.add_argument("--pool-dir", default=str(DEFAULT_POOL_DIR), help="Directory containing pool_YYYYMMDD.json files.")
    parser.add_argument("--pool-lookback", type=int, default=3, help="Merge recent N pool files when --pool-date is empty.")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--attack-limit", type=int, default=8)
    parser.add_argument("--min-pct", type=float, default=2.0)
    parser.add_argument("--max-pct", type=float, default=8.5)
    parser.add_argument("--max-ma20-gap", type=float, default=35.0)
    parser.add_argument("--snapshot-dir", default="/opt/data/fenjue/snapshots")
    parser.add_argument("--snapshot-date", default="", help="Snapshot date like 20260511. Empty = today.")
    parser.add_argument("--early-tag", default="0925", help="Use snapshot_YYYYMMDD_TAG.json as early strength signal. Empty disables it.")
    parser.add_argument("--quote-tag", default="", help="Replay/testing only: use snapshot_YYYYMMDD_TAG.json as current quotes instead of live Sina quotes.")
    parser.add_argument("--ignore-market-gate", action="store_true", help="For testing/replay only. Live mode should require market red.")
    parser.add_argument("--allow-stale", action="store_true", help="Allow prior-trading-day quotes for weekend/review use.")
    args = parser.parse_args()

    clear_proxy_env()
    start = datetime.now()
    if args.quote_tag:
        gate_ok, gate_text = True, "回放模式：等待读取历史快照中的大盘闸门。"
    else:
        gate_ok, gate_text = market_gate()
    if not gate_ok and not args.ignore_market_gate:
        print("焚诀快筛 live")
        print("口径：只允许沪深主板 600/601/603/605/000/001/002/003；科创/创业/北交一律排除。")
        print(gate_text)
        print("[SILENT] 大盘未红，焚诀不开仓。")
        return 0
    pool_path, pool = load_pool(Path(args.pool_dir), args.pool_date or None, args.pool_lookback)
    quote_path = None
    if args.quote_tag:
        quote_path, quotes = load_snapshot(Path(args.snapshot_dir), args.quote_tag, args.snapshot_date or None)
        if not quotes:
            raise SystemExit(f"Quote snapshot not found or empty: {args.quote_tag}")
        quote_payload = json.loads(quote_path.read_text(encoding="utf-8"))
        gate_ok = bool(quote_payload.get("market_gate_ok", True))
        gate_text = str(quote_payload.get("market_gate_text") or "历史快照未记录大盘闸门。")
        if not gate_ok and not args.ignore_market_gate:
            print("焚诀快筛 replay")
            print(gate_text)
            print("[SILENT] 历史快照中大盘闸门未通过。")
            return 0
    else:
        quotes = fetch_quotes([str(r["code"]).zfill(6) for r in pool])
        quote_dates = Counter(str(row.get("date") or "") for row in quotes.values())
        quote_date = quote_dates.most_common(1)[0][0] if quote_dates else ""
        if quote_date and quote_date != datetime.now().strftime("%Y-%m-%d") and not args.allow_stale:
            print("焚诀快筛 live")
            print(f"[SILENT] 行情日期为 {quote_date}，不是今天；休市或数据过期，不输出实时候选。")
            return 0
    early_path, early_quotes = (None, {})
    if args.early_tag:
        early_path, early_quotes = load_snapshot(Path(args.snapshot_dir), args.early_tag, args.snapshot_date or None)
    rows = rank_candidates(pool, quotes, args, early_quotes)
    elapsed = (datetime.now() - start).total_seconds()

    print(f"焚诀快筛 live | pool={pool_path.name} | merged_pool={len(pool)} | quotes={len(quotes)} | elapsed={elapsed:.1f}s")
    print("口径：只允许沪深主板 600/601/603/605/000/001/002/003；科创/创业/北交一律排除；默认合并最近3个交易日强势池；站上MA5或MA20；大盘红盘才输出。")
    if early_path:
        print(f"早盘快照：{early_path.name}，已纳入竞价/早盘强度。")
    elif args.early_tag:
        print(f"早盘快照：未找到 {args.early_tag}，退回纯实时快筛。")
    if quote_path:
        print(f"回放快照：{quote_path.name}，本次未抓实时行情。")
    print(gate_text)
    if not rows:
        print("[SILENT] 无高质量候选。")
        return 0

    attack_rows = rank_attack_candidates(rows, args.attack_limit)
    if attack_rows:
        print("\n[打板/冲板观察]")
        print("说明：这是高波动观察池，不等于买入指令；优先看板块共振、承接不破开盘、回封强度和量能。")
        for i, r in enumerate(attack_rows, 1):
            print(
                f"{i:02d}. {r['code']} {r['name']} | {r['sector']} | "
                f"{r['price']:.2f}({r['pct']:+.2f}%) | 距涨停{r['to_limit_pct']:+.2f}% | "
                f"开盘{r['open_pct']:+.2f}% 高点{r['high_pct']:+.2f}% 日内位置{r['range_pos']:.0%} | "
                f"成交{r['amount_yi']:.2f}亿/早盘后{r['amount_after_early_yi']:.2f}亿 | "
                f"{r['attack_tag']} | attack={r['attack_score']:.1f}"
            )

    print("\n[趋势/建仓候选]")
    for i, r in enumerate(rows[: args.limit], 1):
        print(
            f"{i:02d}. {r['code']} {r['name']} | {r['sector']} | "
            f"{r['price']:.2f}({r['pct']:+.2f}%) | 成交{r['amount_yi']:.2f}亿 | "
            f"早盘{r['early_pct']:+.2f}%→当前加速{r['pct_accel']:+.2f}% | "
            f"{r['line_signal']} | 日内位置{r['range_pos']:.0%} | MA5乖离{r['ma5_gap']:+.2f}% MA20乖离{r['ma20_gap']:+.2f}% | "
            f"板块候选{r['sector_candidates']} | score={r['score']:.1f}"
        )

    print("\n[板块聚合]")
    for sector, count in Counter(r["sector"] for r in rows).most_common(8):
        amt = sum(r["amount_yi"] for r in rows if r["sector"] == sector)
        print(f"- {sector}: {count}只, 快照成交{amt:.2f}亿")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
