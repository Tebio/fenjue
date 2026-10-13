#!/usr/bin/env python3
"""交易日历（官方口径，含未来交易日）——金股线入场日等依赖它。

为什么不复用 data/index_sh000001.json：那份日历由 update_kcache.py 末尾的
update_index() 写，尾部 = 最近一个【bar 已落盘】的交易日 → 天然滞后一天
（当天 bar 要当晚 19:40 补跑才进缓存）。
金股线的入场日 = 当月第 6 个交易日，必须【月初就算得出来】；吃滞后日历会把
2026-10-15 的入场日拖到 10-16 才标出来 = 白白错一天（2026-10-08 修）。

来源：baostock query_trade_dates（官方日历，含未来日期）。
缓存：data/trade_calendar/<year>.json，TTL 7 天；baostock 挂时用缓存，再没有返回空
（调用方自己退回旧口径，绝不猜节假日）。
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, "/opt/data/python-libs")

ROOT = Path("/opt/data/fenjue")
CACHE_DIR = ROOT / "data/trade_calendar"
TTL_SECONDS = 7 * 86400


def _cache_path(year: int) -> Path:
    return CACHE_DIR / f"{year}.json"


def _fetch_official(year: int) -> list[str] | None:
    """baostock 官方日历（含全年未来交易日）。任何异常都返回 None，不抛。"""
    try:
        import baostock as bs

        lg = bs.login()
        if lg.error_code != "0":
            return None
        rs = bs.query_trade_dates(start_date=f"{year}-01-01", end_date=f"{year}-12-31")
        days = []
        while rs.error_code == "0" and rs.next():
            row = rs.get_row_data()
            if row[1] == "1":
                days.append(row[0])
        bs.logout()
        return days or None
    except Exception:
        try:
            import baostock as bs

            bs.logout()
        except Exception:
            pass
        return None


def trading_days(year: int) -> list[str]:
    """该年全部官方交易日（升序，含未来）。"""
    fp = _cache_path(year)
    if fp.exists() and (time.time() - fp.stat().st_mtime) < TTL_SECONDS:
        return json.loads(fp.read_text())
    days = _fetch_official(year)
    if days:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        fp.write_text(json.dumps(days))
        return days
    return json.loads(fp.read_text()) if fp.exists() else []


def month_days(ym: str) -> list[str]:
    """该月官方交易日列表（含未来）。ym 形如 '2026-10'。"""
    return [d for d in trading_days(int(ym[:4])) if d.startswith(ym)]


def entry_day(ym: str, n: int = 6) -> str | None:
    """该月第 n 个交易日（金股线入场日）。日历不可用 → None。"""
    days = month_days(ym)
    return days[n - 1] if len(days) >= n else None


def is_trading_day(day: str) -> bool:
    return day in set(trading_days(int(day[:4])))


def next_month(ym: str) -> str:
    y, m = int(ym[:4]), int(ym[5:7]) + 1
    return f"{y + 1}-01" if m > 12 else f"{y}-{m:02d}"


def bjt_today() -> str:
    """北京日期（容器是 UTC，别用 date.today()）。"""
    return (datetime.now(timezone.utc) + timedelta(hours=8)).date().isoformat()


if __name__ == "__main__":
    ym = sys.argv[1] if len(sys.argv) > 1 else bjt_today()[:7]
    ds = month_days(ym)
    print(f"{ym}: {len(ds)} 个交易日 → {ds}")
    print(f"入场日（第6个）= {entry_day(ym)}")
