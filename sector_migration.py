#!/usr/bin/env python3
"""Fenjue sector migration tracker.

Compare two pool_YYYYMMDD.json files and surface style rotation signals:
sectors whose candidate count or turnover expanded/shrank sharply.
This is intentionally offline and fast; it only reads existing pool files.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


ROOT = Path("/opt/data/fenjue")
MAIN_PREFIXES = ("600", "601", "603", "605", "000", "001", "002", "003")


def is_main_board(code: str) -> bool:
    return str(code).zfill(6).startswith(MAIN_PREFIXES)


def pool_files(root: Path) -> list[Path]:
    return sorted(root.glob("pool_2026*.json"))


def pick_pair(root: Path, old: str = "", new: str = "", lookback: int = 1) -> tuple[Path, Path]:
    files = pool_files(root)
    if not files:
        raise SystemExit("No pool_YYYYMMDD.json found.")
    if new:
        new_path = root / f"pool_{new.replace('-', '')}.json"
    else:
        new_path = files[-1]
    if not new_path.exists():
        raise SystemExit(f"New pool not found: {new_path}")
    if old:
        old_path = root / f"pool_{old.replace('-', '')}.json"
    else:
        idx = files.index(new_path)
        old_idx = max(0, idx - max(1, lookback))
        old_path = files[old_idx]
    if old_path == new_path:
        raise SystemExit("Need two different pool files for migration analysis.")
    if not old_path.exists():
        raise SystemExit(f"Old pool not found: {old_path}")
    return old_path, new_path


def summarize(path: Path) -> dict[str, dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    stats: dict[str, dict] = defaultdict(lambda: {"count": 0, "amount": 0.0, "zt": 0, "pct_sum": 0.0, "stocks": []})
    for row in data.get("results", []):
        code = str(row.get("code", "")).zfill(6)
        if not is_main_board(code):
            continue
        sector = row.get("sector") or "未分类"
        pct = float(row.get("pct") or 0)
        amount = float(row.get("amount_yi") or 0)
        item = stats[sector]
        item["count"] += 1
        item["amount"] += amount
        item["zt"] += 1 if pct >= 9.8 else 0
        item["pct_sum"] += pct
        item["stocks"].append(row)
    for item in stats.values():
        item["avg_pct"] = item["pct_sum"] / item["count"] if item["count"] else 0.0
        item["stocks"].sort(key=lambda r: (float(r.get("amount_yi") or 0), float(r.get("pct") or 0)), reverse=True)
    return dict(stats)


def classify(old: dict, new: dict) -> str:
    old_count, new_count = old["count"], new["count"]
    old_amount, new_amount = old["amount"], new["amount"]
    count_ratio = new_count / old_count if old_count else (99.0 if new_count else 0.0)
    amount_ratio = new_amount / old_amount if old_amount else (99.0 if new_amount else 0.0)
    if old_count and new_count == 0:
        return "🔴🔴 归零退潮"
    if count_ratio <= 0.5 and amount_ratio <= 0.75:
        return "🔴 数量腰斩+成交收缩"
    if count_ratio <= 0.5:
        return "🔴 数量腰斩"
    if count_ratio >= 2 and amount_ratio >= 1.5:
        return "🟢 数量翻倍+成交放大"
    if count_ratio >= 2:
        return "🟢 数量翻倍"
    if amount_ratio >= 2 and new_count >= old_count:
        return "🟢 成交翻倍"
    if amount_ratio <= 0.5 and new_count <= old_count:
        return "🔴 成交腰斩"
    return "观察"


def fmt_leaders(item: dict, n: int = 3) -> str:
    out = []
    for r in item.get("stocks", [])[:n]:
        out.append(f"{str(r.get('code','')).zfill(6)}{r.get('name','')}({float(r.get('amount_yi') or 0):.0f}亿,{float(r.get('pct') or 0):+.1f}%)")
    return " / ".join(out) if out else "-"


def build_rows(old_stats: dict[str, dict], new_stats: dict[str, dict]) -> list[dict]:
    rows = []
    for sector in sorted(set(old_stats) | set(new_stats)):
        old = old_stats.get(sector, {"count": 0, "amount": 0.0, "zt": 0, "avg_pct": 0.0, "stocks": []})
        new = new_stats.get(sector, {"count": 0, "amount": 0.0, "zt": 0, "avg_pct": 0.0, "stocks": []})
        old_count = old["count"]
        old_amount = old["amount"]
        count_ratio = new["count"] / old_count if old_count else (99.0 if new["count"] else 0.0)
        amount_ratio = new["amount"] / old_amount if old_amount else (99.0 if new["amount"] else 0.0)
        signal = classify(old, new)
        strength = abs(new["count"] - old["count"]) * 18 + abs(new["amount"] - old["amount"]) * 0.6
        if signal != "观察":
            strength += 100
        rows.append({
            "sector": sector,
            "old_count": old["count"],
            "new_count": new["count"],
            "old_amount": old["amount"],
            "new_amount": new["amount"],
            "count_ratio": count_ratio,
            "amount_ratio": amount_ratio,
            "new_zt": new["zt"],
            "signal": signal,
            "strength": strength,
            "leaders": fmt_leaders(new),
        })
    rows.sort(key=lambda r: (r["signal"] == "观察", -r["strength"]))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Fenjue sector migration tracker")
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--old", default="", help="Old pool date YYYYMMDD. Empty = N-lookback.")
    parser.add_argument("--new", default="", help="New pool date YYYYMMDD. Empty = latest.")
    parser.add_argument("--lookback", type=int, default=1, help="Compare latest vs N available pool files back.")
    parser.add_argument("--limit", type=int, default=12)
    args = parser.parse_args()

    old_path, new_path = pick_pair(Path(args.root), args.old, args.new, args.lookback)
    old_stats = summarize(old_path)
    new_stats = summarize(new_path)
    rows = build_rows(old_stats, new_stats)

    print(f"行业迁移追踪 | {old_path.name} → {new_path.name}")
    print("口径：只看沪深主板焚诀池。数量变化是资金风格线索，不等于买入指令；必须结合次日竞价/快筛确认。")
    for i, r in enumerate(rows[: args.limit], 1):
        print(
            f"{i:02d}. {r['sector']} | {r['signal']} | "
            f"数量 {r['old_count']}→{r['new_count']} ({r['count_ratio']:.1f}x) | "
            f"成交 {r['old_amount']:.0f}→{r['new_amount']:.0f}亿 ({r['amount_ratio']:.1f}x) | "
            f"新池涨停{r['new_zt']} | 锚点: {r['leaders']}"
        )
    print("\n使用规则：🟢翻倍/成交放大=新方向观察；🔴腰斩/归零=旧方向退潮预警；若你持仓在退潮侧，第二天先看风险而不是找理由加仓。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
