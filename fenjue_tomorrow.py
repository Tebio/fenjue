#!/usr/bin/env python3
"""Generate a concise next-day Fenjue direction brief from the latest pool.

This script is intentionally offline/fast: it reads pool_YYYYMMDD.json only.
Use it after close. Intraday decisions still belong to fenjue_fast.py.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from sector_migration import build_rows, pick_pair, summarize


ROOT = Path("/opt/data/fenjue")


def is_main_board(code: str) -> bool:
    return str(code).zfill(6).startswith(("600", "601", "603", "605", "000", "001", "002", "003"))


def latest_pool(root: Path) -> Path:
    files = sorted(root.glob("pool_2026*.json"))
    if not files:
        raise SystemExit("No pool_YYYYMMDD.json found.")
    return files[-1]


def classify_sector(d: dict) -> str:
    if d["zt"] >= 2 and d["amount"] >= 100 and d["avg_pct"] >= 4:
        return "主线候选"
    if d["amount"] >= 250 and d["avg_pct"] >= 3:
        return "大资金方向"
    if d["zt"] >= 1 and d["n"] <= 3:
        return "独苗/情绪锚"
    if d["avg_pct"] < 1 or d["neg"] >= max(2, d["n"] // 3):
        return "分化/谨慎"
    return "观察"


def risk_flags(d: dict) -> list[str]:
    flags = []
    if d["top_amount"] > d["amount"] * 0.45:
        flags.append("单票占比过高")
    if d["neg"] >= max(2, d["n"] // 3):
        flags.append("板块内部分化")
    if d["zt"] == 0 and d["amount"] >= 250:
        flags.append("大成交但无涨停")
    if d["avg_pct"] >= 7:
        flags.append("高潮后接力难度高")
    return flags


def main() -> int:
    parser = argparse.ArgumentParser(description="Fenjue next-day direction brief")
    parser.add_argument("--pool", default="", help="pool_YYYYMMDD.json path. Empty = latest.")
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--top-sectors", type=int, default=8)
    parser.add_argument("--top-stocks", type=int, default=6)
    args = parser.parse_args()

    root = Path(args.root)
    pool_path = Path(args.pool) if args.pool else latest_pool(root)
    data = json.loads(pool_path.read_text(encoding="utf-8"))
    rows = [r for r in data.get("results", []) if is_main_board(str(r.get("code", "")))]

    try:
        old_path, new_path = pick_pair(root, new=pool_path.stem.replace("pool_", ""), lookback=1)
        migration_rows = build_rows(summarize(old_path), summarize(new_path))
    except Exception:
        old_path = new_path = None
        migration_rows = []

    sectors: dict[str, dict] = defaultdict(lambda: {"n": 0, "amount": 0.0, "pct_sum": 0.0, "zt": 0, "neg": 0, "stocks": []})
    for r in rows:
        sector = r.get("sector") or "未分类"
        pct = float(r.get("pct") or 0)
        amount = float(r.get("amount_yi") or 0)
        d = sectors[sector]
        d["n"] += 1
        d["amount"] += amount
        d["pct_sum"] += pct
        d["zt"] += 1 if pct >= 9.8 else 0
        d["neg"] += 1 if pct < 0 else 0
        d["stocks"].append(r)

    ranked = []
    for sector, d in sectors.items():
        d["avg_pct"] = d["pct_sum"] / d["n"] if d["n"] else 0.0
        d["stocks"].sort(key=lambda x: (float(x.get("pct") or 0) >= 9.8, float(x.get("amount_yi") or 0), float(x.get("pct") or 0)), reverse=True)
        d["top_amount"] = float(d["stocks"][0].get("amount_yi") or 0) if d["stocks"] else 0.0
        d["label"] = classify_sector(d)
        d["risks"] = risk_flags(d)
        # Direction score favors breadth, real money and limit-up anchors.
        d["score"] = d["amount"] * 0.35 + d["n"] * 18 + d["zt"] * 70 + max(d["avg_pct"], 0) * 22 - d["neg"] * 18
        ranked.append((sector, d))
    ranked.sort(key=lambda item: item[1]["score"], reverse=True)

    print(f"焚诀明日方向 | pool={pool_path.name} | 沪深主板池={len(rows)}")
    print("原则：这是次日观察计划，不是买入指令。明天必须用 9:25 竞价 + 9:40 快筛确认。")
    if migration_rows:
        print("\n[行业迁移追踪]")
        print(f"对比：{old_path.name} → {new_path.name}。这是风格切换预警，优先级高于单日板块热度。")
        shown = 0
        for r in migration_rows:
            if r["signal"] == "观察":
                continue
            shown += 1
            print(
                f"{shown:02d}. {r['sector']} | {r['signal']} | "
                f"数量 {r['old_count']}→{r['new_count']} ({r['count_ratio']:.1f}x) | "
                f"成交 {r['old_amount']:.0f}→{r['new_amount']:.0f}亿 ({r['amount_ratio']:.1f}x) | "
                f"锚点: {r['leaders']}"
            )
            if shown >= 6:
                break
        if shown == 0:
            print("无明显翻倍/腰斩迁移信号。")
        print("规则：🟢翻倍/成交放大=新方向观察；🔴腰斩/归零=旧方向退潮预警。")
    print("\n[板块热度]")
    for i, (sector, d) in enumerate(ranked[: args.top_sectors], 1):
        risk = "；".join(d["risks"]) if d["risks"] else "无明显"
        print(
            f"{i:02d}. {sector} | {d['label']} | {d['n']}只 | 成交{d['amount']:.1f}亿 | "
            f"均涨{d['avg_pct']:+.2f}% | 涨停{d['zt']} | 风险:{risk}"
        )
        leaders = []
        for r in d["stocks"][:3]:
            leaders.append(f"{r['code']}{r['name']}({float(r.get('pct') or 0):+.1f}%,{float(r.get('amount_yi') or 0):.0f}亿)")
        print("    锚点: " + " / ".join(leaders))

    print("\n[明日9:25优先盯]")
    watch = []
    for sector, d in ranked[: args.top_sectors]:
        for r in d["stocks"][: args.top_stocks]:
            pct = float(r.get("pct") or 0)
            amount = float(r.get("amount_yi") or 0)
            if pct >= 9.8 or amount >= 80 or (d["zt"] >= 2 and amount >= 20):
                watch.append((sector, d, r))
    seen = set()
    n = 0
    for sector, d, r in watch:
        code = str(r["code"]).zfill(6)
        if code in seen:
            continue
        seen.add(code)
        n += 1
        print(
            f"{n:02d}. {code} {r['name']} | {sector} | 昨涨{float(r.get('pct') or 0):+.2f}% | "
            f"昨成交{float(r.get('amount_yi') or 0):.1f}亿 | 触发:高开1%-6%且9:40不破开盘/板块≥3只在榜"
        )
        if n >= 12:
            break

    print("\n[否定条件]")
    print("- 大盘未红或明显缩量：不开新仓，只观察。")
    print("- 9:40 板块少于3只在榜，或龙头 accel<0 且日内位置<50%：按分化处理。")
    print("- 一字板/秒板买不到的不追；炸板回落后除非二次回封，否则不当强票。")
    print("- 趋势票和打板票分开看：趋势榜强不代表适合打板。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
