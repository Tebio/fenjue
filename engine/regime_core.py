#!/usr/bin/env python3
"""engine/regime_core.py — regime 四态判定的唯一出处（2026-10-20 立）

背景与裁决（详见 research/regime_final_verdict.md + research/K4_final_on_fixed_data.md）：
  旧判定 `跌停家数 >= 20` 建立在被低估的跌停序列上。真序列下它的开火率是 36.3%
  （686/1888 天），是噪音不是信号。跌停家数绝对值不能跨年比——2023 年日均 14 家、
  2024 年日均 46 家，同一个「20」在两年的含义完全不同。故腿一改为滚动 250 日分位。

裁决要点：
  1. 腿一 = 滚动 250 日分位（合计口径：纯 10% 档 + 真 ST 5% 档），q95。绝对门槛不进主路径。
  2. PANIC_PCT_Q = 0.95 与策略B 的 q95 **同值不同源**，是独立常量，禁止交叉引用——
     否则日后调策略B 甜点会静默改写全系统的恐慌定义。
  3. 腿二 (涨停枯竭 + 指数大跌) 保留阈值 30/1.0，**不采用 U*=39**。实测：腿二在任何
     阈值上都没有独立信息（剔掉与腿一重叠的日子后，@30 t=-0.84、@39 t=+0.04、@50 t=+0.53）；
     @39 表面 t=2.27 全部来自它与腿一重叠的 28 天（前瞻 +2.146%，腿一已单独抓到）。
     把 30 改成 39 只会把无信息天数从 30 天扩到 66 天。
  4. 兜底不再静默用 20：分位缺失时用 ABS_FALLBACK=38 并 stderr 告警。用 20 会把
     「数据断供」静默翻译成「35.8% 的日子恐慌」，是本仓库 [SILENT] 纪律的同款事故。
  5. **两腿的建议动作相反**，必须分开给：
     腿一（跌停潮）= 投降式抛售后的反弹窗口，实测前瞻 5 日指数 +1.356% (t=+4.09)、
       前瞻最大回撤 -0.69% 反而比非恐慌日 -1.01% 更浅 → 与策略B 对齐，不该空仓躲。
     腿二（涨停枯竭+指数跌）= 趋势延续型弱势，实测前瞻 -0.067% (t=-0.84，不显著) → 降进攻频率。
     旧代码两腿共用一句「空仓或高股息防御」，对腿一是反向操作。
"""
from __future__ import annotations

import sys

# —— 腿一：滚动分位 ——
PANIC_PCT_Q = 0.95      # 独立常量，禁止与策略B 的 q95 交叉引用
PCT_WINDOW = 250
PCT_MIN_PERIODS = 120   # 窗口有效值不足则不判

# —— 腿二：涨停枯竭 + 指数大跌 ——
LEG2_LU_MAX = 30        # 涨停家数上限（否决 39，见模块 docstring 第 3 条）
LEG2_IDX_PCT = -1.0     # 指数日跌幅（%）

# —— 兜底：分位缺失时（仅冷启动/管线故障），不是主路径 ——
ABS_FALLBACK = 38       # 合计口径的绝对家数备案值（K4 T*），仅为可解释性保留

STATES = ("主线期", "妖股期", "恐慌期", "平淡期")

ADVICE_PANIC_LEG1 = (
    "跌停潮（合计口径分位≥0.95）——历史上这种投降式抛售之后是反弹窗口："
    "前瞻5日指数 +1.36%(t=4.09)、前瞻最大回撤反而比平时更浅。与策略B 对齐，分批建指数仓，不要空仓躲"
)
ADVICE_PANIC_LEG2 = (
    "涨停枯竭+指数大跌——趋势延续型弱势（独立信息弱，前瞻5日 -0.07%，t=-0.84 不显著）："
    "降低进攻频率，不新开追高仓"
)
ADVICE_PANIC_BOTH = (
    "跌停潮叠加涨停枯竭——投降式抛售与趋势弱势同时出现："
    "以策略B 的指数分批建仓为主，个股进攻暂停"
)
ADVICE_MAINLINE = "涨停集中在主线产业链——用板块操作台/焚诀主线打法（反转开盘买、追高只允许尾盘买）"
ADVICE_HOTMONEY = "涨停全是小市值散票无主线——默认不参与；个股不可预测"
ADVICE_FLAT = "无量能无主线——观望，红利宇宙建仓窗口"


def _warn_once(msg: str) -> None:
    key = "_warned_" + str(abs(hash(msg)))
    if not getattr(_warn_once, key, False):
        setattr(_warn_once, key, True)
        print(f"[REGIME][WARN] {msg}", file=sys.stderr)


def _verdict(state: str, advice: str, leg1: bool, leg2: bool, gap: bool,
             basis: str = "pct") -> dict:
    return {"state": state, "advice": advice, "leg1": bool(leg1), "leg2": bool(leg2),
            "gap": bool(gap), "basis": basis}


