#!/usr/bin/env python3
"""engine/seat_gene_backfill.py — 龙虎榜三榜 1 年历史回填（席位基因库数据底座）

HiThink dragon-tiger-list 实测 1 年深（2026-09-12 验证 2025-09-12 有数据）。
回填 hot_money / org / all 三榜到 data/hithink/<date>/，与 hithink_daily.py 同构。
- 交易日历：big_kcache/000001.json 的日期序列
- 已存在的文件跳过（幂等，可断点续跑）
- 限速 0.2s/请求（限额 20/s，远低于）
"""
import json, subprocess, sys, time
from datetime import date, timedelta
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
OUT = ROOT / "data/hithink"
KEY = None
for line in Path("/opt/data/.env").read_text().splitlines():
    if line.startswith("HITHINK_API_KEY="):
        KEY = line.split("=", 1)[1].strip()
assert KEY, "HITHINK_API_KEY missing"
BASE = "https://fuyao.aicubes.cn"
BOARDS = ["hot_money", "org", "all"]


def get(path):
    r = subprocess.run(["curl", "-sL", "--max-time", "25", "-H", f"X-api-key: {KEY}", BASE + path],
                       capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"})
    try:
        return json.loads(r.stdout)
    except Exception:
        return {"code": -1, "raw": r.stdout[:200]}


def trading_days() -> list[str]:
    ks = json.loads((ROOT / "data/big_kcache/000001.json").read_text())
    start = (date.today() - timedelta(days=370)).isoformat()
    return sorted(k["date"] for k in ks if k["date"] >= start)


def main():
    days = trading_days()
    print(f"trading days to cover: {len(days)} ({days[0]}..{days[-1]})", flush=True)
    done = skip = empty = err = 0
    for d in days:
        outdir = OUT / d
        outdir.mkdir(parents=True, exist_ok=True)
        for b in BOARDS:
            f = outdir / f"lhb_{'hot' if b == 'hot_money' else b}.json"  # 与 hithink_daily 命名一致
            if f.exists():
                skip += 1
                continue
            r = get(f"/api/a-share/special-data/dragon-tiger-list?board_type={b}&date={d}")
            if r.get("code") != 0:
                err += 1
                print(f"[ERR] {d} {b}: {str(r)[:150]}", flush=True)
            elif not (r.get("data") or {}).get("count"):
                empty += 1  # 当日该榜无数据（如半日市），不落盘
            else:
                f.write_text(json.dumps(r, ensure_ascii=False))
                done += 1
            time.sleep(0.2)
        if done % 60 == 0:
            print(f"progress: {d} done={done} skip={skip} empty={empty} err={err}", flush=True)
    print(f"FINISH done={done} skip={skip} empty={empty} err={err}", flush=True)


if __name__ == "__main__":
    main()
