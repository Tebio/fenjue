#!/usr/bin/env python3
"""engine/update_kcache.py — big_kcache 增量更新（baostock，单进程纪律）

对每只已缓存股票：从本地最后日期+1 拉到最新交易日，去重 append。
新上市（本地缺失）的票交给 fetch_full_market.py 全量拉，本脚本不管。
用法：python3 engine/update_kcache.py [end_date]   # 默认今天
"""
import json, sys, time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, "/opt/data/python-libs")
import baostock as bs

KC = Path("/opt/data/fenjue/data/big_kcache")
FIELDS = "date,open,high,low,close,volume"


def code_to_bs(code: str) -> str:
    return ("sh." if code.startswith("6") else "sz.") + code


def main():
    end = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    files = sorted(KC.glob("*.json"))
    lg = bs.login()
    assert lg.error_code == "0", lg.error_msg
    updated = upto = errors = 0
    t0 = time.time()
    for idx, fp in enumerate(files):
        code = fp.stem
        try:
            rows = json.loads(fp.read_text())
            last = rows[-1]["date"]
            if last >= end:
                upto += 1
                continue
            start = (date.fromisoformat(last) + timedelta(days=1)).isoformat()
            rs = bs.query_history_k_data_plus(code_to_bs(code), FIELDS,
                                              start_date=start, end_date=end,
                                              frequency="d", adjustflag="2")
            new = []
            while rs.error_code == "0" and rs.next():
                r = rs.get_row_data()
                if not r[1]:
                    continue
                new.append({"date": r[0], "open": float(r[1]), "high": float(r[2]),
                            "low": float(r[3]), "close": float(r[4]), "volume": float(r[5] or 0)})
            if new:
                seen = {r["date"] for r in rows}
                rows.extend(r for r in new if r["date"] not in seen)
                rows.sort(key=lambda r: r["date"])
                fp.write_text(json.dumps(rows))
                updated += 1
        except Exception as e:
            errors += 1
            print(f"ERR {code}: {e}", flush=True)
        if idx % 200 == 0:
            print(f"[{idx}/{len(files)}] updated={updated} upto={upto} err={errors} {time.time()-t0:.0f}s", flush=True)
        time.sleep(0.12)  # 限流纪律
    bs.logout()
    print(f"DONE updated={updated} already_current={upto} errors={errors} elapsed={time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
