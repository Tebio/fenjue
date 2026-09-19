#!/usr/bin/env python3
"""engine/dsr_recount.py — E2 销账：DSR trials 实测数重算（2026-09-19 深夜）。

红队二轮 E2：旧 DSR 全部按 trials=25 假设，本周末新增测试数百次后该假设系统性偏高。
本模块：
  1. trials 普查：结构计数 data/*.json 中所有「胜率+均值」叶记录（≈一次策略评估），
     含重复提交（保守方向：trials 偏大 → DSR 更严，不会放水）。
  2. 单遍收集 REGISTRY 89 个检测器的事件（与 run_pipeline 同口径：START..hi、_epx>0），
     共享全宇宙日均值（calendar_time 里逐 detector 重算 uni 是纯浪费，数值不变）。
  3. 同一日历时间超额序列分别按 trials=25（复现旧值=自检）与 trials=实测N 出 DSR。
用法：.venv/bin/python engine/dsr_recount.py
输出：data/dsr_recount_YYYYMMDD.json
"""
import glob
import json
import math
import re
import statistics as st
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import law_pipeline as lp

ROOT = Path("/opt/data/fenjue")
FEE = 0.0015
H = 5  # 与 run_pipeline 默认 horizon 一致
BJT = timezone(timedelta(hours=8))

WIN = re.compile(r"胜率|win")
MEAN = re.compile(r"均值|期望|mean|avg|均笔|收益")


def trials_census():
    """结构计数：data/*.json 里含胜率键+均值键的叶记录数（≥5 才计入，滤掉配置块）。"""
    per, total = {}, 0
    for f in sorted(glob.glob(str(ROOT / "data/*.json"))):
        try:
            d = json.load(open(f))
        except Exception:
            continue
        n = [0]

        def walk(o):
            if isinstance(o, dict):
                ks = list(o.keys())
                if any(WIN.search(str(k)) for k in ks) and any(MEAN.search(str(k)) for k in ks):
                    n[0] += 1
                    return
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for it in o:
                    walk(it)

        walk(d)
        if n[0] >= 5:
            per[Path(f).name] = n[0]
            total += n[0]
    return per, total


def collect_chunk(stocks, names):
    """单遍全宇宙 × 一批检测器（分批防 OOM：89 检测器全量事件同时驻留曾把进程吃挂）。
    与 run_pipeline 同循环边界；detector 异常按 False 记。"""
    events = {nm: [] for nm in names}
    dets = [(nm, lp.REGISTRY[nm]) for nm in names]
    hi_h = max(lp.HORIZONS) + 1
    err = defaultdict(int)
    for code, d in stocks.items():
        n = d["n"]
        epx = d["o"]  # _epx 主路径=次日开盘；entry 口径与 run_pipeline 默认一致
        for i in range(lp.START, n - hi_h):
            if epx[i + 1] <= 0:
                continue
            for nm, det in dets:
                try:
                    if det(d, i):
                        events[nm].append((code, i))
                except Exception:
                    err[nm] += 1
    return events, dict(err)


def uni_means(stocks):
    """calendar_time 里的全宇宙日度均值（同口径；流式 sum/count 聚合，不驻留明细）。"""
    agg = defaultdict(lambda: [0.0, 0])
    for code, d in stocks.items():
        c, o, n = d["c"], d["o"], d["n"]
        for i in range(lp.START, n - H - 1):
            if o[i + 1] > 0:
                a = agg[d["date"][i + 1]]
                a[0] += c[i + H] / o[i + 1] - 1 - FEE
                a[1] += 1
    return {dt: s / k for dt, (s, k) in agg.items()}


def ct_series(events, stocks, uni_m):
    """与 lp.calendar_time 数值 identical 的日度超额序列（共享 uni_m 版）。"""
    by_date = defaultdict(list)
    for code, i in events:
        d = stocks[code]
        by_date[d["date"][min(i + 1, d["n"] - 1)]].append(d["c"][i + H] / d["o"][i + 1] - 1 - FEE)
    return [st.mean(by_date[dt]) - uni_m[dt] for dt in sorted(by_date) if dt in uni_m]


def main():
    per, trials = trials_census()
    print(f"trials 普查：{len(per)} 个文件，raw 合计 {trials}（含重复提交=保守方向）", flush=True)

    stocks = lp.load_universe()
    lp.build_xsection(stocks)
    names = sorted(lp.REGISTRY)
    uni_m = uni_means(stocks)
    print(f"宇宙 {len(stocks)} 只，检测器 {len(names)} 个，uni 均值就绪，分批收集…", flush=True)

    out, errs = {}, {}
    CHUNK = 10
    for c0 in range(0, len(names), CHUNK):
        batch = names[c0:c0 + CHUNK]
        events, err = collect_chunk(stocks, batch)
        errs.update(err)
        for nm in batch:
            ev = events[nm]
            if len(ev) < 30:
                out[nm] = {"事件数": len(ev), "注": "样本<30 不算 ct"}
                continue
            series = ct_series(ev, stocks, uni_m)
            del events[nm]
            if len(series) < 30:
                out[nm] = {"事件数": len(ev), "天数": len(series), "注": "天数<30 不算 DSR"}
                continue
            m, sd = st.mean(series), st.stdev(series)
            sr = m / sd * math.sqrt(244) if sd > 0 else 0
            skew, kurt = lp._skew(series), lp._kurt(series)
            dsr_old = lp.deflated_sharpe(sr / math.sqrt(244), len(series), skew, kurt, trials=25)
            dsr_new = lp.deflated_sharpe(sr / math.sqrt(244), len(series), skew, kurt, trials=trials)
            out[nm] = {"事件数": len(ev), "天数": len(series),
                       "日均超额%": round(100 * m, 3), "年化Sharpe": round(sr, 2),
                       "t_NW": lp.nw_t(series, H), "skew": round(skew, 2), "kurt": round(kurt, 2),
                       "DSR_旧_trials25": dsr_old, "DSR_新_trials实测": dsr_new}
            print(f"  {nm}: SR {sr:.2f} DSR {dsr_old} → {dsr_new}", flush=True)
        del events

    today = datetime.now(BJT).strftime("%Y%m%d")
    fp = ROOT / f"data/dsr_recount_{today}.json"
    json.dump({"meta": {"date": today, "horizon": H, "fee": FEE,
                        "trials_实测": trials, "trials_旧假设": 25,
                        "trials_口径": "data/*.json 结构计数（胜率+均值叶记录），含重复提交=保守方向；tmp/jsonl 未计=反向，两抵",
                        "trials_分文件": per, "detector_异常计数": errs},
                "signals": out},
               open(fp, "w"), ensure_ascii=False, indent=1)
    print(f"落盘 {fp}", flush=True)


if __name__ == "__main__":
    main()
