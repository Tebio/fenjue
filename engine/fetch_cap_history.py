#!/usr/bin/env python3
"""engine/fetch_cap_history.py — 历史流通市值重建 (2026-09-06)

销 AGENTS.md 欠账 #4：regime_backtest 用 2026-09-04 市值快照当常数。
方法：baostock 不复权日线带 turn（换手率%），流通股本 = volume/(turn/100)，
流通市值(亿) = close * 流通股本 / 1e8。逐股写 data/cap_hist/{code}.json。
断点续跑；与 refetch_qfq.py 同款温柔策略（1s/只 + 失败退避）。
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "/opt/data/python-libs")
import baostock as bs  # noqa: E402

ROOT = Path("/opt/data/fenjue")
KC = ROOT / "data" / "big_kcache"
OUT = ROOT / "data" / "cap_hist"
OUT.mkdir(exist_ok=True)
START, END = "2019-01-01", "2026-09-04"


def main() -> None:
    todo = []
    for f in sorted(KC.glob("*.json")):
        if f.stem == "000001":
            continue
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