def classify(
    limit_ups: int,
    index_pct: float,
    small_cap_ratio: float,
    top_sector_conc: float,
    limit_downs_abs: int | None = None,
    pct_limit_down: float | None = None,
) -> tuple[str, str]:
    """四态判定，唯一出处。返回 (state, advice)。

    腿一优先用 pct_limit_down（合计口径的滚动分位）；缺失时退回 limit_downs_abs
    与 ABS_FALLBACK 比较并告警——绝不静默用 20。

    ⚠️ 调用方必须保证 pct_limit_down 的窗口与 limit_downs_abs 是**同一口径**
    （合计 = 纯10%档 + 真ST5%档）。分子用纯 10%、窗口用合计，会让腿一系统性偏钝。
    """
    v = classify_ex(limit_ups=limit_ups, index_pct=index_pct,
                    small_cap_ratio=small_cap_ratio, top_sector_conc=top_sector_conc,
                    limit_downs_abs=limit_downs_abs, pct_limit_down=pct_limit_down)
    return v["state"], v["advice"]


def classify_ex(
    limit_ups: int,
    index_pct: float,
    small_cap_ratio: float,
    top_sector_conc: float,
    limit_downs_abs: int | None = None,
    pct_limit_down: float | None = None,
) -> dict:
    """classify() 的元信息视图：多返回腿标志、缺口标志与判定依据。

    `gap=True` = 腿一退回了绝对家数兜底（分位序列缺失）。调用方**必须**把缺口
    显示给用户，禁止当成正常判定——2026-10-19 实锤：kcache 断供 → 分位算不出 →
    权威时间轴静默把交易日当假日、跳过不写盘，cron 还报 ok，面板徽标停在 10-16。
    「数据断供」不许被翻译成「今天没事」，这与 ABS_FALLBACK 不用 20 是同一条纪律。
    """
    # 主线 / 妖股（原逻辑不动，不依赖跌停腿）
    if limit_ups >= 60 and top_sector_conc >= 0.22:
        return _verdict("主线期", ADVICE_MAINLINE, False, False, False, "n/a")
    if limit_ups >= 40 and small_cap_ratio >= 0.65 and top_sector_conc < 0.22:
        return _verdict("妖股期", ADVICE_HOTMONEY, False, False, False, "n/a")

    # 腿一：滚动分位；缺失→绝对兜底并告警（gap 上浮给调用方）
    gap = pct_limit_down is None
    if gap:
        leg1 = (limit_downs_abs or 0) >= ABS_FALLBACK
        _warn_once(
            f"pct_limit_down 缺失，腿一退回绝对家数 {ABS_FALLBACK} 备案值——"
            f"若这是数据管线断供，本次判定不可信，请查 emotion_series.jsonl"
        )
    else:
        leg1 = pct_limit_down >= PANIC_PCT_Q
    basis = "abs_fallback" if gap else "pct"

    # 腿二：涨停枯竭 + 指数大跌
    leg2 = (limit_ups < LEG2_LU_MAX) and (index_pct < LEG2_IDX_PCT)

    if leg1 and leg2:
        return _verdict("恐慌期", ADVICE_PANIC_BOTH, leg1, leg2, gap, basis)
    if leg1:
        return _verdict("恐慌期", ADVICE_PANIC_LEG1, leg1, leg2, gap, basis)
    if leg2:
        return _verdict("恐慌期", ADVICE_PANIC_LEG2, leg1, leg2, gap, basis)
    return _verdict("平淡期", ADVICE_FLAT, leg1, leg2, gap, basis)


def classify_stats(stats: dict) -> tuple[str, str]:
    """从 meter 的 stats dict 判定（regime_meter.classify 的等价实现）。"""
    return classify(
        limit_ups=stats["limit_ups"],
        index_pct=stats["index_pct"],
        small_cap_ratio=stats["small_cap_board_ratio"],
        top_sector_conc=stats["top_sector_concentration"],
        limit_downs_abs=stats.get("limit_downs"),
        pct_limit_down=stats.get("pct_limit_down"),
    )


def pct_limit_down_from_series(nd: int, day: str, path: str | None = None) -> float | None:
    """给定 `day` 的跌停合计家数 `nd`，返回它在日序列尾窗（含当日虚拟 append）的经验分位。

    用于「当日尚未落盘」的场景（盘中实时 / 权威时间轴补当日）。窗口 = 前 249 个
    已有值 + 当日 nd，共 250。有效值不足 PCT_MIN_PERIODS 返回 None（→ 走兜底并告警）。
    """
    import json
    import os

    p = path or "/opt/data/fenjue/data/emotion_series.jsonl"
    if not os.path.exists(p):
        return None
    vals = []
    with open(p, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if r["date"] == day:      # 同日行剔除，避免与虚拟 append 双计
                continue
            v = r.get("limit_down")
            if v is not None:
                vals.append(int(v))
    win = vals[-(PCT_WINDOW - 1):] + [int(nd)]
    if len(win) < PCT_MIN_PERIODS:
        return None
    return round(sum(1 for v in win if v <= int(nd)) / len(win), 4)


def load_pct_series(path: str | None = None) -> dict[str, float | None]:
    """date -> pct_limit_down，来自 emotion_series.jsonl（合计口径，已算好）。

    三个消费者（regime_meter 实时、regime_daily_append 权威时间轴、
    regime_backtest_hcap 回测）**必须共用同一份分位序列**，否则面板徽标与回测
    会各按一套阈值出标签——这正是 2026-10-20 之前的病灶。
    """
    import json
    import os

    p = path or "/opt/data/fenjue/data/emotion_series.jsonl"
    out: dict[str, float | None] = {}
    if not os.path.exists(p):
        return out
    with open(p, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            out[r["date"]] = r.get("pct_limit_down")
    return out
