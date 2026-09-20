#!/usr/bin/env python3
"""fjcore.py — 焚诀门面层（2026-09-19 架构收编，用户令「不要代码堆叠」）。

新模块的唯一入口。禁止再直接 import law_pipeline 读全局、禁止再各自重写 fwd/stat。
law_pipeline 仍是底层引擎（不动它，绞杀者模式：新代码全走这里，旧模块逐步迁移）。

用法：
    from fjcore import Universe, forward, stats, EXIT_RULES
    u = Universe()                    # 全宇宙+横截面，一次加载全局缓存
    r = forward(u.stocks[code], i, 5) # 统一前向收益（次日开盘买/净口径/剔一字）
    m = stats(returns)                # 统一指标（n/胜率/均值/赔率/中位）
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import law_pipeline as lp

FEE = 0.0015
HORIZONS = (1, 2, 3, 5, 10, 20)


class Universe:
    """全市场宇宙 + 横截面 globals，进程内单例。"""

    _inst = None

    def __new__(cls):
        if cls._inst is None:
            cls._inst = super().__new__(cls)
            cls._inst._ready = False
        return cls._inst

    def load(self):
        if self._ready:
            return self
        self.stocks = lp.load_universe()
        lp.build_xsection(self.stocks)
        self.regime = lp.load_regime()
        self.cap, self.cap_qs = lp.load_cap_quintiles()
        self.fund = lp._XFUND          # code -> (dates, vals) packed tuple（查询走 fund_at）
        self.ldc = lp._XLDC            # date -> 当日全市场跌停数
        self.ladder = lp._XLADDER      # date -> industry -> 涨停数（板块梯队）
        self.ind = lp._IND or {}       # code -> industry
        self.cradle_cnt = lp._XCRADLE  # date -> 当日妖股摇篮信号数（成簇横截面）
        self._ready = True
        return self

    def cap_at(self, code, date):
        return lp.cap_at_date(self.cap, code, date)

    def fund_at(self, code, date):
        # 直通 lp.fund_at（packed tuple + bisect，2026-09-20 收编验证抓出：旧版按 dict.get 读 tuple 会炸）
        return lp.fund_at(code, date)


def forward(d, i, h, fee=FEE):
    """统一前向收益：信号日 i 收盘确认 → 次日开盘买 → 入场+h 日收盘卖（净口径）。
    开盘一字跌停（买不进）返回 None。"""
    ei = i + 1
    if ei >= d["n"] or ei + h >= d["n"] or d["o"][ei] <= 0:
        return None
    if d["o"][ei] <= d["c"][i] * 0.905:
        return None
    return d["c"][ei + h] / d["o"][ei] - 1 - fee


def stats(rs):
    """统一指标包：n / win% / mean% / med% / 赔率 / t。rs 为收益率（小数）。"""
    rs = [r for r in rs if r is not None]
    if not rs:
        return None
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    n = len(rs)
    mean = sum(rs) / n
    sd = (sum((x - mean) ** 2 for x in rs) / n) ** 0.5 or 1e-12
    odds = (sum(wins) / len(wins)) / abs(sum(losses) / len(losses)) if wins and losses else None
    srt = sorted(rs)
    return {"n": n, "win%": round(100 * len(wins) / n, 1), "mean%": round(100 * mean, 2),
            "med%": round(100 * srt[n // 2], 2), "赔率": round(odds, 2) if odds else None,
            "t": round(mean / sd * n ** 0.5, 1)}


def full_curve(rs_by_h):
    """汇报纪律（用户钦定）：全 horizon 曲线一行。"""
    return " | ".join(
        f"T+{h} {s['win%']}%/{s['mean%']}%/赔{s['赔率']}"
        for h, s in rs_by_h.items() if s)


# 出口规则库的唯一登记处（exit_rule_grid.py 的实现为准，引用不复制）
EXIT_RULES = ("fixed_1", "fixed_2", "fixed_3", "fixed_5", "fixed_8", "fixed_13", "fixed_21",
              "tp4_s3", "tp6_s3", "tp8_s5", "tp10_s5", "trail_5", "trail_8", "ma60_out",
              "tp6s3_ma60")

# 闸门/容量/选票的直通（薄封装，签名即文档）
submit_gate = lp.submit_gate
capacity_sim = lp.capacity_sim
collect_sigs = lp._collect_sigs
REGISTRY = lp.REGISTRY
# 底层常数/检测器助手直通（绞杀者收编用：winner_anatomy 等迁移期引用）
START = lp.START
td9buy = lp._td9buy
three_down = lp._three_down
