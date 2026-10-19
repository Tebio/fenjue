#!/usr/bin/env python3
"""流式预抽取月末标量（内存安全：逐票读 big_kcache，不驻留全量 K 线；15GB 机 OOM 防线）。
产物 data/fund_cohold/kc_scalars.npz:
  codes[]            主板 60/00 票
  months[]           月末月份标签（升序）
  month_end[i,j]     票 i 在 months[j] 月末的前复权收盘（缺失 nan）
  ma60_pos[i,j]      该月末收盘相对当日 MA60 的百分比（缺失 nan）
用法: .venv/bin/python engine/fund_cohold_scalars.py [起始月 YYYY-MM] [结束月 YYYY-MM]
"""
import json, os, sys
import numpy as np

KC = "/opt/data/fenjue/data/big_kcache"
OUT = "/opt/data/fenjue/data/fund_cohold/kc_scalars.npz"


def main():
    start = sys.argv[1] if len(sys.argv) > 1 else "2021-04"
    end = sys.argv[2] if len(sys.argv) > 2 else "2026-09"
    ref = json.load(open(f"{KC}/000001.json"))
    month_last = {}
    for k in ref:
        month_last[k["date"][:7]] = k["date"]
    months = sorted(m for m in month_last if start <= m <= end)
    print(f"月份 {months[0]} .. {months[-1]} ({len(months)})", flush=True)

    codes, me_rows, pos_rows = [], [], []
    for fn in sorted(os.listdir(KC)):
        code = fn[:-5]
        if code[:2] not in ("60", "00"):
            continue
        try:
            ks = json.load(open(f"{KC}/{fn}"))
        except Exception:
            continue
        if len(ks) < 80:
            continue
        didx = {k["date"]: i for i, k in enumerate(ks)}
        closes = [k["close"] for k in ks]
        row_me, row_pos = [], []
        for m in months:
            d = month_last.get(m)
            i = didx.get(d)
            if i is None or i < 59:
                row_me.append(np.nan); row_pos.append(np.nan); continue
            c = closes[i]
            row_me.append(c)
            ma = sum(closes[i - 59:i + 1]) / 60 if c > 0 else 0
            row_pos.append(c / ma - 1 if ma > 0 else np.nan)
        codes.append(code); me_rows.append(row_me); pos_rows.append(row_pos)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    np.savez(OUT, codes=np.array(codes), months=np.array(months),
             month_end=np.array(me_rows, dtype=np.float32),
             ma60_pos=np.array(pos_rows, dtype=np.float32))
    print(f"[DONE] codes={len(codes)} months={len(months)} -> {OUT}", flush=True)


if __name__ == "__main__":
    main()
