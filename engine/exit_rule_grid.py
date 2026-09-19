#!/usr/bin/env python3
"""exit_rule_grid.py — 卖点研究：存活信号的出场规则网格（2026-09-18 夜间批）。

用户原话：「不光研究买点，而且要研究卖的时机让收益最大化，不是笼统固定时间买卖」。
口径（对齐 law_pipeline.capacity_sim）：
  信号日 i 收盘确认 → 次日 i+1 开盘买（开盘一字跌停作废，o[i+1]<=c[i]*0.905）
  → 出场规则触发 → 净收益 = exit/entry - 1 - 0.0015（往返费）。
T+1 物理：入场日当天不能卖，所有盘中规则最早次日（j>i+1）生效；
  当天高低同时触止盈止损 = 保守记止损先（同 bar 不可知顺序）。

规则族：
  fixed_N    : 入场日+N 天收盘卖，N∈{1,2,3,5,8,13,21}（基线）
  tpX_sY     : 止盈 +X% / 止损 -Y% 盘中触价（high/low），先到先走，兜底 T+21 收盘
  trail_Z    : 移动止盈：收盘从峰值回撤 Z% 离场，兜底 T+21
  ma60_out   : 收盘收复 MA60 次日收盘离场，兜底 T+21
  tp6s3_ma60 : 止盈止损 + MA60 回收 双条件先到先走
指标：n / win% / mean% / med% / 赔率(平均盈利/|平均亏损|) / 期望 / 平均持有天数。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import law_pipeline as lp

ROOT = Path(__file__).resolve().parent.parent
FEE = 0.0015
CAP_HOLD = 21          # 所有规则兜底持有上限
LD_LOCK = -0.095       # 跌停封死（收盘<=入场日基准×(1-9.5%) 视为卖不出顺延）

# 受试信号：G7/事件研究存活系（死的票不进策略——用户裁决）
SIGNALS = [
    "跌停接_MA60下_缩量",
    "组合_跌停低_长周期_超跌20",
    "组合_跌停低_三连阴",
    "组合_跌停低_避雷针低位",
    "组合_缺口低开_低位阳线",
    "组合_触板未封_低位",
]

RULES_FIXED = [("fixed_%d" % n, ("fixed", n)) for n in (1, 2, 3, 5, 8, 13, 21)]
RULES_TP = [(f"tp{tp}_s{sl}", ("tpsl", tp / 100, sl / 100)) for tp, sl in ((4, 3), (6, 3), (8, 5), (10, 5))]
RULES_TRAIL = [(f"trail_{z}", ("trail", z / 100)) for z in (5, 8)]
RULES = RULES_FIXED + RULES_TP + RULES_TRAIL + [
    ("ma60_out", ("ma60",)),
    ("tp6s3_ma60", ("tpsl_ma60", 0.06, 0.03)),
]


def collect_events(detect, stocks):
    """(code, i) 事件列表，口径同 _collect_sigs。"""
    evs = []
    for code, d in stocks.items():
        c, o, ma, n = d["c"], d["o"], d["ma60"], d["n"]
        for i in range(61, n - CAP_HOLD - 2):
            if c[i-1] <= 0 or c[i] <= 0 or o[i+1] <= 0 or ma[i] is None:
                continue
            if o[i+1] <= c[i] * 0.905:
                continue
            try:
                if detect(d, i):
                    evs.append((code, i))
            except Exception:
                pass
    return evs


def simulate(d, i, rule):
    """返回 (净收益率, 持有天数)。买=o[i+1]；规则见模块 docstring。"""
    c, o, h, l, ma, n = d["c"], d["o"], d["h"], d["l"], d["ma60"], d["n"]
    ei = i + 1
    entry = o[ei]
    kind = rule[0]
    if kind == "fixed":
        hold = rule[1]
        j = ei + hold
        while j < n and c[j] <= entry * (1 + LD_LOCK):   # 出场日跌停顺延（≤3 天）
            if j - ei >= hold + 3:
                break
            j += 1
        if j >= n:
            return None
        return c[j] / entry - 1 - FEE, j - ei

    peak = entry
    for j in range(ei, min(ei + CAP_HOLD + 1, n)):
        # 入场日只记录峰值/观察，不卖（T+1）
        sellable = j > ei
        if sellable and c[j] <= entry * (1 + LD_LOCK):
            continue  # 跌停封死卖不出，顺延
        if kind in ("tpsl", "tpsl_ma60"):
            tp, sl = rule[1], rule[2]
            if sellable:
                hit_tp = h[j] >= entry * (1 + tp)
                hit_sl = l[j] <= entry * (1 - sl)
                if hit_sl:      # 同 bar 双触保守记止损
                    return (entry * (1 - sl)) / entry - 1 - FEE, j - ei
                if hit_tp:
                    return tp - FEE, j - ei
                if kind == "tpsl_ma60" and ma[j] is not None and c[j] > ma[j]:
                    return c[j] / entry - 1 - FEE, j - ei
        elif kind == "trail":
            z = rule[1]
            peak = max(peak, c[j])
            if sellable and c[j] <= peak * (1 - z):
                return c[j] / entry - 1 - FEE, j - ei
        elif kind == "ma60":
            if sellable and ma[j] is not None and c[j] > ma[j]:
                return c[j] / entry - 1 - FEE, j - ei
    j = min(ei + CAP_HOLD, n - 1)
    while j > ei and c[j] <= entry * (1 + LD_LOCK):
        j -= 1
        if j <= ei:
            return None  # 全程锁死，剔除（买不进/卖不出幻觉剔除）
    return c[j] / entry - 1 - FEE, j - ei


def metrics(rs):
    if not rs:
        return None
    wins = [r for r, _ in rs if r > 0]
    losses = [r for r, _ in rs if r <= 0]
    rets = sorted(r for r, _ in rs)
    n = len(rets)
    mean = sum(rets) / n
    odds = (sum(wins) / len(wins)) / abs(sum(losses) / len(losses)) if wins and losses else None
    return {
        "n": n,
        "win%": round(100 * len(wins) / n, 1),
        "mean%": round(100 * mean, 2),
        "med%": round(100 * rets[n // 2], 2),
        "赔率": round(odds, 2) if odds else None,
        "期望pp": round(100 * mean, 2),
        "avg持有天": round(sum(h for _, h in rs) / n, 1),
    }


def main():
    # 2026-09-19 用户裁决「比赛也得配上卖点」：--all 时对 REGISTRY 全部信号跑入场×出场矩阵
    sig_list = SIGNALS
    if "--all" in sys.argv:
        sig_list = sorted(lp.REGISTRY.keys())
    stocks = lp.load_universe()
    lp.build_xsection(stocks)
    out = {}
    for name in sig_list:
        det = lp.REGISTRY.get(name)
        if det is None:
            print(f"[skip] {name} 不在注册表", flush=True)
            continue
        evs = collect_events(det, stocks)
        print(f"{name}: 事件 {len(evs)}", flush=True)
        rec = {}
        for rname, rule in RULES:
            rs = []
            for code, i in evs:
                r = simulate(stocks[code], i, rule)
                if r is not None:
                    rs.append(r)
            m = metrics(rs)
            if m:
                rec[rname] = m
        out[name] = rec
        best = max(rec.items(), key=lambda kv: kv[1]["期望pp"]) if rec else None
        print(f"  最优: {best[0]} 期望{best[1]['期望pp']}pp 胜{best[1]['win%']}% 赔{best[1]['赔率']}" if best else "  无有效", flush=True)
    dst = ROOT / f"data/exit_rule_grid{'_all' if '--all' in sys.argv else ''}_20260919.json"
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("saved", dst)


if __name__ == "__main__":
    main()
