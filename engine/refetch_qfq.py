#!/usr/bin/env python3
"""engine/refetch_qfq.py — baostock 前复权温柔重拉 (2026-09-06)
修复：big_kcache 里 2873 只是新浪不复权（除权日价格跳空污染涨跌幅/宽度统计）。
腾讯 fqkline 把本机 IP 限流（501）后退回 baostock：1s/只 + 失败退避。
只重写「不复权」文件（长小数=已是前复权的跳过）。断点续跑。"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "/opt/data/python-libs")
import baostock as bs  # noqa: E402

ROOT = Path("/opt/data/fenjue")
KC = ROOT / "data" / "big_kcache"
START, END = "2019-01-01", "2026-09-04"


def is_raw(rows):
    return not any(abs(x["close"] - round(x["close"], 2)) > 1e-9 for x in rows[:200])


def main() -> None:
    todo = []
    for f in sorted(KC.glob("*.json")):
        if f.stem == "000001":
            continue
        rows = json.loads(f.read_text())
        if rows and is_raw(rows):
            todo.append(f.stem)
    print(f"待重写 {len(todo)}", flush=True)
    bs.login()
    t0 = time.time()
    fails = 0
    for i, code in enumerate(todo):
        for attempt in range(2):
            try:
                rs = bs.query_history_k_data_plus(
                    ("sh." if code.startswith("6") else "sz.") + code,
                    "date,open,high,low,close,volume",
                    start_date=START, end_date=END, frequency="d", adjustflag="2")
                rows = []
                while rs.error_code == "0" and rs.next():
                    r = rs.get_row_data()
                    if r[4]:
                        rows.append({"date": r[0], "open": float(r[1] or 0), "high": float(r[2] or 0),
                                     "low": float(r[3] or 0), "close": float(r[4] or 0),
                                     "volume": float(r[5] or 0)})
                if len(rows) >= 60:
                    (KC / f"{code}.json").write_text(json.dumps(rows))
                break
            except Exception as e:
                if attempt == 0:
                    time.sleep(30)
                else:
                    fails += 1
                    print(f"{code} 两次失败 {str(e)[:40]}", flush=True)
        time.sleep(1.0)
        if i % 200 == 199:
            print(f"  {i+1}/{len(todo)} {(time.time()-t0)/60:.0f}min 失败{fails}", flush=True)
    bs.logout()
    print(f"完成 {(time.time()-t0)/60:.0f}min 失败 {fails}", flush=True)


if __name__ == "__main__":
    main()
