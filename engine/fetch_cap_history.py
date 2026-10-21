#!/usr/bin/env python3
"""engine/fetch_cap_history.py — 历史流通市值重建 (2026-09-06)

销 AGENTS.md 欠账 #4：regime_backtest 用 2026-09-04 市值快照当常数。
方法：baostock 不复权日线带 turn（换手率%），流通股本 = volume/(turn/100)，
流通市值(亿) = close * 流通股本 / 1e8。逐股写 data/cap_hist/{code}.json。
断点续跑；与 refetch_qfq.py 同款温柔策略（1s/只 + 失败退避）。

增量周更（2026-10-21 #354，--update 模式）：
    python3 engine/fetch_cap_history.py --update [limit]
    已有文件从末 bar 续抓到今天（重叠一天去重合并）；末端已是最新交易日跳过（幂等）。
    流通股本只在送转/增发时变，日更无必要 → 周六班（cron id 见注册表 owner）。
"""
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, "/opt/data/python-libs")
import baostock as bs  # noqa: E402

ROOT = Path("/opt/data/fenjue")
KC = ROOT / "data" / "big_kcache"
OUT = ROOT / "data" / "cap_hist"
OUT.mkdir(exist_ok=True)
START, END = "2019-01-01", "2026-09-18"

BJT = timezone(timedelta(hours=8))


def _today_bjt() -> str:
    return datetime.now(BJT).strftime("%Y-%m-%d")


def _latest_trading_day(today: str) -> str:
    """只读本地官方日历缓存；缺失 → 返回 today（不短路，宁多抓不猜）。#330-B 纪律。"""
    cal = ROOT / "data/trade_calendar" / f"{today[:4]}.json"
    try:
        days = json.loads(cal.read_text())
    except Exception:
        return today
    past = [d for d in days if d <= today]
    return past[-1] if past else today


def _tail_last_date(fp: Path) -> str | None:
    """单行 JSON 尾读取末 bar 日期（fetch_fundamentals._tail_last_date 同款）。"""
    try:
        with open(fp, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            if size <= 2:
                return ""
            f.seek(max(0, size - 300))
            tail = f.read().decode("utf-8", "ignore")
    except Exception:
        return None
    m = re.findall(r'"(\d{4}-\d{2}-\d{2})"', tail)
    return m[-1] if m else None


def _cap_rows(code: str, start: str, end: str) -> list:
    """抓 [date, close, 流通市值(亿)]；两次尝试（失败先睡 30s）。"""
    for attempt in range(2):
        try:
            rs = bs.query_history_k_data_plus(
                ("sh." if code.startswith("6") else "sz.") + code,
                "date,close,volume,turn",
                start_date=start, end_date=end, frequency="d", adjustflag="3")
            rows = []
            while rs.error_code == "0" and rs.next():
                r = rs.get_row_data()
                if not r[1] or not r[2] or not r[3]:
                    continue
                close, vol, turn = float(r[1]), float(r[2]), float(r[3])
                if turn <= 0 or close <= 0:
                    continue
                cap_yi = close * (vol / (turn / 100)) / 1e8
                rows.append([r[0], round(close, 3), round(cap_yi, 1)])
            return rows
        except Exception as e:
            if attempt == 0:
                time.sleep(30)
            else:
                print(f"{code} 两次失败 {str(e)[:40]}", flush=True)
    return []


def _write_atomic(fp: Path, rows: list) -> None:
    tmp = fp.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rows))
    os.replace(tmp, fp)


