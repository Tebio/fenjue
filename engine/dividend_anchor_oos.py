#!/usr/bin/env python3
"""engine/dividend_anchor_oos.py — 股息率锚无存活者偏差回测 (2026-09-06)

销欠账 #6：旧回测宇宙=中证红利∪红利低波当期 115 只名单，被指数剔除的烂票
不在里面（存活者偏差）；且旧口径疑用「当期 TTM 分红」对「历史价格」（未来函数）。
本版全时点化：
  - 宇宙：当日 TTM 分红 >0 的全主板股票（dividend_history 逐票除权日累计）
  - 时点股息率 = 当日 TTM 每股分红 / 当日不复权收盘价（cap_hist 的 raw close）
  - 事件：息率上穿 4.5%（进入买入区），按触发原因分「分红事件/价格下跌」两组
  - 对照：同日 0<息率<4.5% 的分红股
  - 收益：big_kcache 前复权价总回报（送转/派息天然含在复权序列里，不用手动加回——
    2026-09-06 外部审查发现#3：旧版 raw+现金分红加回漏算转增/送股，系统性做低收益）；
    信号日次日开盘买入（发现#7：旧版信号价=成交价过于理想化），再扣 0.15% 双边费用
  - 分段：2019-2022 非牛段 / 2023-2026 牛段，窗口 120 个交易日（个股自身交易日）
残留偏差：退市股不在 big_kcache（全仓库口径一致，另行标注）。
"""
from __future__ import annotations

import bisect
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
KCACHE = ROOT / "data" / "big_kcache"
CAPDIR = ROOT / "data" / "cap_hist"
DIV = ROOT / "data" / "dividend_history.json"
FWD = 120          # 前向窗口（交易日）
FEE = 0.0015       # 双边费用
BUY_Y = 4.5        # 买入区阈值 %


def ttm_dps_fn(events: list[list]):
    """events: [[ex_date, dps]] → f(date_str) = 过去365天TTM每股分红"""
    evs = sorted((e[0], e[1]) for e in events)
    dates = [e[0] for e in evs]

    def f(d: str) -> float:
        # 年份直接减1拼字符串是有意为之：字符串比较下"上一年-02-29"作为边界依然正确
        # （润日只会让窗口边界差1天）。若改成 date 对象运算，此处会当场炸（外部审查低优先级提醒）。
        y, m, dd = int(d[:4]) - 1, d[5:7], d[8:10]
        lo = f"{y}-{m}-{dd}"
        i = bisect.bisect_right(dates, d)
        j = bisect.bisect_right(dates, lo)
        return sum(v for _, v in evs[j:i])
    return f


