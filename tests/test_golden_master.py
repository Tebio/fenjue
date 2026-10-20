#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_golden_master.py — PLAT-04 回归测试（每个 golden 一个用例）。

跑法：`.venv/bin/python -m pytest -q tests/test_golden_master.py`
      （或整目录 `pytest -q tests`，verify.sh 第 3 步）

设计要点：
- **oracle 存在才断言数值**；oracle 缺失时 SKIP 并明示（VERIFY.md §3 禁止
  「SKIP 冒充通过」——所以缺 oracle 的 SKIP 会打印明确原因，且
  `pytest.skip` 会让 verify.sh 的 `--strict-skips` 之外的调用仍显式可见）。
- 数值容忍带 0.1pp（VERIFY.md §4）；计数类严格相等。
- 不变量断言独立于 oracle：即使 oracle 被误刷新，不变量仍能抓住
  「三个引擎一起错」「注册表被改序」这类结构性破坏。
"""
from __future__ import annotations

import pytest

from tests.golden import _cases as C
from tests.golden import _harness as H

NAMES = list(C.CASES)


def _run(name: str):
    try:
        want = H.load_oracle(name)
    except FileNotFoundError:
        pytest.skip(f"oracle 未建立：tests/golden/oracle/{name}.json"
                    f"（先跑 python -m tests.golden.record {name} 并由人确认后冻结）")
    got = C.CASES[name]()
    got.pop("_meta", None)
    want.pop("_meta", None)
    diffs = H.compare(got, want)
    assert not diffs, ("golden 漂移（容忍带 %.1fpp）:\n  %s"
                       % (H.DRIFT_PP, "\n  ".join(diffs[:40])))
    return got


@pytest.mark.parametrize("name", NAMES)
def test_golden_master(name):
    _run(name)


# ---------------------------------------------------------------------------
# 不变量（不依赖 oracle，抓结构性破坏）
# ---------------------------------------------------------------------------

def test_law_pipeline_registry_intact():
    """注册表条目数与三条被测线仍在册（防误删/改名）。"""
    import law_pipeline as lp
    assert len(lp.REGISTRY) >= 60, f"REGISTRY 条目数异常：{len(lp.REGISTRY)}"
    for name in ("跌停次日接_剔一字", "反转族_MA60下", "跌停接_MA60下"):
        assert name in lp.REGISTRY, f"注册线缺失：{name}"
    assert lp.ENTRY_MODE == "next_open", "入场口径被改动（全体系口径锚）"
    assert lp.NW_MIN_T == 3.0, "Harvey 门槛被改动"


def test_similarity_engines_agree():
    """三引擎必须在同一批查询点上给出同结果（父卡 t_05a4241d 对拍的固化版）。"""
    got = C.case_similarity_knn()
    inv = got["invariants"]
    assert inv["numba_maxabsdiff_zero"], "numba 版与暴力版结果不一致（应逐位相同）"
    assert inv["tree_maxabsdiff_lt_1e-6"], "树版与暴力版差异超机器精度"
    assert inv["all_engines_topk_overlap_ge_0.99"], "top-K 邻居重合度过低"
    assert got["engines"]["tree"]["vs_brute_topk_overlap_min"] >= 0.99, "存在邻居几乎不重合的查询点"


def test_factor_census_registry_frozen():
    """因子注册表顺序 = 编号（顺序变了 trials 分母与 DSR 全变）。"""
    import factor_census as fc
    got = C.case_factor_census()
    assert got["registry"]["order"] == fc.ORDER
    assert got["registry"]["n_factors_stage1"] == 24, "stage1 因子数应为 24（+knn_vote=25）"
    assert got["invariants"]["fee_is_flat_rt_from_costs"]
    assert fc.FEE == 0.0015


def test_regime_thresholds_positive():
    """四态分类在边界上不得出现「同一 stats 两个标签」或异常。"""
    got = C.case_regime_meter_classify()
    labels = {v["regime"] for v in got["cases"].values()}
    assert labels <= {"主线期", "妖股期", "恐慌期", "平淡期"}, f"出现未知标签：{labels}"
    # 每个条件的两侧必须落在不同标签（阈值真有判别力）
    c = got["cases"]
    assert c["主线_阈值上"]["regime"] == "主线期"
    assert c["主线_阈值下"]["regime"] != "主线期"
    assert c["妖股_阈值上"]["regime"] == "妖股期"
    # 腿一（2026-10-20 改分位口径）：分位两侧 + 兜底两侧 + 分位优先于绝对家数
    assert c["恐慌_分位阈上"]["regime"] == "恐慌期"
    assert c["恐慌_分位阈下"]["regime"] != "恐慌期"
    assert c["恐慌_兜底38阈上"]["regime"] == "恐慌期"
    assert c["恐慌_兜底37阈下"]["regime"] != "恐慌期"
    assert c["恐慌_分位高但绝对少"]["regime"] == "恐慌期", "分位字段存在时必须忽略绝对家数"
    # 腿二两侧
    assert c["恐慌_涨停枯竭+指数"]["regime"] == "恐慌期"
    assert c["恐慌_指数差0.01"]["regime"] != "恐慌期"
    assert c["恐慌_涨停差1"]["regime"] != "恐慌期"
    # 两腿的建议动作必须不同（腿一=反弹窗口，腿二=降进攻频率）
    assert c["恐慌_分位阈上"]["advice"] != c["恐慌_涨停枯竭+指数"]["advice"], \
        "腿一与腿二的恐慌建议必须分开给——腿一是反弹窗口，腿二是趋势弱势，共用一句会反向操作"
    # 缺口标志（2026-10-20）：分位缺失必须能被下游看见，禁止把数据断供当正常判定
    m = got["meta"]
    assert m["恐慌_分位阈上"]["gap"] is False and m["恐慌_分位阈上"]["basis"] == "pct"
    assert m["恐慌_兜底38阈上"]["gap"] is True, "无分位字段时必须标 gap，面板才能显示数据缺口"
    assert m["恐慌_兜底38阈上"]["basis"] == "abs_fallback", "兜底判定的 basis 必须写实，不许伪装成 pct"
    assert m["恐慌_兜底37阈下"]["gap"] is True
    assert m["恐慌_兜底38阈上"]["leg1"] is True and m["恐慌_分位阈上"]["leg1"] is True
    assert m["恐慌_涨停枯竭+指数"]["leg1"] is False and m["恐慌_涨停枯竭+指数"]["leg2"] is True
    assert m["恐慌_分位阈上"]["leg2"] is False
    # 元信息视图与二元组视图不得分歧（同一判定两处出标签=老病灶）
    for name, v in m.items():
        assert v["state"] == c[name]["regime"], f"{name}：classify_ex 与 classify 标签不一致"


def test_console_bands_monotonic():
    """价格带必须单调：买入线 ≤ 卖出线 ≤ 清仓线（锚反了会把清仓区当买入区）。"""
    got = C.case_console_price_band()
    for key, v in got["bands"].items():
        b = v["bands"]
        assert b["buy"] <= b["sell"] <= b["clear"], f"{key} 价格带非单调：{b}"
        assert b["add50"] <= b["buy"], f"{key} 5%加仓线应不高于买入线：{b}"
