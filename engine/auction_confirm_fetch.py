#!/usr/bin/env python3
"""engine/auction_confirm_fetch.py — 竞价确认回测的竞价数据回填（卡 t_85004326 ①）。

目标：DEEP（深档低位v2 出手票）事件集 T+1 日的竞价字段（竞价涨幅/量/金额/未匹配量/异动类型），
供「竞价强度连续版」分析。WIDE 12 万只/LD 4800 只超出问财日配额（~100-150 次/日，滚动 24h），
不回填——它们的竞价强度主变量=竞价涨幅=日K 开盘 gap，已在 auction_confirm_backtest 全量覆盖；
竞价量维度只在 DEEP 子集上测增量。

通道：问财逐票逐日查询（「YYYY年M月D日 <名称> 集合竞价」，2026-10-16 实测字段三源校准过）。
PIT 纪律：缓存 data/research/auction_deep/<entry_date>.json，历史日不可变不重拉（--force 除外），
原子写 + _meta 锚（复用 datawall_fetcher）。QuotaExhausted → 断点退出，配额重置后重跑（幂等）。

用法：.venv/bin/python engine/auction_confirm_fetch.py [--limit N] [--force]
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from datawall_fetcher import (QuotaExhausted, _meta, _wencai_query, atomic_write,  # noqa: E402
                              cached_path)

ROOT = Path("/opt/data/fenjue")
EVENTS = json.loads((ROOT / "data" / "auction_confirm_events_20261016.json").read_text())
KIND = "auction_deep"


def fetch_one(code: str, name: str, day: str) -> dict:
    y, m, d = int(day[:4]), int(day[5:7]), int(day[8:10])
    day8 = day.replace("-", "")
    j = _wencai_query(f"{y}年{m}月{d}日 {name} 集合竞价", limit=5)
    if not j.get("success"):
        raise RuntimeError(f"wencai failed: {str(j)[:150]}")
    rows = [r for r in (j.get("datas") or [])
            if (r.get("股票代码") or "").split(".")[0] == code]
    if not rows:
        return {"code": code, "date": day, "found": False}
    r = rows[0]

    def g(k):
        return r.get(f"{k}[{day8}]")

    pct = g("竞价涨幅")
    return {"code": code, "name": r.get("股票简称"), "date": day, "found": True,
            "auction_price": g("竞价匹配价"), "auction_volume": g("竞价量"),
            "auction_amount": g("竞价金额"),
            "auction_pct": (pct / 100.0) if isinstance(pct, (int, float)) else None,
            "unmatched_volume": g("竞价未匹配量"), "unmatched_amount": g("竞价未匹配金额"),
            "abnormal_type": g("竞价异动类型"), "auction_rating": g("竞价评级")}


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="最多拉取多少只（0=不限）")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    # 目标事件集：DEEP 全史（簇日出手的深跌件）——按 entry_date 分组缓存
    events = EVENTS["DEEP"]
    by_day = {}
    for e in events:
        by_day.setdefault(e["entry_date"], []).append(e)
    # 名称映射：big_kcache 无名，从 industry_map / 腾讯快照补；问财按代码也能查但 NL 带名更稳
    names = {}
    try:
        ind = json.loads((ROOT / "data" / "industry_map.json").read_text())
        names = {str(k).zfill(6): (v.get("name") if isinstance(v, dict) else None) for k, v in ind.items()}
    except Exception:
        pass

    done = pulled = skipped = 0
    for day in sorted(by_day):
        p = cached_path(KIND, day)
        if p.exists() and not args.force:
            done += 1
            continue
        items = []
        for e in by_day[day]:
            code = e["code"]
            nm = names.get(code) or code
            try:
                items.append(fetch_one(code, nm, day))
                pulled += 1
            except QuotaExhausted:
                print(f"QUOTA_EXHAUSTED @ {day}（已落盘 {done+pulled} 事件日，断点={day}，配额重置后重跑）",
                      flush=True)
                return
            except Exception as ex:
                items.append({"code": code, "date": day, "found": False,
                              "error": f"{type(ex).__name__}: {ex}"})
                skipped += 1
            time.sleep(1.2)   # 配额限速纪律
            if args.limit and pulled >= args.limit:
                break
        obj = {"date": day, "source": "iwencai_per_stock_auction", "n": len(items),
               "items": items,
               "_meta": _meta("engine.auction_confirm_fetch", [str(EVENTS and 'auction_confirm_events_20261016.json')], day)}
        atomic_write(p, obj)
        print(f"{day}: n={len(items)} -> {p}", flush=True)
        if args.limit and pulled >= args.limit:
            print(f"--limit {args.limit} 到达，停。", flush=True)
            return
    print(f"完成：{len(by_day)} 事件日（命中缓存 {done}，新拉 {pulled}，异常 {skipped}）", flush=True)


if __name__ == "__main__":
    main()
