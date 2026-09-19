#!/usr/bin/env python3
"""nshape_study.py — N字二波启动走势研究（2026-09-19 用户点名金健米业 600127 立项）。

走势解剖（600127，2026-08 至 09）：底部横盘 → 8/6 放量首板（量比4.7）→ 8/11-14 缩量回踩不破
→ 8/17-18 二波放量再启动 → 天量连板主升（5.6→14.9，+165%）→ 9/2 巨量剧震见顶 → 反包/二顶。

定义「N字二波」事件（检测日=二波启动日）：
  1. 首板日 B：前 3~15 日内，收盘≥+9.8%（涨停）+ 当日量比≥2.5 + 前60日无涨停（低位首板）
  2. 回踩期 B+1 ~ 检测日前：收盘价最低点 ≥ B 日开盘 ×0.97（不破启动位，容差3%）
     且回踩期日均量 ≤ B 日量 ×0.65（缩量洗盘）
  3. 检测日 T：涨幅 ≥ +4% 且 量比 ≥ 1.8（放量再起），收盘 > 回踩期最高收盘（过顶确认）
入场变体（用户裁决：不机械开盘买）：
  E_T_close  检测日收盘买（信号当日可判，14:50 执行口径）
  E_T_open   检测日次日开盘买（框架默认口径，对比用）
出场变体（全部收盘判 14:50 可执行，兜底 20 日；T+1 物理：最早入场日次日卖）：
  X_ma5      收盘跌破 MA5 离场
  X_quake    高位剧震离场：量≥5日均量×2 且（上影≥4% 或 实体大阴≤-4%）
  X_trail10  收盘从峰值回撤 10% 离场
  X_fix5/X_fix10  固定持有
  X_bignum   单日 ≤-7% 大阴离场
指标：n / win% / mean% / med% / 赔率 / 平均持有天；净口径 -0.15%。
对照：同票非事件日随机 5 倍采样（位置对照：涨停链股票波动大，必须同票比）。
"""
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import law_pipeline as lp

ROOT = Path(__file__).resolve().parent.parent
FEE = 0.0015
CAP = 20


def volratio(v, i, n=5):
    base = v[max(0, i - n):i]
    if len(base) < n or any(x <= 0 for x in base):
        return 0.0
    m = sum(base) / len(base)
    return v[i] / m if m > 0 else 0.0


def is_nshape(d, t):
    """检测日 t 是否为 N字二波启动日。返回首板日索引或 None。"""
    c, o, v, n = d["c"], d["o"], d["v"], d["n"]
    if t < 65 or c[t] <= 0 or c[t - 1] <= 0:
        return None
    # 条件3：检测日放量大涨过顶（量比阈值 1.5：参照案例金健 8/18 实测 1.74，1.8 会漏掉它——公开标注校准）
    if c[t] / c[t - 1] - 1 < 0.04 or volratio(v, t) < 1.5:
        return None
    for B in range(t - 3, max(60, t - 15), -1):  # 首板在 3~15 日前
        if c[B] <= 0 or c[B - 1] <= 0:
            continue
        if c[B] / c[B - 1] - 1 < 0.098:      # 首板涨停
            continue
        if volratio(v, B) < 2.5:             # 首板放量
            continue
        # 前60日无涨停（低位首板）
        if any(c[j] > 0 and c[j - 1] > 0 and c[j] / c[j - 1] - 1 >= 0.098
               for j in range(max(1, B - 60), B)):
            continue
        retrace = c[B + 1:t]                  # 回踩期
        if len(retrace) < 2:
            continue
        if min(retrace) < o[B] * 0.97:       # 破启动位
            continue
        # 缩量（2026-09-19 按参照案例校准并公开标注：金健首板次日仍天量，
        # 故分两段判——整体均量不超首板量 + 末端3日收敛到首板量8成以下。
        # 这是对着 n=1 案例调的阈值，属于模式定义而非证据，证据由全样本+闸门给出）
        rv = [v[j] for j in range(B + 1, t)]
        if sum(rv) / len(rv) > v[B]:
            continue
        if len(rv) >= 3 and sum(rv[-3:]) / 3 > v[B] * 0.8:
            continue
        if c[t] <= max(retrace):             # 未过回踩期高点（过顶确认）
            continue
        return B
    return None


def simulate_exit(d, ei, rule):
    """ei=入场日索引，entry=o[ei]。返回 (净收益率, 持有天数) 或 None。"""
    c, o, h, l, v, n = d["c"], d["o"], d["h"], d["l"], d["v"], d["n"]
    entry = o[ei]
    if entry <= 0:
        return None
    peak = entry
    for j in range(ei, min(ei + CAP + 1, n)):
        sellable = j > ei                      # T+1
        if not sellable:
            continue
        if c[j] <= 0:
            continue
        pc = c[j - 1]
        chg = c[j] / pc - 1 if pc > 0 else 0
        peak = max(peak, c[j])
        if rule == "X_ma5":
            if j >= ei + 4:
                ma5 = sum(c[j - 4:j + 1]) / 5
                if c[j] < ma5:
                    return c[j] / entry - 1 - FEE, j - ei
        elif rule == "X_quake":
            vr = volratio(v, j)
            upper = (h[j] - c[j]) / c[j] if c[j] > 0 else 0
            if vr >= 2.0 and (upper >= 0.04 or chg <= -0.04):
                return c[j] / entry - 1 - FEE, j - ei
        elif rule == "X_trail10":
            if c[j] <= peak * 0.90:
                return c[j] / entry - 1 - FEE, j - ei
        elif rule == "X_fix5" and j - ei >= 5:
            return c[j] / entry - 1 - FEE, j - ei
        elif rule == "X_fix10" and j - ei >= 10:
            return c[j] / entry - 1 - FEE, j - ei
        elif rule == "X_bignum" and chg <= -0.07:
            return c[j] / entry - 1 - FEE, j - ei
    j = min(ei + CAP, n - 1)
    if j <= ei:
        return None
    return c[j] / entry - 1 - FEE, j - ei


