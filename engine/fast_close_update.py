#!/usr/bin/env python3
"""fast_close_update.py — 15:10 BJT 收盘快报：新浪快照生成当日K线覆盖层。

背景（2026-09-14 用户令"为啥跑这么晚，下班要讨论"）：
baostock 收盘数据 18 点才就绪 → 观察池/深档扫描被迫排到晚上。
但新浪快照 15:00 就有全市场收盘价。本脚本把今日 bar 写成覆盖层
data/kcache_today_overlay.json（不碰 big_kcache 权威库，18:30 baostock 照旧跑），
watch_pool.py / dashboard_build.py 读取时合并覆盖层 → 收盘后 20 分钟内面板全更新。
幂等：同日重复跑覆盖同一文件。
"""
import json, sys, urllib.request, time
from datetime import date
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
OUT = ROOT / "data/kcache_today_overlay.json"


def hq(codes, tries=3):
    out = {}
    for i in range(0, len(codes), 80):
        chunk = codes[i:i + 80]
        for _ in range(tries):
            try:
                req = urllib.request.Request("http://hq.sinajs.cn/list=" + ",".join(chunk),
                                             headers={"Referer": "https://finance.sina.com.cn/"})
                raw = urllib.request.urlopen(req, timeout=15).read().decode("gb18030", "ignore")
                got = 0
                for line in raw.strip().split("\n"):
                    if '=""' in line or "=" not in line:
                        continue
                    f = line.split('="')[1].rstrip('";').split(",")
                    if len(f) < 31:
                        continue
                    code = line.split("=")[0][-6:]
                    try:
                        out[code] = dict(open=float(f[1] or 0), prev=float(f[2] or 0),
                                         close=float(f[3] or 0), high=float(f[4] or 0),
                                         low=float(f[5] or 0), volume=float(f[8] or 0),
                                         day=f[30])
                        got += 1
                    except ValueError:
                        continue
                if got:
                    break
            except Exception:
                time.sleep(1)
        time.sleep(0.2)
    return out


def main():
    for k in list(__import__('os').environ):
        if "proxy" in k.lower():
            __import__('os').environ.pop(k)
    stocks = json.loads((ROOT / "data/main_board_codes.json").read_text())["stocks"]
    codes = [s["code"] for s in stocks]
    idx = hq(["sh000001"])
    if not idx:
        print("[SILENT] 指数快照拉取失败")
        return 1
    today = date.today().isoformat()
    if idx["000001"]["day"] != today:
        return 0  # 非交易日静默
    q = hq([("sh" if c.startswith("6") else "sz") + c for c in codes])
    overlay = {}
    for c in codes:
        d = q.get(c)
        if not d or d["close"] <= 0 or d["day"] != today:
            continue
        overlay[c] = {"date": today, "open": d["open"], "high": d["high"],
                      "low": d["low"], "close": d["close"], "volume": d["volume"],
                      "_src": "sina_fast_close"}
    OUT.write_text(json.dumps(overlay, ensure_ascii=False))
    print(f"收盘快报覆盖层: {today} {len(overlay)} 只（18:30 baostock 权威校准照旧）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
