#!/usr/bin/env python3
"""Fenjue strategy lab: data cache, realistic backtests and live dual-source quotes."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from fenjue_core import (
    DB_PATH,
    ensure_daily,
    fetch_realtime,
    indicators,
    init_db,
    is_main_board,
    load_daily,
    normalize_code,
    record_run,
    retention,
    save_snapshot,
    summarize_returns,
)
from fenjue_fast import rank_attack_candidates, rank_candidates


ROOT = Path("/opt/data/fenjue")
BANKS = {
    "000001": "平安银行",
    "001227": "兰州银行",
    "002142": "宁波银行",
    "002807": "江阴银行",
    "002839": "张家港行",
    "002936": "郑州银行",
    "002948": "青岛银行",
    "002958": "青农商行",
    "002966": "苏州银行",
    "600000": "浦发银行",
    "600015": "华夏银行",
    "600016": "民生银行",
    "600036": "招商银行",
    "600908": "无锡银行",
    "600919": "江苏银行",
    "600926": "杭州银行",
    "600928": "西安银行",
    "601009": "南京银行",
    "601077": "渝农商行",
    "601128": "常熟银行",
    "601166": "兴业银行",
    "601169": "北京银行",
    "601187": "厦门银行",
    "601229": "上海银行",
    "601288": "农业银行",
    "601328": "交通银行",
    "601398": "工商银行",
    "601528": "瑞丰银行",
    "601577": "长沙银行",
    "601658": "邮储银行",
    "601665": "齐鲁银行",
    "601818": "光大银行",
    "601825": "沪农商行",
    "601838": "成都银行",
    "601860": "紫金银行",
    "601916": "浙商银行",
    "601939": "建设银行",
    "601963": "重庆银行",
    "601988": "中国银行",
    "601997": "贵阳银行",
    "601998": "中信银行",
    "603323": "苏农银行",
}


def next_index(rows: list[dict], index: int, offset: int) -> int | None:
    target = index + offset
    return target if target < len(rows) else None


def bank_signals(
    code: str,
    years: int,
    near_ma5_pct: float = 1.5,
    cooldown_days: int = 10,
    cost_pct: float = 0.15,
) -> list[dict]:
    rows = indicators(ensure_daily(code, years=years, backfill=True))
    signals = []
    last_signal_index = -cooldown_days - 1
    for index in range(27, len(rows) - 21):
        current = rows[index]
        previous = rows[index - 1]
        older = rows[index - 2]
        if not current["ma5"] or not current["ma20"] or not previous["ma5"]:
            continue
        below_ma20 = current["close"] < current["ma20"]
        green_shrinking = (
            current["macd_hist"] < 0
            and current["macd_hist"] > previous["macd_hist"] > older["macd_hist"]
        )
        crossed_ma5 = current["close"] >= current["ma5"] and previous["close"] < previous["ma5"]
        near_ma5 = abs(current["close"] - current["ma5"]) / current["ma5"] * 100 <= near_ma5_pct
        if not (below_ma20 and green_shrinking and (crossed_ma5 or near_ma5)):
            continue
        if index - last_signal_index <= cooldown_days:
            continue
        if current["dif"] >= 0 and current["dea"] >= 0:
            axis = "above_zero"
        elif current["dif"] < 0 and current["dea"] < 0:
            axis = "below_zero"
        else:
            axis = "mixed"
        entry_index = next_index(rows, index, 1)
        if entry_index is None:
            continue
        entry = rows[entry_index]["open"]
        item = {
            "code": code,
            "name": BANKS.get(code, code),
            "signal_date": current["trade_date"],
            "entry_date": rows[entry_index]["trade_date"],
            "axis": axis,
            "entry": entry,
            "ma5_gap": (current["close"] - current["ma5"]) / current["ma5"] * 100,
            "ma20_gap": (current["close"] - current["ma20"]) / current["ma20"] * 100,
        }
        future_lows = []
        for horizon in (5, 10, 20):
            exit_index = next_index(rows, entry_index, horizon)
            if exit_index is None:
                break
            item[f"ret_{horizon}d"] = (rows[exit_index]["close"] - entry) / entry * 100 - cost_pct
            future_lows.extend(row["low"] for row in rows[entry_index : exit_index + 1])
            item[f"mae_{horizon}d"] = (min(future_lows) - entry) / entry * 100
        signals.append(item)
        last_signal_index = index
    return signals


def cmd_backtest_bank(args: argparse.Namespace) -> int:
    init_db()
    all_signals = []
    failed = []
    for index, code in enumerate(BANKS, 1):
        try:
            signals = bank_signals(
                code,
                args.years,
                args.near_ma5_pct,
                args.cooldown_days,
                args.cost_pct,
            )
            all_signals.extend(signals)
            print(f"[{index:02d}/{len(BANKS)}] {code} {BANKS[code]}: {len(signals)} signals", file=sys.stderr)
        except Exception as exc:
            failed.append((code, str(exc)))
            print(f"[WARN] {code}: {exc}", file=sys.stderr)

    metrics = {}
    print("银行焚诀回测 | 决策日收盘确认，下一交易日开盘成交")
    print("条件：股价在MA20下；MACD绿柱连续两日缩短；回到/靠近MA5。")
    for axis in ("above_zero", "below_zero", "mixed"):
        group = [row for row in all_signals if row["axis"] == axis]
        label = {"above_zero": "零轴上", "below_zero": "零轴下", "mixed": "零轴混合"}[axis]
        metrics[axis] = {}
        print(f"\n{label} | 样本 {len(group)}")
        for horizon in (5, 10, 20):
            values = [row[f"ret_{horizon}d"] for row in group if f"ret_{horizon}d" in row]
            stats = summarize_returns(values)
            metrics[axis][f"{horizon}d"] = stats
            if stats["count"]:
                print(
                    f"  {horizon:02d}日: 胜率 {stats['win_rate']:.1%} | "
                    f"均值 {stats['avg_return']:+.2f}% | 中位 {stats['median_return']:+.2f}% | "
                    f"盈亏因子 {stats['profit_factor']:.2f}"
                )
    metrics["failed"] = failed
    record_run(
        "bank_macd_ma5_reclaim",
        all_signals,
        metrics,
        {
            "years": args.years,
            "near_ma5_pct": args.near_ma5_pct,
            "cooldown_days": args.cooldown_days,
            "cost_pct": args.cost_pct,
            "entry": "next_open",
        },
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"metrics": metrics, "signals": all_signals}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n明细已写入 {output}；失败标的 {len(failed)}。")
    return 0


def load_pool_files(root: Path) -> list[tuple[str, list[dict]]]:
    output = []
    for path in sorted(root.glob("pool_20*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        pool_date = str(payload.get("date") or path.stem.removeprefix("pool_"))
        rows = [
            row
            for row in payload.get("results", [])
            if row.get("code") and is_main_board(str(row["code"]))
        ]
        output.append((pool_date, rows))
    return output


def find_trade_index(rows: list[dict], date_text: str) -> int | None:
    normalized = f"{date_text[:4]}-{date_text[4:6]}-{date_text[6:8]}"
    for index, row in enumerate(rows):
        if row["trade_date"] == normalized:
            return index
    return None


def cmd_backtest_pool(args: argparse.Namespace) -> int:
    pools = load_pool_files(Path(args.root))
    codes = sorted({normalize_code(row["code"]) for _, rows in pools for row in rows})
    daily = {}
    for index, code in enumerate(codes, 1):
        try:
            daily[code] = ensure_daily(code, years=args.years)
        except Exception as exc:
            print(f"[WARN] {code}: {exc}", file=sys.stderr)
        if index % 25 == 0:
            print(f"[{index}/{len(codes)}] daily cache ready", file=sys.stderr)

    signals = []
    for pool_date, rows in pools:
        sector_counts = defaultdict(int)
        for row in rows:
            sector_counts[row.get("sector") or "未分类"] += 1
        for row in rows:
            code = normalize_code(row["code"])
            bars = daily.get(code) or []
            base_index = find_trade_index(bars, pool_date)
            if base_index is None or base_index + 1 >= len(bars):
                continue
            entry_row = bars[base_index + 1]
            entry = entry_row["open"]
            item = {
                "code": code,
                "name": row.get("name") or code,
                "sector": row.get("sector") or "未分类",
                "signal_date": bars[base_index]["trade_date"],
                "entry_date": entry_row["trade_date"],
                "entry": entry,
                "pool_pct": float(row.get("pct") or 0),
                "pool_amount_yi": float(row.get("amount_yi") or 0),
                "sector_breadth": sector_counts[row.get("sector") or "未分类"],
                "line_signal": row.get("line_signal") or "",
            }
            for horizon in (1, 3, 5):
                exit_index = base_index + 1 + horizon
                if exit_index < len(bars):
                    item[f"ret_{horizon}d"] = (bars[exit_index]["close"] - entry) / entry * 100
            signals.append(item)

    print("焚诀历史池回测 | 每个历史 pool 只预测下一交易日，避免使用最新池回看过去")
    metrics = {}
    variants = {
        "all": lambda row: True,
        "breadth_3": lambda row: row["sector_breadth"] >= 3,
        "breadth_5": lambda row: row["sector_breadth"] >= 5,
        "breadth_3_amount_20": lambda row: row["sector_breadth"] >= 3 and row["pool_amount_yi"] >= 20,
    }
    for name, predicate in variants.items():
        group = [row for row in signals if predicate(row)]
        metrics[name] = {}
        print(f"\n{name} | 样本 {len(group)}")
        for horizon in (1, 3, 5):
            values = [row[f"ret_{horizon}d"] for row in group if f"ret_{horizon}d" in row]
            stats = summarize_returns(values)
            metrics[name][f"{horizon}d"] = stats
            if stats["count"]:
                print(
                    f"  {horizon}日: 胜率 {stats['win_rate']:.1%} | "
                    f"均值 {stats['avg_return']:+.2f}% | 中位 {stats['median_return']:+.2f}%"
                )
    record_run("historical_pool_oos", signals, metrics, {"entry": "next_open", "pool_files": len(pools)})
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"metrics": metrics, "signals": signals}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n覆盖历史池 {len(pools)} 个、股票 {len(codes)} 只；明细 {output}")
    return 0


def cmd_theme(args: argparse.Namespace) -> int:
    pools = load_pool_files(Path(args.root))
    index_rows = indicators(ensure_daily("sh000001", years=args.years))
    index_map = {row["trade_date"].replace("-", ""): row for row in index_rows}
    previous = None
    print("上证MA20共振题材 | 仅识别候选，不把事后龙虎榜数据混入盘中信号")
    events = []
    for pool_date, rows in pools:
        market = index_map.get(pool_date)
        if not market or not market["ma20"]:
            previous = (pool_date, rows)
            continue
        market_index = next(
            (index for index, row in enumerate(index_rows) if row["trade_date"].replace("-", "") == pool_date),
            None,
        )
        prior_market = index_rows[market_index - 1] if market_index is not None and market_index > 0 else None
        reclaimed = bool(
            prior_market
            and prior_market["ma20"]
            and prior_market["close"] < prior_market["ma20"]
            and market["close"] >= market["ma20"]
        )
        distance = (market["close"] - market["ma20"]) / market["ma20"] * 100
        near_reclaim = -args.near_pct <= distance <= args.near_pct
        if not (reclaimed or near_reclaim):
            previous = (pool_date, rows)
            continue
        old_counts = defaultdict(int)
        if previous:
            for row in previous[1]:
                old_counts[row.get("sector") or "未分类"] += 1
        new_counts = defaultdict(int)
        amount = defaultdict(float)
        leaders = defaultdict(list)
        for row in rows:
            sector = row.get("sector") or "未分类"
            new_counts[sector] += 1
            amount[sector] += float(row.get("amount_yi") or 0)
            leaders[sector].append(row)
        candidates = []
        for sector, count in new_counts.items():
            expansion = count / max(1, old_counts.get(sector, 0))
            if count < args.min_breadth:
                continue
            score = count * 2 + min(expansion, 4) * 2 + min(amount[sector] / 50, 5)
            candidates.append((score, sector, count, expansion, amount[sector]))
        candidates.sort(reverse=True)
        if candidates:
            event = {
                "date": pool_date,
                "index_close": market["close"],
                "index_ma20": market["ma20"],
                "index_ma20_distance_pct": distance,
                "reclaimed_today": reclaimed,
                "themes": [
                    {
                        "sector": sector,
                        "breadth": count,
                        "expansion": expansion,
                        "amount_yi": sector_amount,
                        "leaders": [
                            f"{normalize_code(row['code'])}{row.get('name','')}"
                            for row in sorted(
                                leaders[sector],
                                key=lambda item: float(item.get("amount_yi") or 0),
                                reverse=True,
                            )[:3]
                        ],
                    }
                    for _, sector, count, expansion, sector_amount in candidates[:5]
                ],
            }
            events.append(event)
            print(
                f"{pool_date} | 上证 {market['close']:.2f} / MA20 {market['ma20']:.2f} | "
                + "；".join(
                    f"{item['sector']} 宽度{item['breadth']} 扩张{item['expansion']:.1f}x"
                    for item in event["themes"][:3]
                )
            )
        previous = (pool_date, rows)
    print(f"\n找到 {len(events)} 个靠近/收复MA20的历史观察点。样本不足时不得宣称高胜率。")
    Path(args.output).write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


def cmd_backtest_intraday(args: argparse.Namespace) -> int:
    snapshot_dir = Path(args.snapshot_dir)
    signals = []
    tested_days = 0
    for current_path in sorted(snapshot_dir.glob("snapshot_20*_0940.json")):
        payload = json.loads(current_path.read_text(encoding="utf-8"))
        quote_date = str(payload.get("quote_date") or current_path.stem.split("_")[1])
        if not payload.get("market_gate_ok"):
            continue
        early_path = snapshot_dir / f"snapshot_{quote_date}_0925.json"
        if not early_path.exists():
            continue
        early_payload = json.loads(early_path.read_text(encoding="utf-8"))
        pool_name = str(payload.get("pool") or "")
        pool_path = ROOT / pool_name
        if not pool_path.exists():
            continue
        pool = json.loads(pool_path.read_text(encoding="utf-8")).get("results", [])
        rank_args = argparse.Namespace(min_pct=2.0, max_pct=8.5, max_ma20_gap=35.0)
        ranked = rank_candidates(
            pool,
            payload.get("quotes") or {},
            rank_args,
            early_payload.get("quotes") or {},
        )
        attack = rank_attack_candidates(ranked, args.limit)
        tested_days += 1
        for track, candidates in (("trend", ranked[: args.limit]), ("attack", attack[: args.limit])):
            for rank, row in enumerate(candidates, 1):
                code = normalize_code(row["code"])
                bars = ensure_daily(code, years=3)
                day_index = find_trade_index(bars, quote_date)
                if day_index is None:
                    continue
                entry = float(row["price"])
                item = {
                    "track": track,
                    "rank": rank,
                    "code": code,
                    "name": row["name"],
                    "sector": row["sector"],
                    "signal_date": bars[day_index]["trade_date"],
                    "entry": entry,
                    "market_gate": payload.get("market_gate_text"),
                }
                item["ret_close"] = (bars[day_index]["close"] - entry) / entry * 100 - args.cost_pct
                if day_index + 1 < len(bars):
                    item["ret_next_close"] = (
                        (bars[day_index + 1]["close"] - entry) / entry * 100 - args.cost_pct
                    )
                signals.append(item)

    print("焚诀 9:40 快照回测 | 只使用当时保存的行情与股票池")
    metrics = {}
    for track in ("attack", "trend"):
        for top_n in (1, 3, args.limit):
            group = [row for row in signals if row["track"] == track and row["rank"] <= top_n]
            key = f"{track}_top{top_n}"
            metrics[key] = {}
            print(f"\n{key} | {len(group)} 条 / {tested_days} 个通过大盘闸门的交易日")
            for field, label in (("ret_close", "当日收盘"), ("ret_next_close", "次日收盘")):
                values = [row[field] for row in group if field in row]
                stats = summarize_returns(values)
                metrics[key][field] = stats
                if stats["count"]:
                    print(
                        f"  {label}: 胜率 {stats['win_rate']:.1%} | "
                        f"均值 {stats['avg_return']:+.2f}% | 中位 {stats['median_return']:+.2f}%"
                    )
    record_run(
        "intraday_0940_replay",
        signals,
        metrics,
        {"cost_pct": args.cost_pct, "limit": args.limit, "entry": "snapshot_0940_price"},
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"metrics": metrics, "signals": signals}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n有效交易日 {tested_days}，明细 {output}")
    return 0


def cmd_live(args: argparse.Namespace) -> int:
    codes = [normalize_code(code) for code in args.codes]
    quotes = fetch_realtime(codes, verify=not args.no_verify)
    if args.save:
        save_snapshot(quotes)
    for code in codes:
        row = quotes.get(code)
        if not row:
            print(f"{code} | 无数据")
            continue
        print(
            f"{code} {row['name']} | {row['price']:.2f} {row['pct']:+.2f}% | "
            f"{row['source']} / {row.get('quality','unknown')} | "
            f"{row['trade_date']} {row['quote_time']}"
        )
    return 0


def cmd_status(_: argparse.Namespace) -> int:
    init_db()
    import sqlite3

    conn = sqlite3.connect(DB_PATH)
    daily = conn.execute("SELECT COUNT(*), COUNT(DISTINCT code), MIN(trade_date), MAX(trade_date) FROM daily_bars").fetchone()
    quotes = conn.execute("SELECT COUNT(*), MIN(trade_date), MAX(trade_date) FROM quote_snapshots").fetchone()
    runs = conn.execute("SELECT strategy, COUNT(*), MAX(run_at) FROM strategy_runs GROUP BY strategy").fetchall()
    conn.close()
    print(f"DB: {DB_PATH} ({DB_PATH.stat().st_size / 1024 / 1024:.1f} MiB)")
    print(f"日线: {daily[0]}行 / {daily[1]}只 / {daily[2]}~{daily[3]}")
    print(f"快照: {quotes[0]}行 / {quotes[1]}~{quotes[2]}")
    for row in runs:
        print(f"回测: {row[0]} {row[1]}次，最近 {row[2]}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fenjue research and cache tools")
    sub = parser.add_subparsers(dest="command", required=True)

    live = sub.add_parser("live", help="Dual-source realtime quote")
    live.add_argument("codes", nargs="+")
    live.add_argument("--no-verify", action="store_true")
    live.add_argument("--save", action="store_true")
    live.set_defaults(func=cmd_live)

    bank = sub.add_parser("backtest-bank", help="Backtest bank MACD/MA5 setup")
    bank.add_argument("--years", type=int, default=5)
    bank.add_argument("--near-ma5-pct", type=float, default=1.5)
    bank.add_argument("--cooldown-days", type=int, default=10)
    bank.add_argument("--cost-pct", type=float, default=0.15)
    bank.add_argument("--output", default="/opt/data/fenjue/data/bank_strategy_backtest.json")
    bank.set_defaults(func=cmd_backtest_bank)

    pool = sub.add_parser("backtest-pool", help="Backtest each historical pool out of sample")
    pool.add_argument("--root", default=str(ROOT))
    pool.add_argument("--years", type=int, default=5)
    pool.add_argument("--output", default="/opt/data/fenjue/data/pool_oos_backtest.json")
    pool.set_defaults(func=cmd_backtest_pool)

    theme = sub.add_parser("theme-resonance", help="Find themes resonating with an index MA20 reclaim")
    theme.add_argument("--root", default=str(ROOT))
    theme.add_argument("--years", type=int, default=5)
    theme.add_argument("--near-pct", type=float, default=0.8)
    theme.add_argument("--min-breadth", type=int, default=3)
    theme.add_argument("--output", default="/opt/data/fenjue/data/theme_resonance.json")
    theme.set_defaults(func=cmd_theme)

    intraday = sub.add_parser("backtest-intraday", help="Replay saved 09:25/09:40 snapshots")
    intraday.add_argument("--snapshot-dir", default="/opt/data/fenjue/snapshots")
    intraday.add_argument("--limit", type=int, default=5)
    intraday.add_argument("--cost-pct", type=float, default=0.15)
    intraday.add_argument("--output", default="/opt/data/fenjue/data/intraday_0940_backtest.json")
    intraday.set_defaults(func=cmd_backtest_intraday)

    clean = sub.add_parser("retention", help="Apply bounded storage retention")
    clean.add_argument("--intraday-days", type=int, default=120)
    clean.add_argument("--daily-years", type=int, default=5)
    clean.set_defaults(func=lambda args: print(retention(args.intraday_days, args.daily_years)) or 0)

    status = sub.add_parser("status")
    status.set_defaults(func=cmd_status)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
