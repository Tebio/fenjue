#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""engine/overnight_effect.py — 隔夜效应全宇宙研究（卡 t_9e69cd05，AGENTS 落账见 #291）

①全宇宙 8 年收益分解：隔夜段（T收→T+1开）vs 盘中段（T+1开→T+1收），分年/regime；
②「尾盘买次日开盘卖」可执行策略口径：每日全宇宙持有隔夜段，换手 100%/日，
  成本走 engine/costs.py 唯一真源（FLAT_RT 平口径 + 真实费目三档资金），成本绞肉算清；
③隔夜收益预测力：per-date 横截面 corr(隔夜, 盘中) + 隔夜十分位→盘中均值（文献方向检验）。

口径
----
- 宇宙 = big_kcache 主板（60/00 前缀，≥300 bar），含已退市缺口（#265⑤ 方向已知：高估）。
- 隔夜 on = o[T+1]/c[T]-1；盘中 id = c[T+1]/o[T+1]-1；归属日 = T+1。停牌缝隙 >10 自然日剔除。
- 分解口径（①③）不剔一字；策略口径（②）剔「收盘封死涨停」（买不到），
  「一字跌停开」递延到首个非锁死开盘卖（≤3 日，兜底 c[T+4]）——买卖可行性双向建模。
- 指数对照 = data/index_sh000001.json 同口径。regime = regime_timeline_hcap.json（权威轴）。
- 复跑：.venv/bin/python engine/overnight_effect.py  （纯离线，零网络，~3 分钟）
产物：data/overnight_effect_20261016.json
"""
import glob
import json
import math
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import law_pipeline as lp  # noqa: E402  nw_t / deflated_sharpe 共享实现
from costs import FLAT_RT, roundtrip_cost  # noqa: E402  TAX-01 唯一真源

ROOT = Path("/opt/data/fenjue")
KC = ROOT / "data" / "big_kcache"
OUT = ROOT / "data" / "overnight_effect_20261016.json"
FEE_SLOTS = {"flat0.15%": FLAT_RT, "real_2w": roundtrip_cost(20000),
             "real_5w": roundtrip_cost(50000), "real_5k": roundtrip_cost(5000)}


def load_calendar():
    idx = json.loads((ROOT / "data/index_sh000001.json").read_text())
    return [k["date"] for k in idx], idx


def main():
    cal, idx_bars = load_calendar()
    nd = len(cal)
    cal64 = np.array(cal, dtype="datetime64[D]")
    regime = {r["date"]: r["regime"]
              for r in json.loads((ROOT / "data/regime_timeline_hcap.json").read_text())}
    reg_of = np.array([regime.get(d, "?") for d in cal])

    # 累加器（①③）：归属日=T+1
    sx = np.zeros(nd); sy = np.zeros(nd); sxx = np.zeros(nd)
    syy = np.zeros(nd); sxy = np.zeros(nd); cnt = np.zeros(nd)
    # 策略口径（②）：可执行子集的隔夜收益（含递延卖出），与纸面全量
    strat_sum = np.zeros(nd); strat_cnt = np.zeros(nd)
    on_store, id_store, di_store = [], [], []   # ③十分位用（float32 全量 ~6M 对）

    files = sorted(glob.glob(str(KC / "*.json")))
    nstk = 0
    for fp in files:
        code = Path(fp).stem
        if code[:2] not in ("60", "00"):
            continue
        ks = json.loads(open(fp).read())
        n = len(ks)
        if n < 300:
            continue
        nstk += 1
        c = np.array([k["close"] for k in ks])
        o = np.array([k["open"] for k in ks])
        h = np.array([k["high"] for k in ks])
        l = np.array([k["low"] for k in ks])
        dt = np.array([k["date"] for k in ks], dtype="datetime64[D]")
        pc = c[:-1]
        on = o[1:] / pc - 1
        intr = c[1:] / o[1:] - 1
        chg = c[1:] / pc - 1          # T+1 日收收涨幅（T 视角下一位）
        gapd = (dt[1:] - dt[:-1]).astype(np.int64)
        valid = (pc > 0) & (o[1:] > 0) & (gapd <= 10) & np.isfinite(on) & np.isfinite(intr)
        didx = np.searchsorted(cal64, dt[1:])
        v = valid & (didx < nd)
        np.add.at(sx, didx[v], on[v]); np.add.at(sy, didx[v], intr[v])
        np.add.at(sxx, didx[v], on[v] ** 2); np.add.at(syy, didx[v], intr[v] ** 2)
        np.add.at(sxy, didx[v], on[v] * intr[v]); np.add.at(cnt, didx[v], 1)
        on_store.append(on[v].astype(np.float32))
        id_store.append(intr[v].astype(np.float32))
        di_store.append(didx[v].astype(np.int32))
        # ---- ②策略口径：T 收盘买（封死涨停买不到→剔）→ T+1 开盘卖（一字跌停开递延）
        chgT = c[:-1] / np.concatenate([[np.nan], c[:-2]]) - 1   # T 日涨幅
        sealed_up = (chgT >= 0.098) & (c[:-1] >= h[:-1] * 0.999)  # T 收盘封死涨停
        buyable = valid & ~sealed_up
        # 一字跌停开（T+1）：开==高==低 且 开/昨收≤-9.5%
        one_down = (np.abs(o[1:] - h[1:]) <= o[1:] * 1e-6) & \
                   (np.abs(o[1:] - l[1:]) <= o[1:] * 1e-6) & (on <= -0.095)
        defer_idx = np.where(buyable & one_down)[0]
        sell_ret = on.copy()                       # 默认 T+1 开盘卖
        for i in defer_idx:                        # 递延卖出（罕见，逐笔处理）
            got = None
            for j in range(i + 2, min(i + 5, n - 1)):
                if o[j] > 0 and not (o[j] / c[j - 1] - 1 <= -0.095
                                     and abs(o[j] - h[j]) <= o[j] * 1e-6
                                     and abs(o[j] - l[j]) <= o[j] * 1e-6):
                    got = o[j] / c[i] - 1
                    break
            sell_ret[i] = got if got is not None else c[min(i + 4, n - 1)] / c[i] - 1
        b = buyable & ~one_down
        np.add.at(strat_sum, didx[b], sell_ret[b]); np.add.at(strat_cnt, didx[b], 1)
        if defer_idx.size:
            np.add.at(strat_sum, didx[defer_idx], sell_ret[defer_idx])
            np.add.at(strat_cnt, didx[defer_idx], 1)

    # ================= ① 分解 =================
    m_on = sx / np.maximum(cnt, 1)
    m_id = sy / np.maximum(cnt, 1)
    days = cnt > 0
    # 指数同口径
    ic = np.array([k["close"] for k in idx_bars]); io = np.array([k["open"] for k in idx_bars])
    idx_on = io[1:] / ic[:-1] - 1
    idx_id = ic[1:] / io[1:] - 1

    def curve(r):
        return float(np.prod(1 + r[np.isfinite(r)]))

    def seg_stats(mask, label):
        a, b = m_on[mask & days], m_id[mask & days]
        if len(a) < 5:
            return None
        return {"label": label, "days": len(a),
                "隔夜日均bp": round(1e4 * float(np.mean(a)), 2),
                "盘日均bp": round(1e4 * float(np.mean(b)), 2),
                "隔夜胜率%": round(100 * float(np.mean(a > 0)), 1),
                "盘中胜率%": round(100 * float(np.mean(b > 0)), 1),
                "隔夜累计x": round(curve(a), 3), "盘中累计x": round(curve(b), 3),
                "隔夜t": round(float(np.mean(a) / (np.std(a) / math.sqrt(len(a)))), 1),
                "盘中t": round(float(np.mean(b) / (np.std(b) / math.sqrt(len(b)))), 1)}

    years = np.array([d[:4] for d in cal])
    by_year = [seg_stats(years == y, y) for y in sorted(set(years))]
    by_regime = [seg_stats(reg_of == r, r) for r in ("恐慌期", "平淡期", "妖股期", "主线期")]
    full = seg_stats(np.ones(nd, bool), "全期")
    idx_full = {"隔夜累计x": round(curve(idx_on), 3), "盘中累计x": round(curve(idx_id), 3),
                "隔夜日均bp": round(1e4 * float(np.mean(idx_on)), 2),
                "盘中日均bp": round(1e4 * float(np.mean(idx_id)), 2)}

    # ================= ② 尾盘买次日开盘卖（成本生死线） =================
    g = strat_sum / np.maximum(strat_cnt, 1)
    gd = g[strat_cnt > 0]
    strat = {"纸面全宇宙隔夜日均bp": round(1e4 * float(np.mean(m_on[days])), 2),
             "可执行口径隔夜日均bp": round(1e4 * float(np.mean(gd)), 2),
             "成本口径往返%": {k: round(100 * v, 3) for k, v in FEE_SLOTS.items()},
             "成本生死线bp/日": round(1e4 * FEE_SLOTS["real_2w"], 1),
             "by_year": {}}
    for y in sorted(set(years)):
        m = (years == y) & (strat_cnt > 0)
        row = {"gross_bp": round(1e4 * float(np.mean(g[m])), 2)}
        for k, f in FEE_SLOTS.items():
            row[f"net_{k}_x"] = round(curve(g[m] - f), 3)
        strat["by_year"][y] = row
    strat["全期"] = {f"net_{k}_x": round(curve(gd - f), 3) for k in FEE_SLOTS}
    strat["全期"]["gross_x"] = round(curve(gd), 3)
    # 净日度序列 DSR（trials 登记：本研究全局 trials 见 _meta）
    net_daily = gd - FEE_SLOTS["real_2w"]
    sr = float(np.mean(net_daily) / np.std(net_daily)) if np.std(net_daily) > 0 else 0.0
    strat["净日度SR"] = round(sr, 4)
    strat["DSR"] = lp.deflated_sharpe(sr, int(len(gd)), float(lp._skew(net_daily)),
                                      float(lp._kurt(net_daily)), trials=12)

    # ================= ③ 隔夜→盘中 预测力 =================
    cm = (cnt > 30)
    cov = sxy[cm] - sx[cm] * sy[cm] / cnt[cm]
    vx = sxx[cm] - sx[cm] ** 2 / cnt[cm]
    vy = syy[cm] - sy[cm] ** 2 / cnt[cm]
    ok = (vx > 0) & (vy > 0)
    corr_d = cov[ok] / np.sqrt(vx[ok] * vy[ok])
    pred = {"per_date_corr": {"days": int(ok.sum()), "mean": round(float(np.mean(corr_d)), 4),
                              "median": round(float(np.median(corr_d)), 4),
                              "负相关日占比%": round(100 * float(np.mean(corr_d < 0)), 1)}}
    # 十分位：每日横截面按 on 分十档 → 各档当日 id 均值，跨日平均
    on_all = np.concatenate(on_store); id_all = np.concatenate(id_store)
    di_all = np.concatenate(di_store)
    bins_sum = np.zeros(10); bins_cnt = np.zeros(10)
    reg_bin = {r: (np.zeros(10), np.zeros(10)) for r in ("恐慌期", "平淡期", "妖股期", "主线期")}
    order = np.argsort(di_all, kind="stable")
    on_s, id_s, di_s = on_all[order], id_all[order], di_all[order]
    edges = np.flatnonzero(np.diff(di_s)) + 1
    starts = np.concatenate([[0], edges]); ends = np.concatenate([edges, [len(di_s)]])
    for s0, e0 in zip(starts, ends):
        a, b = on_s[s0:e0], id_s[s0:e0]
        if len(a) < 30:
            continue
        q = np.argsort(np.argsort(a)) * 10 // len(a)     # 0..9 分位档
        rlab = reg_of[di_s[s0]]
        for k in range(10):
            mk = q == k
            bins_sum[k] += float(np.mean(b[mk])); bins_cnt[k] += 1
            if rlab in reg_bin:
                ss, cc = reg_bin[rlab]
                ss[k] += float(np.mean(b[mk])); cc[k] += 1
    pred["隔夜十分位_盘中均值bp"] = [
        {"档": k + 1, "盘中bp": round(1e4 * bins_sum[k] / max(bins_cnt[k], 1), 2)}
        for k in range(10)]
    pred["分regime_底档vs顶档_盘中bp"] = {
        r: {"底档(on最负)": round(1e4 * reg_bin[r][0][0] / max(reg_bin[r][1][0], 1), 2),
            "顶档(on最正)": round(1e4 * reg_bin[r][0][9] / max(reg_bin[r][1][9], 1), 2)}
        for r in reg_bin}

    out = {"_meta": {"owner": "engine.overnight_effect", "task": "t_9e69cd05",
                     "inputs": ["data/big_kcache", "data/index_sh000001.json",
                                "data/regime_timeline_hcap.json"],
                     "universe_stocks": nstk, "calendar_days": nd,
                     "trials_registered": 12,
                     "note": "①分解不剔一字；②策略剔封死涨停买不进+一字跌停开递延卖出；"
                             "成本=costs.py 唯一真源；DSR trials=12"},
           "①收益分解": {"全期": full, "指数对照": idx_full,
                       "by_year": [x for x in by_year if x],
                       "by_regime": [x for x in by_regime if x]},
           "②尾盘买次日开盘卖": strat,
           "③隔夜预测力": pred}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(json.dumps({"full": full, "index": idx_full,
                      "strat_all": strat["全期"], "corr": pred["per_date_corr"],
                      "decile": pred["隔夜十分位_盘中均值bp"]}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
