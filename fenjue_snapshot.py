#!/usr/bin/env python3
"""Save a lightweight Fenjue realtime snapshot.

This script is intentionally small: it reuses fenjue_fast.py's Sina batch quote
fetcher, writes one JSON file, and exits. No daemon, no extra Docker service.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from fenjue_fast import DEFAULT_POOL_DIR, fetch_quotes, is_main_board, load_pool, market_gate


def main() -> int:
    parser = argparse.ArgumentParser(description="Save Fenjue quote snapshot for 09:25/09:40 scoring")
    parser.add_argument("--tag", default="", help="Snapshot tag, e.g. 0925 or 0940. Empty = current HHMM.")
    parser.add_argument("--pool-date", default="", help="Pool date like 20260508. Empty = latest pool.")
    parser.add_argument("--pool-dir", default=str(DEFAULT_POOL_DIR))
    parser.add_argument("--out-dir", default="/opt/data/fenjue/snapshots")
    args = parser.parse_args()

    now = datetime.now()
    tag = args.tag or now.strftime("%H%M")
    pool_path, pool = load_pool(Path(args.pool_dir), args.pool_date or None)
    codes = [str(r.get("code", "")).zfill(6) for r in pool if is_main_board(str(r.get("code", "")))]
    quotes = fetch_quotes(codes)
    gate_ok, gate_text = market_gate()
    quote_dates = Counter(str(row.get("date") or "").replace("-", "") for row in quotes.values())
    quote_day = quote_dates.most_common(1)[0][0] if quote_dates else now.strftime("%Y%m%d")
    if len(quote_day) != 8:
        quote_day = now.strftime("%Y%m%d")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"snapshot_{quote_day}_{tag}.json"
    payload = {
        "created_at": now.isoformat(timespec="seconds"),
        "quote_date": quote_day,
        "tag": tag,
        "pool": pool_path.name,
        "market_gate_ok": gate_ok,
        "market_gate_text": gate_text,
        "count": len(quotes),
        "quotes": quotes,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"snapshot saved: {out_path} | quotes={len(quotes)} | {gate_text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
