#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""engine/submit_lean.py — 低内存 submit 六闸门跑批（卡 t_9e69cd05 工具件）

背景：`law_pipeline.py submit` 在本机（15GB，且常与其他 kanban worker 并发）会 exit 137 OOM
——根因是顶层 main 的 mkdir 式全宇宙 dict 常驻（实测单进程 rss ≈2.97GB 仅存 K 线，叠上
build_xsection/cap_quintiles/多次 run_pipeline 即越界）。本脚本复用 law_pipeline 的
**同一套** submit_gate/探测器/build_xsection（零口径二次实现，C6 纪律），只把宇宙加载
换成 numpy 精简版（对齐 engine/auction_confirm_backtest.py 的 load_universe_lean 手法）。

用法：.venv/bin/python engine/submit_lean.py "跌停接_MA60下_gap≤-3" ["另一下detector名" ...]
输出：stdout 每行一个判决 JSON（与 law_pipeline submit 同结构），并写 data/law_pipeline_submit_<今日>.json
"""
import glob
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import law_pipeline as lp  # noqa: E402

ROOT = Path("/opt/data/fenjue")
KC = ROOT / "data" / "big_kcache"


def load_lean():
    """numpy 精简宇宙：c/o/h/l/v/ma60(np)/date/n。ma60 与 lp.load_universe 逐值一致
    （含今日收盘的 60 日均；i<60 为 NaN）——注意 lp.load_universe 的 ma60[i] 为滞后一根，
    此处为对齐 detector（law_pipeline 内 _demo_deep_core 用 d["ma60"][i] 含当日）。"""
    stocks = {}
    for fp in sorted(glob.glob(str(KC / "*.json"))):
        ks = json.loads(open(fp).read())
        if len(ks) < 300:
            continue
        code = Path(fp).stem
        c = np.array([k["close"] for k in ks])
        S = np.concatenate([[0.0], np.cumsum(c)])
        ma60 = np.full(len(c), np.nan)
        ma60[60:] = (S[60:len(c)] - S[:len(c) - 60]) / 60   # 滞后一根：ma60[i]=mean(c[i-60..i-1])
        stocks[code] = {
            "code": code, "c": c,
            "o": np.array([k["open"] for k in ks]),
            "h": np.array([k["high"] for k in ks]),
            "l": np.array([k["low"] for k in ks]),
            "v": np.array([k.get("volume", 0) for k in ks]),
            "ma60": ma60, "date": [k["date"] for k in ks], "n": len(ks),
        }
        del ks
    return stocks


def main():
    names = sys.argv[1:]
    assert names, "用法: submit_lean.py <detector名> [...]"
    stocks = load_lean()
    print("stocks:", len(stocks), flush=True)
    lp.build_xsection(stocks)
    regime = lp.load_regime()
    stock_cap, qs = lp.load_cap_quintiles()
    out, rc = {}, 0
    for name in names:
        fn = lp.REGISTRY[name]
        passed, v = lp.submit_gate(name, fn, stocks, regime, stock_cap, qs)
        out[name] = v
        rc |= 0 if passed else 1
        print(json.dumps(v, ensure_ascii=False), flush=True)
    today = (datetime.now(timezone.utc) + timedelta(hours=8)).date().isoformat().replace("-", "")
    dst = ROOT / f"data/law_pipeline_submit_{today}.json"
    if dst.exists():
        prev = json.loads(dst.read_text())
        prev.update(out)
        out = prev
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("saved", dst)
    sys.exit(rc)


if __name__ == "__main__":
    main()
