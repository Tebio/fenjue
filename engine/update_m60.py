#!/usr/bin/env python3
"""engine/update_m60.py — 60分钟K线库（Sina 通道，60分钟级盘中研究底座）

深度现实（2026-09-12 探针实证）：baostock 分钟线无深度（2019=0行），
腾讯 mkline 被拦，Sina getKLineData scale=60 datalen=1970 ≈ 2 年（4根/日）。
策略：首跑全量回填 2 年，之后每日 cron 增量（datalen=16 覆盖当日）。
存储：data/m60_cache/<code>.json，行={day,open,high,low,close,volume}（Sina 原生字段 day 含时分）。
用法：python3 engine/update_m60.py [full|delta]   # 默认 delta
"""
import json, subprocess, sys, time
from pathlib import Path

CACHE = Path("/opt/data/fenjue/data/m60_cache")
CACHE.mkdir(exist_ok=True)
KC = Path("/opt/data/fenjue/data/big_kcache")
URL = ("https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
       "CN_MarketData.getKLineData?symbol={sym}&scale=60&ma=no&datalen={n}")


def fetch(sym, n, retries=4):
    """新浪限流对抗：失败退避 5s×2^k，连续失败触发全局冷却。"""
    for k in range(retries):
        r = subprocess.run(["curl", "-sL", "--max-time", "15",
                            "-H", "Referer: https://finance.sina.com.cn/", URL.format(sym=sym, n=n)],
                           capture_output=True, text=True,
                           env={"PATH": "/usr/bin:/bin"})
        try:
            rows = json.loads(r.stdout)
            if rows:
                return rows
        except Exception:
            pass
        time.sleep(5 * (2 ** k))
    return []


def main():
    full = len(sys.argv) > 1 and sys.argv[1] == "full"
    n_bars = 1970 if full else 32  # delta 32根≈8天，容忍cron偶发漏跑（原16根只盖4天）
    codes = sorted(p.stem for p in KC.glob("*.json"))
    done = err = 0
    t0 = time.time()
    for idx, code in enumerate(codes):
        fp = CACHE / f"{code}.json"
        if fp.exists() and fp.stat().st_size > 100:
            done += 1  # 断点续跑：已有数据的跳过
            continue
        sym = ("sh" if code.startswith("6") else "sz") + code
        rows = fetch(sym, n_bars)
        if rows:
            if fp.exists() and not full:
                old = json.loads(fp.read_text())
                seen = {r["day"] for r in old}
                new = [r for r in rows if r["day"] not in seen]
                if new:
                    old.extend(new)
                    old.sort(key=lambda r: r["day"])
                    fp.write_text(json.dumps(old))
            else:
                fp.write_text(json.dumps(rows))
            done += 1
        else:
            err += 1
        if idx % 300 == 0:
            print(f"[{idx}/{len(codes)}] done={done} err={err} {time.time()-t0:.0f}s", flush=True)
        time.sleep(0.1)
    print(f"DONE done={done} err={err} elapsed={time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
