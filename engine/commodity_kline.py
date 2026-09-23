"""商品期货日K采集器（2026-09-23，源：a-stock-data SKILL.md 抄录+实测校准）。

源=新浪 InnerFuturesNewService.getDailyKLine（GBK JSONP），主力连续代码 XX0。
实测（2026-09-23）：CU0 5286 根（2005 起）、AU0 4559 根（2008 起）、LC0 772 根（2023-07 起）。
用途：商品价格超预期研究（洛阳钼业型：商品价格突破→资源股）的数据底座。
缓存 data/commodity/<SYM>.json（全量覆盖写，源即全历史）。cron 每交易日 17:30 增量。
"""
import json
import re
import sys
import time
from pathlib import Path

import requests

ROOT = Path("/opt/data/fenjue")
OUT = ROOT / "data" / "commodity"
OUT.mkdir(exist_ok=True)

# A股映射相关的品种（主力连续）
SYMBOLS = {
    "CU0": "沪铜", "AL0": "沪铝", "ZN0": "沪锌", "NI0": "沪镍", "PB0": "沪铅",
    "AU0": "黄金", "AG0": "白银", "LC0": "碳酸锂", "RB0": "螺纹钢",
    "I0": "铁矿石", "M0": "豆粕", "SC0": "原油", "CF0": "棉花", "SR0": "白糖",
    "MA0": "甲醇", "TA0": "PTA", "FG0": "玻璃", "SA0": "纯碱",
}

URL = ("https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20_{code}="
       "/InnerFuturesNewService.getDailyKLine?symbol={code}")
HEADERS = {"Referer": "https://finance.sina.com.cn/", "User-Agent": "Mozilla/5.0"}


def fetch(sym: str) -> list[dict]:
    r = requests.get(URL.format(code=sym), headers=HEADERS, timeout=20)
    text = r.content.decode("gbk", "replace")
    m = re.search(rf"var _{re.escape(sym)}=\((\[.*?\])\)", text, re.S)
    if not m:
        raise RuntimeError(f"{sym} 返回非预期 JSONP")
    body = m.group(1).strip()
    if body == "null":
        raise ValueError(f"{sym} 无数据")
    rows = []
    seen = set()
    for it in json.loads(body):
        day = it["d"] if "-" in str(it["d"]) else str(it["d"])
        day = day.replace("/", "-")
        if day in seen:
            raise RuntimeError(f"{sym} {day} 重复")
        seen.add(day)
        rows.append({"date": day, "open": float(it["o"]), "high": float(it["h"]),
                     "low": float(it["l"]), "close": float(it["c"]),
                     "volume": float(it.get("v") or 0)})
    return rows


def main():
    only = sys.argv[1:] or list(SYMBOLS)
    ok, fail = [], []
    for sym in only:
        try:
            rows = fetch(sym)
            (OUT / f"{sym}.json").write_text(json.dumps(
                {"symbol": sym, "name": SYMBOLS.get(sym, sym), "rows": rows}, ensure_ascii=False))
            ok.append(f"{sym}({SYMBOLS.get(sym, sym)}) {len(rows)}根 {rows[0]['date']}~{rows[-1]['date']}")
        except Exception as e:
            fail.append(f"{sym}: {str(e)[:80]}")
        time.sleep(0.4)
    print("✅", " | ".join(ok))
    if fail:
        print("❌", " | ".join(fail))


if __name__ == "__main__":
    main()
