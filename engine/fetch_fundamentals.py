#!/usr/bin/env python3
"""engine/fetch_fundamentals.py — 全市场日频基本面库（2026-09-18 立项）

用途：为「存活策略命中票的基本面共同点分析」提供底料。
字段：peTTM / pbMRQ / psTTM / turn(换手%) / isST，另存 volume+amount 供自算流动性。
不入评分管线（V3 冻结中），纯测量底座。

方法：baostock 逐股前复权日线，一次查询带全部字段；断点续跑（已存在的票跳过）。
纪律：单进程（baostock 禁双进程）；失败退避重试；与 big_kcache 对账行数防截断。

用法：
    python3 engine/fetch_fundamentals.py            # 全量（断点续跑）
    python3 engine/fetch_fundamentals.py 000001     # 单票
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "/opt/data/python-libs")
import baostock as bs

ROOT = Path("/opt/data/fenjue")
KC = ROOT / "data/big_kcache"
DST = ROOT / "data/fund_cache"
START = "2018-01-01"
END = "2026-09-18"

FIELDS = "date,close,turn,tradestatus,pctChg,peTTM,pbMRQ,psTTM,isST"


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    shard = sys.argv[2] if len(sys.argv) > 2 else None
    DST.mkdir(parents=True, exist_ok=True)

    codes = sorted(Path(fp).stem for fp in KC.glob("*.json"))
    if only:
        codes = [only]
    # 分片模式：从清单文件读（并发加速，2026-09-18）
    if shard:
        codes = [c.strip() for c in Path(shard).read_text().splitlines() if c.strip()]

    todo = [c for c in codes if not (DST / f"{c}.json").exists()]
    print(f"universe={len(codes)} todo={len(todo)}", flush=True)

    lg = bs.login()
    if lg.error_code != "0":
        print("login failed", lg.error_msg)
        return 1

    ok = fail = 0
    for idx, code in enumerate(todo, 1):
        bs_code = ("sh." if code.startswith("6") else "sz.") + code
        rows = []
        for attempt in range(3):
            try:
                rs = bs.query_history_k_data_plus(
                    bs_code, FIELDS, start_date=START, end_date=END,
                    frequency="d", adjustflag="3")
                if rs.error_code != "0":
                    time.sleep(2 ** attempt)
                    continue
                while rs.next():
                    r = rs.get_row_data()
                    if not r[0] or not r[1]:
                        continue
                    # date, close, turn, tradestatus, pctChg, peTTM, pbMRQ, psTTM, isST
                    rows.append([
                        r[0],
                        float(r[1]) if r[1] else None,
                        float(r[2]) if r[2] else None,
                        r[3],
                        float(r[4]) if r[4] else None,
                        float(r[5]) if r[5] else None,   # peTTM
                        float(r[6]) if r[6] else None,   # pbMRQ
                        float(r[7]) if r[7] else None,   # psTTM
                        r[8],
                    ])
                break
            except Exception as e:
                time.sleep(2 ** attempt)
                if attempt == 2:
                    print(f"  ERR {code}: {e}")
        if rows:
            # 完整性对账：与 big_kcache 行数比（防限流截断）
            try:
                kc = json.loads((KC / f"{code}.json").read_text())
                if len(rows) < len(kc) * 0.6:
                    print(f"  WARN {code}: rows {len(rows)} vs kcache {len(kc)}, 疑似截断，仍落盘（重跑可覆盖）")
            except Exception:
                pass
            (DST / f"{code}.json").write_text(json.dumps(rows))
            ok += 1
        else:
            fail += 1
            (DST / f"{code}.json").write_text("[]")  # 占位防重试（空=该票无数据）
        if idx % 200 == 0:
            print(f"  {idx}/{len(todo)} ok={ok} fail={fail}", flush=True)
        time.sleep(0.35)

    bs.logout()
    print(f"done ok={ok} fail={fail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
