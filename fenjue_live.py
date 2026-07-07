#!/usr/bin/env python3
"""Compatibility wrapper for old Fenjue live commands.

Old versions used slow per-stock Eastmoney polling. Live trading must now use
Sina batch snapshots:

  phase1 -> fenjue_snapshot.py --tag 0925
  phase2 -> fenjue_fast.py --limit N

Historical replay/close validation remains in /opt/data/tools/stock/fen_replay.py
and should only be called when explicitly requested.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent


def run(args: list[str]) -> int:
    proc = subprocess.run([sys.executable, *args], cwd=str(HERE), check=False)
    return proc.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Fast Fenjue live compatibility wrapper")
    parser.add_argument("phase", choices=["phase1", "phase2", "snapshot", "fast"], help="phase1=save 09:25 snapshot; phase2=run fast 09:40 scan")
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--tag", default="0925")
    parser.add_argument("--pool-dir", default="")
    parser.add_argument("--snapshot-dir", default="/opt/data/fenjue/snapshots")
    parser.add_argument("--snapshot-date", default="")
    parser.add_argument("--early-tag", default="0925")
    parser.add_argument("--ignore-market-gate", action="store_true")
    args = parser.parse_args()

    if args.phase in {"phase1", "snapshot"}:
        cmd = ["fenjue_snapshot.py", "--tag", args.tag, "--out-dir", args.snapshot_dir]
        if args.pool_dir:
            cmd.extend(["--pool-dir", args.pool_dir])
        return run(cmd)

    cmd = [
        "fenjue_fast.py",
        "--limit",
        str(args.limit),
        "--snapshot-dir",
        args.snapshot_dir,
        "--early-tag",
        args.early_tag,
    ]
    if args.pool_dir:
        cmd.extend(["--pool-dir", args.pool_dir])
    if args.snapshot_date:
        cmd.extend(["--snapshot-date", args.snapshot_date])
    if args.ignore_market_gate:
        cmd.append("--ignore-market-gate")
    return run(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
