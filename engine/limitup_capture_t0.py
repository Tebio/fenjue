#!/usr/bin/env python3
"""engine/limitup_capture_t0.py — 两个幻想的实证（2026-09-12 用户灵魂拷问）

Q1: 信号选出的票，当天买入当天吃涨停的概率是多少？吃到后次日收益几何？
    → 对照全市场涨停基率。8年日K全宇宙。
Q2: 持仓做T（先买后卖正T）在 m60 bar 级路径下净期望为正吗？
    → 2年 m60 全宇宙，限价单真实填充顺序模拟，同bar双向触及保守判不成交，费用0.1%/往返。
"""
import json, glob, math, statistics as st, time
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
KC = ROOT / "data/big_kcache"
M60 = ROOT / "data/m60_cache"
OUT = ROOT / "data/limitup_capture_t0_20260912.json"


def limit_pct(code):
    return 0.195 if code.startswith(("30", "68")) else 0.097  # 阈值留舍入余量


# ── Q1: 涨停捕获 ──
def q1():
    t0 = time.time()
    base_cnt = sig3_cnt = sig95_cnt = 0
    base_lu = sig3_lu = sig95_lu = 0
    lu_next_open, lu_next_close = [], []   # 吃到涨停（开盘买入）后：次日开盘/尾盘相对买入价
    sig3_rs, sig95_rs = [], []
    ndays = 0
    for fp in glob.glob(str(KC / "*.json")):
        code = Path(fp).stem
        ks = json.loads(open(fp).read())
        if len(ks) < 300:
            continue
        c = [k["close"] for k in ks]
        o = [k["open"] for k in ks]
        th = limit_pct(code)
        for i in range(65, len(ks) - 2):
            if c[i - 1] <= 0 or o[i + 1] <= 0:
                continue
            chg = c[i] / c[i - 1] - 1
            nd = c[i + 1] / c[i] - 1
            ndays += 1
            base_cnt += 1
            is_lu = nd >= th
            if is_lu:
                base_lu += 1
            r_oc = c[i + 1] / o[i + 1] - 1  # 开盘买→当日收盘（毛）
            if chg <= -0.03:
                sig3_cnt += 1
                sig3_rs.append(r_oc)
                if is_lu:
                    sig3_lu += 1
                    lu_next_open.append(o[i + 2] / o[i + 1] - 1)
                    lu_next_close.append(c[i + 2] / o[i + 1] - 1)
            if chg <= -0.095:
                sig95_cnt += 1
                sig95_rs.append(r_oc)
                if is_lu:
                    sig95_lu += 1
    def S(rs):
        return {"n": len(rs), "mean%": round(100 * st.mean(rs), 2),
                "win%": round(100 * sum(r > 0 for r in rs) / len(rs), 1)} if len(rs) >= 30 else None
    return {
        "涨停基率%": round(100 * base_lu / base_cnt, 3),
        "基率样本": base_cnt,
        "信号≤-3%次日涨停率%": round(100 * sig3_lu / sig3_cnt, 3),
        "信号≤-3%_n": sig3_cnt, "信号≤-3%当日开盘买→收盘": S(sig3_rs),
        "信号≤-9.5%次日涨停率%": round(100 * sig95_lu / max(sig95_cnt, 1), 3),
        "信号≤-9.5%_n": sig95_cnt, "信号≤-9.5%当日开盘买→收盘": S(sig95_rs),
        "吃到涨停后_次日开盘相对买入价": S(lu_next_open),
        "吃到涨停后_次日尾盘相对买入价": S(lu_next_close),
        "说明": "涨停=收盘涨幅≥9.7%(主板)/19.5%(30/68开头)；毛口径未扣费",
    }


# ── Q2: 做T（正T：先买后卖，当日了结）──
def q2():
    t0 = time.time()
    DIPS = [0.01, 0.015, 0.02]
    TGTS = [0.01, 0.015, 0.02]
    FEE_RT = 0.001  # 买佣金0.025% + 卖佣金0.025%+印花0.05%
    res = {(d, t): {"days": 0, "buy_fill": 0, "sell_fill": 0, "rets": []}
           for d in DIPS for t in TGTS}
    for fp in glob.glob(str(M60 / "*.json")):
        per = {}
        for b in json.loads(open(fp).read()):
            per.setdefault(b["day"][:10], []).append(
                (b["day"][11:], float(b["open"]), float(b["high"]), float(b["low"]), float(b["close"])))
        for dstr, bars0 in per.items():
            if len(bars0) < 4:
                continue
            bars = sorted(bars0)
            o = bars[0][1]
            close = bars[-1][4]
            for dip in DIPS:
                blim = o * (1 - dip)
                bi = None
                for k, (_, _, hi, lo, _) in enumerate(bars):
                    if lo <= blim:
                        bi = k
                        break
                for tgt in TGTS:
                    cell = res[(dip, tgt)]
                    cell["days"] += 1
                    if bi is None:
                        continue  # 未成交=0收益（持币）
                    cell["buy_fill"] += 1
                    slim = blim * (1 + tgt)
                    sold = None
                    for k in range(bi, 4):
                        _, _, hi, lo, _ = bars[k]
                        if k == bi and hi >= slim and lo <= blim:
                            continue  # 同bar双向触及，顺序未知→保守判不成交
                        if hi >= slim:
                            sold = slim
                            break
                    if sold is not None:
                        cell["sell_fill"] += 1
                        cell["rets"].append(tgt - FEE_RT)
                    else:
                        cell["rets"].append(close / blim - 1 - FEE_RT)  # 尾盘了结
    out = {}
    for (dip, tgt), cell in res.items():
        rs = cell["rets"]
        key = f"买-{100*dip:.1f}%/卖+{100*tgt:.1f}%"
        if not rs:
            continue
        day_expect = sum(rs) / cell["days"]  # 未成交日记0
        out[key] = {
            "天数": cell["days"],
            "买成交率%": round(100 * cell["buy_fill"] / cell["days"], 1),
            "卖成交率|买%": round(100 * cell["sell_fill"] / cell["buy_fill"], 1),
            "单笔净%": round(100 * st.mean(rs), 3),
            "胜率%": round(100 * sum(r > 0 for r in rs) / len(rs), 1),
            "每日期望%": round(100 * day_expect, 4),
            "年化粗估%": round(244 * 100 * day_expect, 1),
        }
    return out, time.time() - t0


if __name__ == "__main__":
    r1 = q1()
    print(json.dumps(r1, ensure_ascii=False, indent=1), flush=True)
    r2, sec = q2()
    print(f"Q2 用时 {sec:.0f}s", flush=True)
    print(json.dumps(r2, ensure_ascii=False, indent=1), flush=True)
    OUT.write_text(json.dumps({"Q1涨停捕获": r1, "Q2做T": r2}, ensure_ascii=False, indent=1))
    print("saved", OUT)