def update(limit: int | None = None, shard: str | None = None) -> int:
    """增量周更：只补每票末 bar 之后的缺口。shard='k/N' 分片（cron 3600s 墙钟纪律）。"""
    today = _today_bjt()
    latest_td = _latest_trading_day(today)
    codes = sorted(fp.stem for fp in KC.glob("*.json"))
    if shard:
        k, n = (int(x) for x in shard.split("/"))
        codes = codes[k::n]

    todo = []       # (code, start_date)
    skipped_fresh = skipped_empty = 0
    for c in codes:
        fp = OUT / f"{c}.json"
        if fp.exists():
            last = _tail_last_date(fp)
            if last == "":
                skipped_empty += 1
                continue
            if last is None:
                todo.append((c, START))
            elif last >= latest_td:
                skipped_fresh += 1
            else:
                todo.append((c, last))
        else:
            todo.append((c, START))

    print(f"cap update: today={today} latest_td={latest_td} shard={shard or '-'} "
          f"universe={len(codes)} "
          f"todo={len(todo)} fresh_skip={skipped_fresh} empty_skip={skipped_empty}", flush=True)
    if limit:
        todo = todo[:limit]
        print(f"  probe limit={limit} → todo={len(todo)}", flush=True)
    if not todo:
        print("done ok=0 fail=0 (all fresh)")
        return 0

    bs.login()
    t0 = time.time()
    ok = fails = 0
    for i, (code, start) in enumerate(todo):
        rows = _cap_rows(code, start, today)
        fp = OUT / f"{code}.json"
        is_full = (start == START)
        if rows:
            if is_full:
                # 全量补抓保留原完整性校验（<60% 对账不落盘）
                kc = KC / f"{code}.json"
                expected = len(json.loads(kc.read_text())) if kc.exists() else 0
                if expected >= 60 and len(rows) < expected * 0.6:
                    fails += 1
                    print(f"{code} 仅{len(rows)}/{expected}行（疑似截断），未落盘", flush=True)
                    time.sleep(0.6)
                    continue
                _write_atomic(fp, rows)
            else:
                old = json.loads(fp.read_text())
                merged = {r[0]: r for r in old}
                for r in rows:
                    merged[r[0]] = r
                _write_atomic(fp, [merged[d] for d in sorted(merged)])
            ok += 1
        else:
            fails += 1
            if is_full:
                print(f"{code} 0行未落盘（疑似限流）", flush=True)
            else:
                print(f"  ERR {code}: 增量 0 行（start={start}），保留旧文件", flush=True)
        time.sleep(0.6)
        if (i + 1) % 200 == 0:
            print(f"  {i+1}/{len(todo)} {(time.time()-t0)/60:.0f}min ok={ok} 失败{fails}", flush=True)
    bs.logout()
    print(f"done ok={ok} fail={fails} {(time.time()-t0)/60:.0f}min", flush=True)
    return 0


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--update":
        shard = limit = None
        for a in sys.argv[2:]:
            if "/" in a:
                shard = a
            else:
                limit = int(a)
        sys.exit(update(limit, shard))
    todo = []
    for f in sorted(KC.glob("*.json")):
        if (OUT / f"{f.stem}.json").exists():
            continue
        todo.append(f.stem)
    print(f"待拉 {len(todo)}", flush=True)
    bs.login()
    t0 = time.time()
    fails = 0
    for i, code in enumerate(todo):
        for attempt in range(2):
            try:
                rs = bs.query_history_k_data_plus(
                    ("sh." if code.startswith("6") else "sz.") + code,
                    "date,close,volume,turn",
                    start_date=START, end_date=END, frequency="d", adjustflag="3")
                rows = []
                while rs.error_code == "0" and rs.next():
                    r = rs.get_row_data()
                    if not r[1] or not r[2] or not r[3]:
                        continue
                    close, vol, turn = float(r[1]), float(r[2]), float(r[3])
                    if turn <= 0 or close <= 0:
                        continue
                    cap_yi = close * (vol / (turn / 100)) / 1e8
                    rows.append([r[0], round(close, 3), round(cap_yi, 1)])
                # 完整性校验（2026-09-06 外部审查发现#9）：跟 big_kcache 已有日K对账，
                # 行数明显少于预期 = 接口中途被限流截断，只警告不落盘，留给续跑重试。
                # 阈值 0.6：长期停牌股（盈方微 0.67/皇台 0.79，新浪含停牌日而 baostock 不含）
                # 天然偏低，0.8 会误杀它们。
                kc = KC / f"{code}.json"
                expected = len(json.loads(kc.read_text())) if kc.exists() else 0
                if expected >= 60 and 0 < len(rows) < expected * 0.6:
                    fails += 1
                    print(f"{code} 仅{len(rows)}/{expected}行（疑似截断），未落盘", flush=True)
                elif len(rows) >= 60:
                    (OUT / f"{code}.json").write_text(json.dumps(rows))
                elif len(rows) > 0:
                    (OUT / f"{code}.json").write_text(json.dumps(rows))
                    print(f"{code} 仅{len(rows)}行（新股/数据短）", flush=True)
                else:
                    # 0 行 = 接口异常/限流，不落盘，留给下次续跑重试
                    fails += 1
                    print(f"{code} 0行未落盘（疑似限流）", flush=True)
                break
            except Exception as e:
                if attempt == 0:
                    time.sleep(30)
                else:
                    fails += 1
                    print(f"{code} 两次失败 {str(e)[:40]}", flush=True)
        time.sleep(0.6)
        if i % 200 == 199:
            print(f"  {i+1}/{len(todo)} {(time.time()-t0)/60:.0f}min 失败{fails}", flush=True)
    bs.logout()
    print(f"完成 {(time.time()-t0)/60:.0f}min 失败 {fails}", flush=True)


if __name__ == "__main__":
    main()
