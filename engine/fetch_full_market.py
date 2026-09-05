#!/usr/bin/env python3
"""engine/fetch_full_market.py — 全主板 3194 票历史日K补齐 (2026-09-06)
背景：周期仪回验发现 300 只池票样本覆盖不到妖股（金健米业等不在池史），
回验全判「平淡期」= 样本偏差。补齐全主板后回验才有效。
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "/opt/data/python-libs")
import baostock as bs  # noqa: E402

ROOT = Path("/opt/data/fenjue")
KC = ROOT / "data" / "big_kcache"
START, END = "2019-01-01", "2026-09-04"


def main():
    codes = json.loads((ROOT / "data" / "main_board_codes.json").read_text())["stocks"]
    codes = [str(s["code"]).zfill(6) for s in codes]
    todo = [c for c in codes if not (KC / f"{c}.json").exists()]
    print(f"总数 {len(codes)}，已有 {len(codes)-len(todo)}，待拉 {len(todo)}", flush=True)
    lg = bs.login()
    if lg.error_code != "0":
        print("login fail")
        return 1
    done = 0
    t0 = time.time()
    for c in todo:
        try:
            rs = bs.query_history_k_data_plus(
                ("sh." if c.startswith("6") else "sz.") + c,
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
                (KC / f"{c}.json").write_text(json.dumps(rows))
        except Exception as e:
            print(f"{c} fail {e}", flush=True)
        done += 1
        if done % 200 == 0:
            print(f"  {done}/{len(todo)} ({(time.time()-t0)/60:.0f}min)", flush=True)
    bs.logout()
    print(f"完成，耗时 {(time.time()-t0)/60:.0f} 分钟", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
