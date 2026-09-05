#!/usr/bin/env python3
"""engine/dividend_universe.py — 高股息全宇宙扫描 (2026-09-06)

不再靠人脑列板块：中证红利(100) ∪ 红利低波(50) 官方指数成分股兜底，
每票算股息率锚价格带（买入4.5%/卖出4.0%/清仓3.0%），按当前息率排序输出。
首次拉分红明细较慢（~150 票），磁盘缓存 7 天。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, "/opt/data/python-libs")
from engine.console import (bands_from_dividend, clear_proxy, dividend_ttm,  # noqa: E402
                            ladder, tencent_quotes, zone_of)

CACHE = ROOT / "data" / "dividend_universe.json"


def fetch_universe() -> list[dict]:
    import akshare as ak
    stocks: dict[str, str] = {}
    for idx in ("000922", "H30269"):
        df = ak.index_stock_cons_csindex(symbol=idx)
        for _, row in df.iterrows():
            code = str(row["成分券代码"]).zfill(6)
            if code.startswith(("600", "601", "603", "605", "000", "001", "002")):
                stocks.setdefault(code, str(row["成分券名称"]))
    return [{"code": c, "name": n} for c, n in sorted(stocks.items())]


def scan() -> dict:
    clear_proxy()
    uni = fetch_universe()
    quotes = tencent_quotes([s["code"] for s in uni])
    rows = []
    for s in uni:
        q = quotes.get(s["code"])
        if not q:
            continue
        dps = dividend_ttm(s["code"])
        if not dps:
            continue
        yld = round(dps / q["price"] * 100, 2)
        bands = bands_from_dividend(dps)
        zone, action = zone_of(q["price"], bands)
        rows.append({"code": s["code"], "name": q["name"], "price": q["price"], "pct": q["pct"],
                     "yield": yld, "zone": zone, "action": action, "bands": bands,
                     "ladder": ladder(bands),
                     "dist_to_buy%": round((bands["buy"] / q["price"] - 1) * 100, 1)})
    rows.sort(key=lambda r: r["yield"], reverse=True)
    return {"count": len(rows), "rows": rows}


def render(data: dict) -> str:
    lines = [f"💰 高股息全宇宙（中证红利∪红利低波，{data['count']} 只有分红数据）", ""]
    for zone in ("买入区", "持有区", "卖出区", "清仓区"):
        group = [r for r in data["rows"] if r["zone"] == zone]
        if not group:
            continue
        lines.append(f"── {zone}（{len(group)} 只）──")
        for r in group:
            b = r["bands"]
            lines.append(f"{r['name']}({r['code']}) {r['price']} 息率{r['yield']}% | "
                         f"买≤{b['buy']} 卖{b['sell']} 清≥{b['clear']} | 距买入{r['dist_to_buy%']:+.1f}%")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    data = scan()
    CACHE.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    print(render(data))
    print(f"写入 {CACHE}")