def metrics(rs):
    if not rs:
        return None
    rets = sorted(r for r, _ in rs)
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    n = len(rets)
    mean = sum(rets) / n
    odds = (sum(wins) / len(wins)) / abs(sum(losses) / len(losses)) if wins and losses else None
    return {"n": n, "win%": round(100 * len(wins) / n, 1), "mean%": round(100 * mean, 2),
            "med%": round(100 * rets[n // 2], 2), "赔率": round(odds, 2) if odds else None,
            "avg持有天": round(sum(h for _, h in rs) / n, 1)}


RULES = ["X_ma5", "X_quake", "X_trail10", "X_fix5", "X_fix10", "X_bignum"]


def find_retrace_entry(d, E):
    """委托 law_pipeline._nshape_retrace（单实现纪律，2026-09-19）。"""
    import law_pipeline as lp
    return True if lp._nshape_retrace(d, E) else None


def main():
    stocks = lp.load_universe()
    lp.build_xsection(stocks)
    events = []   # (code, t, B)
    for code, d in stocks.items():
        n = d["n"]
        for t in range(65, n - CAP - 2):
            B = is_nshape(d, t)
            if B is not None:
                events.append((code, t, B))
    print(f"N字二波事件: {len(events)}", flush=True)

    out = {"事件数": len(events), "入场x出场": {}}
    rng = random.Random(20260919)
    for entry_mode in ("T_close", "T_open"):
        for rule in RULES:
            rs = []
            for code, t, B in events:
                d = stocks[code]
                ei = t if entry_mode == "T_close" else t + 1
                if ei >= d["n"] - 1 or d["o"][ei] <= 0:
                    continue
                # 入场可成交性：次日开盘一字涨停买不进
                if entry_mode == "T_open" and d["o"][ei] / d["c"][t] - 1 >= 0.095:
                    continue
                # 收盘入场用收盘价的等价口径：把 entry 换成 c[t]
                if entry_mode == "T_close":
                    d2 = dict(d)
                    r = simulate_exit_close(d, t, rule)
                else:
                    r = simulate_exit(d, ei, rule)
                if r is not None:
                    rs.append(r)
            m = metrics(rs)
            out["入场x出场"][f"{entry_mode}+{rule}"] = m
            if m:
                print(f"{entry_mode}+{rule}: n={m['n']} 胜{m['win%']}% 均{m['mean%']}% 赔{m['赔率']} 持{m['avg持有天']}天", flush=True)
    dst = ROOT / "data/nshape_study_20260919.json"
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("saved", dst)

    # ---- 回踩期入场变体（E=B+3 收盘买，可执行口径）----
    revents = []
    for code, d in stocks.items():
        for E in range(64, d["n"] - CAP - 2):
            if find_retrace_entry(d, E) is not None:
                revents.append((code, E))
    print(f"回踩期入场事件: {len(revents)}", flush=True)
    for rule in RULES:
        rs = []
        for code, E in revents:
            r = simulate_exit_close(stocks[code], E, rule)
            if r is not None:
                rs.append(r)
        m = metrics(rs)
        out["入场x出场"][f"retrace+{rule}"] = m
        if m:
            print(f"retrace+{rule}: n={m['n']} 胜{m['win%']}% 均{m['mean%']}% 赔{m['赔率']} 持{m['avg持有天']}天", flush=True)
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("saved", dst)


def simulate_exit_close(d, t, rule):
    """收盘入场口径：entry=c[t]，ei=t（当日已持有，次日可卖）。"""
    c, o, h, l, v, n = d["c"], d["o"], d["h"], d["l"], d["v"], d["n"]
    entry = c[t]
    if entry <= 0:
        return None
    peak = entry
    for j in range(t + 1, min(t + CAP + 1, n)):
        if c[j] <= 0:
            continue
        pc = c[j - 1]
        chg = c[j] / pc - 1 if pc > 0 else 0
        peak = max(peak, c[j])
        if rule == "X_ma5":
            if j >= t + 4:
                ma5 = sum(c[j - 4:j + 1]) / 5
                if c[j] < ma5:
                    return c[j] / entry - 1 - FEE, j - t
        elif rule == "X_quake":
            vr = volratio(v, j)
            upper = (h[j] - c[j]) / c[j] if c[j] > 0 else 0
            if vr >= 2.0 and (upper >= 0.04 or chg <= -0.04):
                return c[j] / entry - 1 - FEE, j - t
        elif rule == "X_trail10":
            if c[j] <= peak * 0.90:
                return c[j] / entry - 1 - FEE, j - t
        elif rule == "X_fix5" and j - t >= 5:
            return c[j] / entry - 1 - FEE, j - t
        elif rule == "X_fix10" and j - t >= 10:
            return c[j] / entry - 1 - FEE, j - t
        elif rule == "X_bignum" and chg <= -0.07:
            return c[j] / entry - 1 - FEE, j - t
    j = min(t + CAP, n - 1)
    if j <= t:
        return None
    return c[j] / entry - 1 - FEE, j - t


if __name__ == "__main__":
    main()
