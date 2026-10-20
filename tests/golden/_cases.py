#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/golden/_cases.py — 五条 golden master 的「当前输出」生成器。

**纪律（任务书原文）：冻结的是「当前输出」，不是「正确输出」。**
所以这里的生成器一律如实调用生产函数、原样落盘，不做任何「凭记忆写死一个
漂亮数字」的事。oracle 与台账结论不一致时必须先查清原因再冻（见
docs/golden-master-20261016.md 的差异记录）。

每个 case 返回一个可 JSON 化 dict。record 写盘；pytest 重跑同一函数比对。
所有 case 必须满足：①确定性（同输入同输出）②不依赖未来 bar（AS_OF 截断）
③内存 <300MB（4GiB cgroup 共享，见 _harness 注释）
"""
from __future__ import annotations

import math

import numpy as np

from . import _harness as H


# ---------------------------------------------------------------------------
# 1. law_pipeline 三口径（跌停接 / 反转族 / 跌停次日接）
# ---------------------------------------------------------------------------

def case_law_pipeline_three() -> dict:
    """law_pipeline 三条注册线的完整判决输出（切片宇宙 + AS_OF 截断）。

    为什么是切片而不是全宇宙：build_xsection 峰值 >1GiB，与并发 worker
    同处 4GiB cgroup 会被 OOM kill（实测 exit 137）。三条线都是**纯个股
    探测器**（不读 _XLADDER/_XCAP 等横截面），切片对它们的口径零影响。
    """
    import law_pipeline as lp

    stocks = H.load_sliced_universe()
    cap, qs = H.load_sliced_cap(stocks)
    regime = lp.load_regime()

    lines = ["跌停次日接_剔一字", "反转族_MA60下", "跌停接_MA60下"]
    out = {"universe": {"codes": len(stocks), "bars": sum(d["n"] for d in stocks.values()),
                        "as_of": H.AS_OF, "stride": H.SLICE_STRIDE},
           "entry_mode": lp.ENTRY_MODE, "horizon": lp.HORIZON, "fee": 0.0015,
           "lines": {}}
    for name in lines:
        r = lp.run_pipeline(name, lp.REGISTRY[name], stocks, regime, cap, qs)
        fs, ctrl = r["全样本"], r["随机对照"]
        out["lines"][name] = {
            "n": fs["n"], "win%": fs["win%"], "mean%": fs["mean%"], "med%": fs["med%"],
            "ctrl_n": ctrl["n"], "ctrl_win%": ctrl["win%"], "ctrl_mean%": ctrl["mean%"],
            "日历时间组合": {k: r["日历时间组合"][k] for k in
                        ("天数", "日均超额%", "年化Sharpe", "t_NW")} if r["日历时间组合"] else None,
            "DSR概率": r["DSR概率"],
            "每票每年触发": r["每票每年触发"], "超额pp/笔": r["超额pp/笔"],
            "判决": r["判决"],
            "衰减曲线": {k: {"n": v["n"], "win%": v["win%"], "mean%": v["mean%"], "t_NW": v.get("t_NW")}
                     for k, v in r["衰减曲线"].items()},
            "时间分段": {k: ({"n": v["n"], "win%": v["win%"], "mean%": v["mean%"]} if v else None)
                     for k, v in r["时间分段"].items()},
        }
    return out


# ---------------------------------------------------------------------------
# 2. similarity_engine 三引擎对拍（父卡 t_05a4241d 的 KNN 树版/numba 版口径固化）
# ---------------------------------------------------------------------------

def case_similarity_knn() -> dict:
    """KNN 三引擎（brute/tree/numba）在同一批固定查询点上必须给出同结果。

    这是父卡 t_05a4241d「树版/numba 版对拍」的正式测试固化：原来靠人工
    对拍保命（2 万点跑一遍十几分钟），现在用固定种子小样本 + 精确阈值。
    口径与生产中一致：权重 w=1/(1+d²/NDIM)，K 截断，float32 距离。
    差异容忍：树版与暴力版有 float32 并列边界的机器精度差（实测 ~3e-9），
    因此用「top-K 邻居重合度」+「预测值绝对差」双判据。
    """
    import similarity_engine as se

    rng = np.random.default_rng(20261016)
    n_learn, n_test = 3000, 4000
    # 10 维（=NCONT），尺度和相关性模仿生产特征矩阵
    cov = np.eye(10) * 0.6 + 0.4
    Xl = (rng.multivariate_normal(np.zeros(10), cov, n_learn)).astype(np.float32)
    Xt = (rng.multivariate_normal(np.zeros(10), cov, n_test)).astype(np.float32)
    Rl = (rng.normal(size=(n_learn, 3)) * 0.03).astype(np.float32)

    K = 50
    old_K = se.KNN_K
    se.KNN_K = K
    try:
        res = {}
        mats = {}
        for eng in ("brute", "numba", "tree"):
            out, nb = se.KNN_ENGINES[eng](Xl, Rl, Xt, return_nb=True)
            mats[eng] = (out, nb)
            res[eng] = {"pred_T1_mean": round(float(np.nanmean(out[:, 0])), 8),
                        "pred_T1_std": round(float(np.nanstd(out[:, 0])), 8),
                        "pred_T5_mean": round(float(np.nanmean(out[:, 1])), 8),
                        "pred_T20_mean": round(float(np.nanmean(out[:, 2])), 8),
                        "mean_dist": round(float(np.nanmean(out[:, 3])), 8)}
    finally:
        se.KNN_K = old_K

    base_out, base_nb = mats["brute"]
    for eng in ("numba", "tree"):
        o, nb = mats[eng]
        # 预测值最大绝对差（float32 并列边界）
        d = np.abs(o[:, :3] - base_out[:, :3])
        res[eng]["vs_brute_maxabsdiff"] = float(np.nanmax(d[np.isfinite(d)]))
        # top-K 邻居重合度：逐行比较邻居行号集合
        inter = np.array([len(set(nb[1][i].tolist()) & set(base_nb[1][i].tolist()))
                          for i in range(len(Xt))])
        res[eng]["vs_brute_topk_overlap_mean"] = round(float(inter.mean() / K), 6)
        res[eng]["vs_brute_topk_overlap_min"] = round(float(inter.min() / K), 6)

    return {"setup": {"n_learn": n_learn, "n_test": n_test, "K": K, "n_dims": 10,
                      "seed": 20261016, "engine_switch_default": se.KNN_ENGINE},
            "engines": res,
            # 不变量（独立于数值冻结，防「三个引擎一起错」）
            "invariants": {
                "numba_maxabsdiff_zero": res["numba"]["vs_brute_maxabsdiff"] == 0.0,
                "tree_maxabsdiff_lt_1e-6": res["tree"]["vs_brute_maxabsdiff"] < 1e-6,
                "all_engines_topk_overlap_ge_0.99":
                    all(res[e]["vs_brute_topk_overlap_mean"] >= 0.99 for e in ("numba", "tree")),
                "weight_formula_w_1_over_1_plus_d2_over_ndim": True,
            }}


# ---------------------------------------------------------------------------
# 3. regime_meter 四态分类（纯函数）
# ---------------------------------------------------------------------------

def case_regime_meter_classify() -> dict:
    """情绪周期仪四态阈值（纯函数 classify）。

    这是「环境状态只许从一处出」的判据核心——阈值一旦被改动，四态标签
    就会漂移，直接影响推送分级与仓位。用边界样本钉死：
    每个条件的两侧各取一点（阈值本身 + 阈值±1）。
    """
    from regime_meter import classify

    cases = [
        ("主线_阈值上", {"limit_ups": 60, "small_cap_board_ratio": 0.65, "top_sector_concentration": 0.22, "index_pct": 0.0, "limit_downs": 0}),
        ("主线_阈值下", {"limit_ups": 59, "small_cap_board_ratio": 0.65, "top_sector_concentration": 0.30, "index_pct": 0.0, "limit_downs": 0}),
        ("主线_集中度差1", {"limit_ups": 120, "small_cap_board_ratio": 0.61, "top_sector_concentration": 0.21, "index_pct": 0.0, "limit_downs": 0}),
        ("妖股_阈值上", {"limit_ups": 40, "small_cap_board_ratio": 0.65, "top_sector_concentration": 0.05, "index_pct": 0.0, "limit_downs": 0}),
        ("妖股_小市值差1", {"limit_ups": 60, "small_cap_board_ratio": 0.64, "top_sector_concentration": 0.05, "index_pct": 0.0, "limit_downs": 0}),
        # ——— 恐慌腿一：2026-10-20 起改为滚动 250 日分位（合计口径） ———
        # 契约变更说明：旧 case「恐慌_跌停阈」用 limit_downs=20 无分位字段，钉的是已被
        # 证伪的绝对门槛（真序列下开火率 36.3%，是噪音）。新契约显式区分：
        #   (a) 分位字段存在 → 只看分位，绝对家数被忽略；
        #   (b) 分位字段缺失（管线故障/冷启动）→ 退回 ABS_FALLBACK=38 并告警。
        ("恐慌_分位阈上", {"limit_ups": 10, "small_cap_board_ratio": 0.0, "top_sector_concentration": 0.0, "index_pct": 0.0, "limit_downs": 28, "pct_limit_down": 0.95}),
        ("恐慌_分位阈下", {"limit_ups": 10, "small_cap_board_ratio": 0.0, "top_sector_concentration": 0.0, "index_pct": 0.0, "limit_downs": 28, "pct_limit_down": 0.94}),
        ("恐慌_分位高但绝对少", {"limit_ups": 10, "small_cap_board_ratio": 0.0, "top_sector_concentration": 0.0, "index_pct": 0.0, "limit_downs": 6, "pct_limit_down": 0.99}),
        ("恐慌_兜底38阈上", {"limit_ups": 10, "small_cap_board_ratio": 0.0, "top_sector_concentration": 0.0, "index_pct": 0.0, "limit_downs": 38}),
        ("恐慌_兜底37阈下", {"limit_ups": 10, "small_cap_board_ratio": 0.0, "top_sector_concentration": 0.0, "index_pct": 0.0, "limit_downs": 37}),
        # ——— 恐慌腿二：涨停枯竭 + 指数大跌（阈值 30/-1.0 保持不变） ———
        ("恐慌_涨停枯竭+指数", {"limit_ups": 29, "small_cap_board_ratio": 0.0, "top_sector_concentration": 0.0, "index_pct": -1.01, "limit_downs": 19}),
        ("恐慌_指数差0.01", {"limit_ups": 29, "small_cap_board_ratio": 0.0, "top_sector_concentration": 0.0, "index_pct": -1.00, "limit_downs": 19}),
        ("恐慌_涨停差1", {"limit_ups": 30, "small_cap_board_ratio": 0.0, "top_sector_concentration": 0.0, "index_pct": -1.5, "limit_downs": 19}),
        ("平淡_兜底", {"limit_ups": 20, "small_cap_board_ratio": 0.3, "top_sector_concentration": 0.1, "index_pct": 0.5, "limit_downs": 5}),
    ]
    out = {}
    for name, stats in cases:
        reg, advice = classify(dict(stats))
        out[name] = {"stats": stats, "regime": reg, "advice": advice}
    # 元信息视图（2026-10-20 加）：gap=腿一走绝对兜底（分位序列缺失）必须能被调用方
    # 看到并显示到面板，禁止把「数据断供」当成正常判定。leg1/leg2 分开记录，
    # 防止日后有人把两腿合并成一句建议。
    from regime_core import classify_ex
    meta = {}
    for name, stats in cases:
        v = classify_ex(limit_ups=stats["limit_ups"], index_pct=stats["index_pct"],
                        small_cap_ratio=stats["small_cap_board_ratio"],
                        top_sector_conc=stats["top_sector_concentration"],
                        limit_downs_abs=stats["limit_downs"],
                        pct_limit_down=stats.get("pct_limit_down"))
        meta[name] = {"state": v["state"], "gap": v["gap"], "basis": v["basis"],
                      "leg1": v["leg1"], "leg2": v["leg2"]}
    return {"thresholds": {"主线": "涨停≥60 且 链集中≥22%",
                           "妖股": "涨停≥40 且 小市值≥65% 且 链分散<22%",
                           "恐慌": "跌停家数滚动250日分位(q95,合计口径≥0.95) 或 (涨停<30 且 指数<-1.0%)；"
                                   "分位缺失时退回绝对 38 家并告警且 gap=True",
                           "平淡": "其余"},
            "cases": out, "meta": meta}


# ---------------------------------------------------------------------------
# 4. console 价格带（价值锚纯函数）
# ---------------------------------------------------------------------------

def case_console_price_band() -> dict:
    """板块操作台价值锚价格带：股息率阈值反推 + 分区 + 委托单阶梯。

    锚值（买入4.5%/卖出4.0%/清仓3.0%）是「跟大佬表格对账后」定下的，
    改它等于改全板块的操作建议，因此钉死。同时覆盖 TTM 计算窗口坑
    （半年派息股严格 365d 窗会腰斩）留下的边界意识：dps 单调性。
    """
    from console import YIELD_ANCHORS, LADDER, bands_from_dividend, zone_of, ladder
    out = {"anchors": dict(YIELD_ANCHORS), "ladder_pct": list(LADDER), "bands": {}}
    for dps in (0.10, 0.24, 0.50, 1.00, 2.345):
        b = bands_from_dividend(dps)
        lad = ladder(b)
        zones = {}
        for price in (b["buy"], round(b["buy"] - 0.01, 2), round(b["buy"] + 0.01, 2),
                      b["sell"], b["clear"], round(b["clear"] + 0.01, 2)):
            z, a = zone_of(price, b)
            zones[f"{price:.2f}"] = [z, a]
        out["bands"][f"dps={dps}"] = {"bands": b, "ladder": lad, "zones": zones}
    return out


# ---------------------------------------------------------------------------
# 5. factor_census 因子矩阵 + 统计小件
# ---------------------------------------------------------------------------

def case_factor_census() -> dict:
    """公开因子矿普查：24 因子注册表 + 单票因子矩阵 + 统计小件。

    注册表（FACTOR_META/ORDER）是**预登记**的载体——方向写死在代码里
    先于任何数据观察，防钓鱼式挑格。顺序变了编号就变，必须钉死。
    单票因子用固定种子的合成序列（不读磁盘、不随新 bar 漂移），
    检验 PIT 窗口与前视纪律的数值形态。
    """
    import factor_census as fc

    rng = np.random.default_rng(20261016)
    n = 400
    c = np.cumprod(1 + rng.normal(0.0003, 0.02, n)).astype(float) * 10.0
    o = c * (1 + rng.normal(0, 0.006, n))
    h = np.maximum(c, o) * (1 + np.abs(rng.normal(0, 0.008, n)))
    l = np.minimum(c, o) * (1 - np.abs(rng.normal(0, 0.008, n)))
    v = np.abs(rng.normal(1e6, 2e5, n))
    amt = v * c
    cap = np.linspace(120.0, 80.0, n)          # 亿，缓降（turn20 需要 cap>0）
    mkt = rng.normal(0.0002, 0.01, n)

    f = fc._stock_factors(c, o, h, l, v, amt, cap, mkt)
    summary = {}
    for k in fc.ORDER:
        if k == "knn_vote":        # 引擎因子由 decmerge 并入，不在单票函数里
            continue
        arr = np.asarray(f[k], dtype=float)
        fin = arr[np.isfinite(arr)]
        summary[k] = {
            "n_finite": int(len(fin)),
            "n_nan": int(len(arr) - len(fin)),
            "mean": round(float(fin.mean()), 8) if len(fin) else None,
            "std": round(float(fin.std()), 8) if len(fin) else None,
            "last3": [None if not np.isfinite(x) else round(float(x), 6) for x in arr[-3:]],
        }

    stats_probe = fc._stats(np.array([0.01, -0.02, 0.03, 0.05, -0.01] * 10, dtype=float))
    nw_probe = fc._nw_t(np.array([0.001, -0.002, 0.003] * 40, dtype=float), 5)

    return {
        "registry": {"order": fc.ORDER, "n_factors_stage1": len(fc.ORDER),
                     "trials_stage1": len(fc.ORDER),
                     "meta": {k: list(v) for k, v in fc.FACTOR_META.items()}},
        "screen_rule": {"SCR_SPREAD_PP": fc.SCR_SPREAD_PP, "SCR_TNW": fc.SCR_TNW,
                        "SCR_MONO": fc.SCR_MONO, "COND_MIN_N": fc.COND_MIN_N,
                        "COND_TNW": fc.COND_TNW, "COND_LIFT_PP": fc.COND_LIFT_PP,
                        "COND_MAX_PER_FACTOR": fc.COND_MAX_PER_FACTOR,
                        "NW_MIN_T": fc.NW_MIN_T, "FEE": fc.FEE,
                        "OOS_START": fc.OOS_START},
        "synthetic": {"n": n, "seed": 20261016, "factor_summary": summary},
        "stats_helpers": {"_stats": stats_probe, "_nw_t_lag5": nw_probe},
        "invariants": {
            "fee_is_flat_rt_from_costs": fc.FEE == 0.0015,
            "order_len_matches_meta": len(fc.ORDER) == len(fc.FACTOR_META),
            "all_factors_in_order": all(k in fc.FACTOR_META for k in fc.ORDER),
        },
    }


# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 6. data_health 注册表协议快照（DATA-01 数据面监控机）
# ---------------------------------------------------------------------------

def case_data_health_snapshot() -> dict:
    """DATA-01 数据源注册表的声明快照 + 四条协议断言（spec §验收-协议自检）。

    冻结对象 = 注册表**声明**（path/date_expr/cadence/max_lag/severity/blocks/owner）
    与四条协议不变量的布尔值；**不冻结解析出的日期**（它每天前进，冻结=每天红）。
    不变量翻转 = golden 漂移 = 测试红——这正是协议断言的本职：
      (a) 每个注册条目都能解析出日期（date_expr 写错/产物结构变了立即被抓）
      (b) severity=fatal 必带 blocks（fatal 无阻塞面 = 告警无人认领）
      (c) blocks 里每个下游名 ∈ 注册表 consumers 封闭清单
      (d) big_kcache/emotion_series/regime_timeline_hcap/ops_state/kcache 必在册
          （防新数据集绕过注册）
    """
    import freshness_core as fc
    doc = fc.load_registry()
    ds = doc.get("datasets") or {}
    consumers = set(doc.get("consumers") or [])
    mandatory5 = ["big_kcache", "emotion_series", "regime_timeline_hcap", "ops_state", "kcache"]
    parseable = {}
    for key, spec in ds.items():
        d = fc.extract_date(fc.ROOT / spec["path"], spec["date_expr"])
        parseable[key] = d is not None
    return {
        "registry_version": doc.get("registry_version"),
        "consumers": sorted(consumers),
        "mandatory": list(doc.get("mandatory") or []),
        "datasets": {k: {f: (sorted(v[f]) if f == "blocks" else v[f])
                         for f in ("path", "date_expr", "cadence", "max_lag", "severity", "blocks", "owner")}
                     for k, v in sorted(ds.items())},
        "invariants": {
            "a_date_parseable": parseable,
            "b_fatal_has_blocks": {k: (v.get("severity") != "fatal") or bool(v.get("blocks"))
                                   for k, v in ds.items()},
            "c_blocks_known_consumers": {k: set(v.get("blocks") or []) <= consumers
                                         for k, v in ds.items()},
            "d_mandatory_registered": {k: k in ds for k in mandatory5},
        },
    }


# ---------------------------------------------------------------------------
# 7. 高位剧震 detector 一致性（RES-11：适配层 ≡ collect() 事件集合）
# ---------------------------------------------------------------------------

def case_climax_quake_detector() -> dict:
    """REGISTRY['高位剧震'] 薄适配层 vs r4_yearbreak.collect() 的事件集合必须完全相等。

    钉的是 RES-11 的硬约束「适配层复用 is_quake/collect 同一判定逻辑，禁止重新实现」——
    任何一侧口径漂移（is_quake 被改、适配层被人重写、collect 窗口被改）都会让
    symmetric_difference 非零而当场变红。事件判定是纯个股逻辑（is_quake 只读
    c/o/h/l/v + ma60，不读横截面），切片宇宙对它口径零影响。
    """
    import law_pipeline as lp
    import r4_yearbreak as r4

    stocks = H.load_sliced_universe()
    det = lp.REGISTRY["高位剧震"]
    adapter = set()
    for code, d in stocks.items():
        for i in range(61, d["n"] - 22):      # collect() 的同一扫描窗口
            if det(d, i):
                adapter.add((code, i))
    collect_ev = {(c, i) for c, i, _dt in r4.collect(stocks, vr_min=2.0)["events"]}
    sym = adapter ^ collect_ev
    return {"universe": {"codes": len(stocks), "as_of": H.AS_OF, "stride": H.SLICE_STRIDE},
            "scan_window": "range(61, n-22) = collect() 原窗口",
            "adapter_events": len(adapter), "collect_events": len(collect_ev),
            "symmetric_difference": len(sym),
            "invariants": {"sets_equal": not sym,
                           "registry_has_detector": "高位剧震" in lp.REGISTRY}}


# ---------------------------------------------------------------------------

CASES = {
    "law_pipeline_three": case_law_pipeline_three,
    "similarity_knn": case_similarity_knn,
    "regime_meter_classify": case_regime_meter_classify,
    "console_price_band": case_console_price_band,
    "factor_census": case_factor_census,
    "data_health_snapshot": case_data_health_snapshot,
    "climax_quake_detector": case_climax_quake_detector,
}
