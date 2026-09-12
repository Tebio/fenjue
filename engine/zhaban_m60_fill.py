#!/usr/bin/env python3
"""engine/zhaban_m60_fill.py — 炸板回踩挂单的成交现实重测（2026-09-12）

动机：zhaban_backtest（日K）的 opt/mid 入场是成交子集乐观口径，撞 #35 限价单恒等式坑。
本模块在 m60 空间全自洽重测（不复权 60 分钟 bar，2024-08-30..2026-09-11，3234 只）：
  信号：m60 聚合日K重判（昨收→今收 ≥+9.8% 涨停；今开≥+5%；今日最低涨幅∈[3%,8.5%]）
  挂单：限价 = 昨收×(1+X)，X∈{6%,7%,8%}
  成交规则（保守）：bar.open≤限价→按 bar.open 成交；bar.low≤限价→按限价成交；否则未成交=0
  出场：T+1 开盘（次日首 bar open）/ T+1 收盘（次日末 bar close），费 0.15%
  关键输出：成交率（R/U 分组=逆向选择定量）、每信号期望（未成交=0）、每成交期望
残留乐观（诚实标注）：60 分钟粒度，秒级触碰+薄队列的不可成交无法识别——成交率仍偏高。
"""
import json, sys, statistics as st
from collections import defaultdict
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
M60 = ROOT / "data/m60_cache"
FEE = 0.0015
LIMITS = [0.06, 0.07, 0.08]


def S(rs):
    if len(rs) < 30:
        return None
    m = st.mean(rs)
    return {"n": len(rs), "win%": round(100*sum(r > 0 for r in rs)/len(rs), 1),
            "mean%": round(100*m, 2), "med%": round(100*st.median(rs), 2)}


def daily_bars(rows):
    """m60 → 日K（不复权）。"""
    days = defaultdict(list)
    for r in rows:
        days[r["day"][:10]].append(r)
    out = []
    for dt in sorted(days):
        bs = sorted(days[dt], key=lambda r: r["day"])
        out.append({"date": dt, "open": float(bs[0]["open"]),
                    "high": max(float(b["high"]) for b in bs),
                    "low": min(float(b["low"]) for b in bs),
                    "close": float(bs[-1]["close"]), "bars": bs})
    return out


def main():
    per_limit = {x: {"sig": [], "fill_open": [], "fill_close": [], "fill_R": [], "fill_U": [],
                     "band_open": [], "band_close": [],
                     "n_sig": 0, "n_fill": 0, "n_R": 0, "n_U": 0, "fill_in_R": 0,
                     "n_band": 0, "n_deep": 0} for x in LIMITS}
    files = sorted(M60.glob("*.json"))
    for k, fp in enumerate(files):
        if k % 500 == 0:
            print(f"progress {k}/{len(files)}", flush=True)
        try:
            rows = json.loads(fp.read_text())
        except Exception:
            continue
        dk = daily_bars(rows)
        for i in range(2, len(dk) - 1):
            pc = dk[i-1]["close"]
            ppc = dk[i-2]["close"]
            if pc <= 0 or ppc <= 0:
                continue
            if (pc/ppc - 1) * 100 < 9.8:   # 昨日未涨停
                continue
            o, lo, cl = dk[i]["open"], dk[i]["low"], dk[i]["close"]
            if o <= 0 or (o/pc - 1) * 100 < 5:
                continue
            g_low = (lo/pc - 1) * 100
            in_band = 3 <= g_low <= 8.5
            reseal = (cl/pc - 1) * 100 >= 9.8
            nxt = dk[i+1]
            for x in LIMITS:
                stt = per_limit[x]
                stt["n_sig"] += 1
                stt["n_band" if in_band else "n_deep"] += 1
                stt["n_R" if reseal else "n_U"] += 1
                lim = pc * (1 + x)
                fill_px = None
                for b in dk[i]["bars"]:
                    bo, bl = float(b["open"]), float(b["low"])
                    if bo <= lim:
                        fill_px = bo
                        break
                    if bl <= lim:
                        fill_px = lim
                        break
                if fill_px is None or fill_px <= 0:
                    continue  # 未成交=0（不进 fill 统计，per-signal 期望单独算）
                stt["n_fill"] += 1
                if reseal:
                    stt["fill_in_R"] += 1
                r_open = nxt["open"]/fill_px - 1 - FEE if nxt["open"] > 0 else None
                r_close = nxt["close"]/fill_px - 1 - FEE
                if r_open is not None:
                    stt["fill_open"].append(r_open)
                    if in_band:
                        stt["band_open"].append(r_open)
                stt["fill_close"].append(r_close)
                if in_band:
                    stt["band_close"].append(r_close)
                (stt["fill_R"] if reseal else stt["fill_U"]).append(r_close)

    out = {"meta": {"window": "m60 2024-08-30..2026-09-11", "fee": FEE,
                    "note": "per_signal期望=成交收益×成交率(未成交=0)；60分粒度成交率仍偏高"}}
    for x in LIMITS:
        stt = per_limit[x]
        fill_rate = stt["n_fill"] / stt["n_sig"] if stt["n_sig"] else 0
        r_in_R = stt["fill_in_R"] / stt["n_R"] if stt["n_R"] else 0
        r_in_U = (stt["n_fill"] - stt["fill_in_R"]) / stt["n_U"] if stt["n_U"] else 0
        per_sig_open = [r * fill_rate for r in stt["fill_open"]]  # 近似：E=fill_rate×E|fill
        res = {
            "信号数": stt["n_sig"], "其中浅炸(3~8.5%)": stt["n_band"], "深炸(<3%)": stt["n_deep"],
            "成交率%": round(100*fill_rate, 1),
            "成交率_R组%": round(100*r_in_R, 1), "成交率_U组%": round(100*r_in_U, 1),
            "每成交_T1开盘": S(stt["fill_open"]), "每成交_T1收盘": S(stt["fill_close"]),
            "浅炸子集_T1开盘": S(stt["band_open"]),
            "每成交_T1收盘_R组": S(stt["fill_R"]), "每成交_T1收盘_U组": S(stt["fill_U"]),
            "每信号期望_T1开盘%": round(100*st.mean(per_sig_open), 2) if per_sig_open else None,
        }
        out[f"挂+{int(x*100)}%"] = res
        print(f"== 挂+{int(x*100)}% ==", json.dumps(res, ensure_ascii=False), flush=True)
    (ROOT/"data/zhaban_m60_fill_20260912.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    print("SAVED data/zhaban_m60_fill_20260912.json")


if __name__ == "__main__":
    main()