def main() -> None:
    divs = json.loads(DIV.read_text())

    entries = defaultdict(list)   # date -> [(code, yield)] 买入区穿越事件
    controls = defaultdict(list)  # date -> [code] 当日分红股但未达买入区
    uni_size = defaultdict(int)   # date -> 当日 TTM 分红>0 的股票数

    codes = [f.stem for f in sorted(KCACHE.glob("*.json")) if f.stem != "000001"]
    for code in codes:
        ev = divs.get(code) or []
        if not ev:
            continue
        capf = CAPDIR / f"{code}.json"
        if not capf.exists():
            continue
        raw = json.loads(capf.read_text())  # [[date, close_raw, cap]]
        kf = KCACHE / f"{code}.json"
        qfq = {k["date"]: float(k["close"]) for k in json.loads(kf.read_text())} if kf.exists() else {}
        ttm = ttm_dps_fn(ev)
        prev_in = False
        prev_dps = 0.0
        prev_d = ""
        prev_close_raw = 0.0
        for d, close_raw, _cap in raw:
            if d < "2019-01-01":
                continue
            dps = ttm(d)
            if dps <= 0:
                prev_in = False
                prev_dps = 0.0
                prev_d, prev_close_raw = d, close_raw
                continue
            uni_size[d] += 1
            yld = dps / close_raw * 100
            in_zone = yld >= BUY_Y
            if in_zone and not prev_in:
                # 发现#6：按触发原因分组——TTM 分红增加=除权日机械事件；否则=价格下跌穿越
                trig = "分红事件" if dps > prev_dps else "价格下跌"
                # R2 审查发现#3-信号侧：转增/送股除权让不复权价机械下跌→息率机械上穿，
                # 会被误记成"价格下跌触发"。用前复权序列交叉验证：raw 跌幅显著差于 qfq
                # 跌幅（>3pp）说明"下跌"主要是除权算术，归入"除权机械"并剔除出统计。
                if trig == "价格下跌" and prev_close_raw > 0 and qfq:
                    q0, q1 = qfq.get(prev_d), qfq.get(d)
                    if q0 and q1 and close_raw / prev_close_raw - 1 < (q1 / q0 - 1) - 0.03:
                        trig = "除权机械"
                entries[d].append((code, round(yld, 2), trig))
            elif not in_zone:
                controls[d].append(code)
            prev_in = in_zone
            prev_dps = dps
            prev_d, prev_close_raw = d, close_raw

    # 前向收益：big_kcache 前复权序列（送转/派息已含），信号日次日开盘买入，
    # 个股自身第 FWD+1 个交易日收盘卖出。懒加载缓存。
    _qfq: dict[str, tuple[list[str], dict[str, dict]]] = {}

    def fwd_return(code: str, d0: str) -> float | None:
        if code not in _qfq:
            kf = KCACHE / f"{code}.json"
            if not kf.exists():
                _qfq[code] = ([], {})
            else:
                ks = json.loads(kf.read_text())
                _qfq[code] = ([k["date"] for k in ks], {k["date"]: k for k in ks})
        days, by = _qfq[code]
        if not days:
            return None
        j = bisect.bisect_right(days, d0)  # 次日（个股自身下一交易日）
        if j >= len(days) or j + FWD >= len(days):
            return None
        p0 = float(by[days[j]]["open"])
        p1 = float(by[days[j + FWD]]["close"])
        if p0 <= 0:
            return None
        return p1 / p0 - 1 - FEE

    def seg_stats(d_lo: str, d_hi: str):
        e_rets: dict[str, list] = {"分红事件": [], "价格下跌": []}
        n_exright = 0
        c_rets = []
        for d, lst in entries.items():
            if d_lo <= d < d_hi:
                for code, _y, trig in lst:
                    if trig == "除权机械":
                        n_exright += 1
                        continue
                    r = fwd_return(code, d)
                    if r is not None:
                        e_rets[trig].append(r)
        # 对照：同窗口内所有「分红股非买入区」的 (date, code)
        for d, lst in controls.items():
            if d_lo <= d < d_hi:
                for code in lst:
                    r = fwd_return(code, d)
                    if r is not None:
                        c_rets.append(r)
        def agg(rs):
            if not rs:
                return {"n": 0}
            win = sum(1 for r in rs if r > 0) / len(rs)
            return {"n": len(rs), "win%": round(win * 100, 1),
                    "mean%": round(sum(rs) / len(rs) * 100, 2)}
        return {"买入区穿越(全体)": agg(e_rets["分红事件"] + e_rets["价格下跌"]),
                "其中-分红事件触发": agg(e_rets["分红事件"]),
                "其中-价格下跌触发": agg(e_rets["价格下跌"]),
                "除权机械(已剔除)": {"n": n_exright},
                "对照(分红股非买入区)": agg(c_rets)}

    out = {
        "scope": "2019-01~2026-09 全主板, 时点TTM息率, 信号次日开盘买, 个股120交易日前复权总回报, -0.15%费用",
        "segments": {
            "2019-2022(非牛段)": seg_stats("2019-01-01", "2023-01-01"),
            "2023-2026(牛段)": seg_stats("2023-01-01", "2026-09-05"),
        },
        "universe_size_samples": {d: uni_size[d] for d in
                                  ("2019-06-03", "2020-06-01", "2021-06-01", "2022-06-01",
                                   "2023-06-01", "2024-06-03", "2025-06-02", "2026-06-01")
                                  if d in uni_size},
        "caveats": ["窗口重叠非独立样本", "退市股不在宇宙(全仓口径一致)", "对照组为同日分红股非买入区"],
    }
    (ROOT / "data" / "dividend_anchor_oos.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
