#!/usr/bin/env python3
"""全主板日K补拉（新浪源，datalen=300 覆盖 2026 全年）——baostock 被限流后的替代。"""
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine.console import kline_sina, clear_proxy

ROOT = Path("/opt/data/fenjue")
KC = ROOT / "data" / "big_kcache"

def main():
    clear_proxy()
    stocks = json.loads((ROOT / "data" / "main_board_codes.json").read_text())["stocks"]
    codes = [str(s["code"]).zfill(6) for s in stocks]
    todo = []
    for c in codes:
        f = KC / f"{c}.json"
        if not f.exists():
            todo.append(c)
        else:
            d = json.loads(f.read_text())
            if d and d[-1]["date"] < "2026-07-01":  # 旧缓存只到7月也要补
                todo.append(c)
    print(f"待拉 {len(todo)}", flush=True)
    t0 = time.time()
    for i, c in enumerate(todo):
        try:
            ks = kline_sina(("sh" if c.startswith("6") else "sz") + c, 300)
            rows = [{"date": k["day"], "open": float(k["open"]), "high": float(k["high"]),
                     "low": float(k["low"]), "close": float(k["close"]), "volume": float(k["volume"])}
                    for k in ks]
            if len(rows) >= 30:
                (KC / f"{c}.json").write_text(json.dumps(rows))
        except Exception as e:
            print(f"{c} fail {str(e)[:50]}", flush=True)
        if i % 200 == 199:
            print(f"  {i+1}/{len(todo)} {(time.time()-t0)/60:.0f}min", flush=True)
        time.sleep(0.05)
    print(f"完成 {(time.time()-t0)/60:.0f}min", flush=True)

if __name__ == "__main__":
    main()
