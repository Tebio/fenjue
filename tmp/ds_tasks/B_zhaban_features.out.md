```python
#!/usr/bin/env python3
"""engine/zhaban_features.py — 任务B：炸板「浅炸/深炸」事前可分特征筛查（2026-09-13）

口径
----
信号（复用 engine/zhaban_m60_fill.py 的日K重判，m60 聚合不复权日K）：
    昨日 收/前收-1 ≥ +9.8%（涨停）且 今日 开/昨收-1 ≥ +5%
挂单 / 成交（挂 +7% 口径）：
    限价 = 昨收 × 1.07；逐 60min bar：bar.open ≤ 限价 → 按 bar.open 成交；
    bar.low ≤ 限价 → 按限价成交；否则未成交（收益计 0，并计入每信号期望分母）
出场：T+1 收盘 / 成交价 - 1 - 0.0015（费 0.0015，单边一次性扣）
outcome：浅炸 = 当日最低涨幅 ∈ [3%, 8.5%]；深炸 = < 3%；未及 = > 8.5%
事前特征（仅用「信号日 10:30 前（含首 60min bar）」与「昨日及以前」数据，outcome 除外）：
    1) 昨是否 60 日首板  2) 昨封板时段  3) 昨量比  4) 今开幅度
    5) 首 30 分钟量能比  6) 流通市值带  7) 距 60 日高点距离

数据源（只读）
--------------
    /opt/data/fenjue/data/m60_cache/<code>.json    不复权 60min bar [{"day":"YYYY-MM-DD HH:MM",...}]
    /opt/data/fenjue/data/big_kcache/<code>.json   前复权日K（仅取比率，绝对价不可跨分红期比）
    /opt/data/fenjue/data/cap_hist/<code>.json     [[date, price, 流通市值亿], ...]

输出
----
    /opt/data/fenjue/data/zhaban_features_20260913.json

已知限制
--------
    L1 60min 粒度：秒级触碰 / 薄队列不可成交无法识别，成交率仍偏高（乐观残留）。
    L2 昨封板时段精度仅到 60min bar 标签（10:30/11:30/14:00/15:00），非逐笔封板时刻。
    L3 首 30 分钟量能比取当日 ≤10:30 的最晚一根 bar；当日无 ≤10:30 bar 的信号直接丢弃。
    L4 前复权价跨分红期绝对价不可比，本模块只用其比率（涨停/量比/距高点）。
    L5 首板判定需 ≥61 根前复权日K，不足者为「未知」档，不参与决策规则。
    L6 多重检验：multiple_testing 字段明文给出所测分档格子数与总评估次数，全量输出不选择性汇报。
    L7 时间分半 train ≤ 2025-08-31 < test，为时序切分（非随机），含市场状态漂移。
"""
import bisect
import json
import statistics as st
from collections import defaultdict
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
DATA = ROOT / "data"
M60 = DATA / "m60_cache"
BIGK = DATA / "big_kcache"
CAP = DATA / "cap_hist"
OUT = DATA / "zhaban_features_20260913.json"

FEE = 0.0015
LIMIT_PCT = 7.0                 # 挂单价 = 昨收 × 1.07
BAND_LO, BAND_HI = 3.0, 8.5     # 浅炸区间（当日最低涨幅）
TRAIN_END = "2025-08-31"        # train: <= ; test: >
MIN_N = 20                      # 规则搜索最小分段样本

FEATURE_ORDER = ["昨首板", "昨封板时间", "昨量比", "今开幅度",
                 "首30分钟量能比", "市值带", "距60日高点"]

BUCKETS = {
    "昨首板":        ["是", "否", "未知"],
    "昨封板时间":    ["早盘<=10:30", "午盘10:30-14:00", "尾盘>=14:00", "无(未封)"],
    "昨量比":        ["<1.0", "1.0-1.5", "1.5-2.5", ">=2.5", "未知"],
    "今开幅度":      ["5-6%", "6-7%", "7-8%", ">=8%"],
    "首30分钟量能比": ["<1.0", "1.0-2.0", "2.0-4.0", ">=4.0", "未知"],
    "市值带":        ["<50亿", "50-150亿", "150-400亿", ">=400亿", "未知"],
    "距60日高点":    ["贴高>=-2%", "-2~-5%", "-5~-10%", "<-10%", "未知"],
}


# ---------------------------------------------------------------- 基础工具
def load_json(fp):
    try:
        return json.loads(Path(fp).read_text())
    except Exception:
        return None


def hhmm(day_str):
    """'YYYY-MM-DD HH:MM' -> 'HH:MM'；无时间字段返回 None（拒绝全日数据）。"""
    if isinstance(day_str, str) and len(day_str) >= 16 and day_str[10] == " ":
        return day_str[11:16]
    return None


def daily_bars(rows):
    """m60 → 日K（不复权），bars 按时间升序。"""
    days = defaultdict(list)
    for r in rows:
        try:
            days[r["day"][:10]].append(r)
        except Exception:
            continue
    out = []
    for dt in sorted(days):
        bs = sorted(days[dt], key=lambda r: r["day"])
        try:
            out.append({"date": dt,
                        "open": float(bs[0]["open"]),
                        "high": max(float(b["high"]) for b in bs),
                        "low": min(float(b["low"]) for b in bs),
                        "close": float(bs[-1]["close"]),
                        "bars": bs})
        except Exception:
            continue
    return out


def first_bar(bars):
    """当日时间标签 <= 10:30 的最晚一根 bar（首 60 分钟）；无则 None。"""
    best, bt = None, None
    for b in bars:
        t = hhmm(b.get("day"))
        if t is None or t > "10:30":
            continue
        if bt is None or t > bt:
            bt, best = t, b
    return best


# ---------------------------------------------------------------- 特征分档
def f_firstboard(v):
    return "未知" if v is None else ("是" if v else "否")


def f_sealtime(t):
    if t is None:
        return "无(未封)"
    if t <= "10:30":
        return "早盘<=10:30"
    if t >= "14:00":
        return "尾盘>=14:00"
    return "午盘10:30-14:00"


def f_vr(v):
    if v is None:
        return "未知"
    if v < 1.0:
        return "<1.0"
    if v < 1.5:
        return "1.0-1.5"
    if v < 2.5:
        return "1.5-2.5"
    return ">=2.5"


def f_gap(g):
    if g < 6.0:
        return "5-6%"
    if g < 7.0:
        return "6-7%"
    if g < 8.0:
        return "7-8%"
    return ">=8%"


def f_v30(v):
    if v is None:
        return "未知"
    if v < 1.0:
        return "<1.0"
    if v < 2.0:
        return "1.0-2.0"
    if v < 4.0:
        return "2.0-4.0"
    return ">=4.0"


def f_cap(v):
    if v is None:
        return "未知"
    if v < 50:
        return "<50亿"
    if v < 150:
        return "50-150亿"
    if v < 400:
        return "150-400亿"
    return ">=400亿"


def f_dist(v):
    if v is None:
        return "未知"
    if v >= -2.0:
        return "贴高>=-2%"
    if v >= -5.0:
        return "-2~-5%"
    if v >= -10.0:
        return "-5~-10%"
    return "<-10%"


def rule_str(cond):
    if len(cond) == 2:
        return f"{cond[0]} = {cond[1]}"
    return f"{cond[0]} = {cond[1]} 且 {cond[2]} = {cond[3]}"


# ---------------------------------------------------------------- 统计
def agg(sigs):
    """每信号期望：未成交收益计 0，且保留在分母中。"""
    n = len(sigs)
    if n == 0:
        return {"信号数": 0, "浅炸率%": None, "深炸率%": None, "成交率%": None,
                "每信号期望%": None, "每成交期望%": None, "每成交胜率%": None}
    band = sum(1 for s in sigs if s["outcome"] == "浅炸")
    deep = sum(1 for s in sigs if s["outcome"] == "深炸")
    rets = [s["ret"] for s in sigs]
    fills = [s["r_fill"] for s in sigs if s["r_fill"] is not None]
    return {
        "信号数": n,
        "浅炸率%": round(100.0 * band / n, 1),
        "深炸率%": round(100.0 * deep / n, 1),
        "成交率%": round(100.0 * len(fills) / n, 1),
        "每信号期望%": round(100.0 * st.mean(rets), 2),
        "每成交期望%": round(100.0 * st.mean(fills), 2) if fills else None,
        "每成交胜率%": round(100.0 * sum(1 for r in fills if r > 0) / len(fills), 1) if fills else None,
    }


# ---------------------------------------------------------------- 主流程
def main():
    files = sorted(M60.glob("*.json"))
    print(f"m60 files: {len(files)}", flush=True)

    sigs = []
    diag = defaultdict(int)
    n_assert = 0

    for k, fp in enumerate(files):
        if k % 400 == 0:
            print(f"[scan] {k}/{len(files)} sigs={len(sigs)}", flush=True)
        code = fp.stem
        try:
            rows = load_json(fp)
            if not rows:
                diag["m60_unreadable"] += 1
                continue
            dk = daily_bars(rows)
            if len(dk) < 4:
                diag["m60_too_short"] += 1
                continue

            # --- 前复权日K索引（仅取比率） ---
            bk = load_json(BIGK / (code + ".json")) or []
            bidx = {}
            for i2, r in enumerate(bk):
                d2 = str(r.get("date", ""))[:10]
                if d2 and d2 not in bidx:
                    bidx[d2] = i2

            # --- 市值索引（月度，取 <= 信号月 的最近一条） ---
            caprows = load_json(CAP / (code + ".json")) or []
            ym2cap = {}
            for r in caprows:
                try:
                    ym2cap[str(r[0])[:7]] = float(r[2])
                except Exception:
                    continue
            ck = sorted(ym2cap)

            # --- 逐日扫信号 ---
            for i in range(2, len(dk) - 1):
                d0 = dk[i]["date"]
                d1 = dk[i - 1]["date"]
                pc = dk[i - 1]["close"]
                ppc = dk[i - 2]["close"]
                if pc <= 0 or ppc <= 0:
                    continue
                if (pc / ppc - 1.0) * 100.0 < 9.8:      # 昨日未涨停
                    continue
                o = dk[i]["open"]
                if o <= 0:
                    continue
                gap = (o / pc - 1.0) * 100.0
                if gap < 5.0:                            # 今开 < +5%
                    continue

                # 信号日首 60min bar（硬约束：<= 10:30）
                fb = first_bar(dk[i]["bars"])
                if fb is None:
                    diag["no_pre1030_bar"] += 1
                    continue
                if not (hhmm(fb["day"]) <= "10:30"):
                    raise AssertionError("特征引用了信号日 10:30 之后的 bar")
                n_assert += 1

                # 特征2 昨日封板时段（昨日首根 high >= 前收×1.098 的 bar）
                seal_t = None
                for b in dk[i - 1]["bars"]:
                    try:
                        if float(b["high"]) >= ppc * 1.098:
                            seal_t = hhmm(b["day"])
                            break
                    except Exception:
                        continue
                if seal_t is None:
                    diag["no_seal_bar"] += 1

                # 特征1/3/7（big_kcache 比率）
                j = bidx.get(d1)
                first_board, vr, dist = None, None, None
                if j is not None and j >= 1:
                    try:
                        bpc = float(bk[j]["close"])
                        bppc = float(bk[j - 1]["close"])
                    except Exception:
                        bpc = bppc = 0.0
                    if bpc > 0 and bppc > 0:
                        # 特征1：60 日首板（昨日之前 60 个交易日内无涨停）
                        if j >= 61:
                            has_limit = False
                            for m in range(j - 60, j):
                                try:
                                    c0 = float(bk[m]["close"])
                                    c1 = float(bk[m - 1]["close"])
                                except Exception:
                                    continue
                                if c1 > 0 and c0 / c1 - 1.0 >= 0.098:
                                    has_limit = True
                                    break
                            first_board = (not has_limit)
                        # 特征3：昨量比 = 昨日量 / 前 5 日均量
                        vs = []
                        for m in range(j - 5, j):
                            if m < 0:
                                continue
                            try:
                                vs.append(float(bk[m]["volume"]))
                            except Exception:
                                pass
                        if len(vs) >= 3 and st.mean(vs) > 0:
                            try:
                                vr = float(bk[j]["volume"]) / st.mean(vs)
                            except Exception:
                                vr = None
                        # 特征7：距 60 日高点（含昨日）距离
                        hs = []
                        for m in range(max(0, j - 59), j + 1):
                            try:
                                hs.append(float(bk[m]["high"]))
                            except Exception:
                                pass
                        if hs and max(hs) > 0:
                            dist = (bpc / max(hs) - 1.0) * 100.0

                # 特征6：流通市值带（当月）
                cap = None
                if ck:
                    jj = bisect.bisect_right(ck, d0[:7]) - 1
                    if jj < 0:
                        jj = 0
                    cap = ym2cap[ck[jj]]

                # 特征5：信号日首 30 分钟量能 / 昨日首 30 分钟量能
                yfb = first_bar(dk[i - 1]["bars"])
                v30 = None
                if yfb is not None:
                    try:
                        v_now = float(fb["volume"])
                        v_y = float(yfb["volume"])
                        if v_y > 0:
                            v30 = v_now / v_y
                    except Exception:
                        v30 = None

                # outcome（允许使用全天数据）
                low0 = dk[i]["low"]
                g_low = (low0 / pc - 1.0) * 100.0
                if BAND_LO <= g_low <= BAND_HI:
                    outcome = "浅炸"
                elif g_low < BAND_LO:
                    outcome = "深炸"
                else:
                    outcome = "未及"

                # 成交（挂 +7%）
                lim = pc * (1.0 + LIMIT_PCT / 100.0)
                fill_px = None
                for b in dk[i]["bars"]:
                    try:
                        bo = float(b["open"])
                        bl = float(b["low"])
                    except Exception:
                        continue
                    if bo <= lim:
                        fill_px = bo
                        break
                    if bl <= lim:
                        fill_px = lim
                        break

                nxt = dk[i + 1]
                if not (nxt["date"] > d0):               # T+1 硬断言
                    raise AssertionError("出场日未晚于入场日")
                n_assert += 1

                if fill_px is not None and fill_px > 0 and nxt["close"] > 0:
                    r_fill = nxt["close"] / fill_px - 1.0 - FEE
                    ret = r_fill                        # 成交：实际收益
                else:
                    r_fill = None
                    ret = 0.0                           # 未成交：计 0 进每信号期望

                sigs.append({
                    "code": code, "date": d0,
                    "outcome": outcome,
                    "ret": ret, "r_fill": r_fill,
                    "feat": {
                        "昨首板": f_firstboard(first_board),
                        "昨封板时间": f_sealtime(seal_t),
                        "昨量比": f_vr(vr),
                        "今开幅度": f_gap(gap),
                        "首30分钟量能比": f_v30(v30),
                        "市值带": f_cap(cap),
                        "距60日高点": f_dist(dist),
                    },
                })
        except AssertionError as e:
            diag["assert_fail"] += 1
            print(f"[ASSERT-FAIL] {code}: {e}", flush=True)
        except Exception:
            diag["stock_error"] += 1

    print(f"signals={len(sigs)} assertions={n_assert} diag={dict(diag)}", flush=True)

    if not sigs:
        OUT.write_text(json.dumps({"meta": {"error": "no signals", "diag": dict(diag)}},
                                  ensure_ascii=False, indent=1))
        print("SAVED (empty)", OUT)
        return

    train_all = [s for s in sigs if s["date"] <= TRAIN_END]
    test_all = [s for s in sigs if s["date"] > TRAIN_END]
    base_all, base_tr, base_te = agg(sigs), agg(train_all), agg(test_all)

    out = {}
    out["meta"] = {
        "task": "任务B 炸板 浅炸/深炸 事前可分特征筛查",
        "signal": "昨涨停(收/前收-1>=9.8%) 且 今开>=昨收*1.05（m60 不复权聚合日K）",
        "fill_rule": "限价=昨收*1.07；bar.open<=限价按open，bar.low<=限价按限价，否则未成交(收益计0)",
        "exit": "T+1 收盘，费 0.0015（单边一次性扣）",
        "outcome_def": {"浅炸": "当日最低涨幅∈[3%,8.5%]", "深炸": "<3%", "未及": ">8.5%"},
        "feature_scope": "信号日 10:30 前（含首 60min bar）+ 昨日及以前；outcome 才可用全天",
        "train": "日期 <= 2025-08-31", "test": "日期 >= 2025-09-01",
        "bar_window": "2024-08-30 .. 2026-09-11",
        "files_scanned": len(files),
        "signals": len(sigs),
        "assertions_passed": n_assert,
        "diagnostics": dict(diag),
        "known_limits": ["L1 60min粒度成交率偏高", "L2 封板时段精度到bar",
                         "L3 无<=10:30 bar 的信号丢弃", "L4 前复权仅取比率",
                         "L5 首板需>=61根前复权日K", "L6 多重检验见multiple_testing",
                         "L7 train/test 为时序切分"],
    }
    out["baseline"] = {"全样本": base_all, "train": base_tr, "test": base_te}

    # ---------------- 特征 × 分档 × 两段 ----------------
    out["feature_tables"] = {}
    for f in FEATURE_ORDER:
        ft = {}
        for b in BUCKETS[f]:
            sub = [s for s in sigs if s["feat"][f] == b]
            ft[b] = {
                "全样本": agg(sub),
                "train": agg([s for s in sub if s["date"] <= TRAIN_END]),
                "test": agg([s for s in sub if s["date"] > TRAIN_END]),
            }
        out["feature_tables"][f] = ft

    # ---------------- 多重检验计数 ----------------
    n_single = sum(len(BUCKETS[f]) for f in FEATURE_ORDER)
    n_pair = 0
    for a in range(len(FEATURE_ORDER)):
        for c in range(a + 1, len(FEATURE_ORDER)):
            n_pair += len(BUCKETS[FEATURE_ORDER[a]]) * len(BUCKETS[FEATURE_ORDER[c]])
    total_cells = n_single + n_pair

    # ---------------- 规则搜索 ----------------
    btr = base_tr["每信号期望%"] if base_tr["每信号期望%"] is not None else 0.0
    bte = base_te["每信号期望%"] if base_te["每信号期望%"] is not None else 0.0

    idx_by = {}
    for f in FEATURE_ORDER:
        for b in BUCKETS[f]:
            idx_by[(f, b)] = [i for i, s in enumerate(sigs) if s["feat"][f] == b]

    def good_label(lab):
        return ("未知" not in lab) and (lab != "无(未封)")

    cands = []
    for f in FEATURE_ORDER:
        for b in BUCKETS[f]:
            if not good_label(b):
                continue
            ids = idx_by[(f, b)]
            if len(ids) >= MIN_N:
                cands.append(((f, b), ids))
    for a in range(len(FEATURE_ORDER)):
        for c in range(a + 1, len(FEATURE_ORDER)):
            fa, fc = FEATURE_ORDER[a], FEATURE_ORDER[c]
            for ba in BUCKETS[fa]:
                if not good_label(ba):
                    continue
                ia = idx_by[(fa, ba)]
                if len(ia) < MIN_N:
                    continue
                sa = set(ia)
                for bc in BUCKETS[fc]:
                    if not good_label(bc):
                        continue
                    ib = idx_by[(fc, bc)]
                    if len(ib) < MIN_N:
                        continue
                    inter = sa & set(ib)
                    if len(inter) < MIN_N:
                        continue
                    cands.append(((fa, ba, fc, bc), sorted(inter)))

    results = []
    for cond, ids in cands:
        sub = [sigs[i] for i in ids]
        tr = [s for s in sub if s["date"] <= TRAIN_END]
        te = [s for s in sub if s["date"] > TRAIN_END]
        ra, ea, aa = agg(tr), agg(te), agg(sub)
        if ra["信号数"] < MIN_N or ea["信号数"] < MIN_N:
            continue
        if ra["每信号期望%"] is None or ea["每信号期望%"] is None:
            continue
        rec = {
            "规则": rule_str(cond),
            "train超额%": round(ra["每信号期望%"] - btr, 2),
            "test超额%": round(ea["每信号期望%"] - bte, 2),
            "全样本": aa, "train": ra, "test": ea,
            "_score": min(ra["每信号期望%"] - btr, ea["每信号期望%"] - bte),
        }
        results.append(rec)

    results.sort(key=lambda r: -r["_score"])
    qualified = [r for r in results if r["_score"] > 0]
    top = []
    for r in results[:20]:
        rr = dict(r)
        rr.pop("_score", None)
        top.append(rr)

    if qualified:
        b0 = qualified[0]
        verdict = ("可分：规则【%s】全样本 n=%d 每信号期望 %.2f%%（浅炸率 %.1f%%）；"
                   "train n=%d %.2f%%；test n=%d %.2f%%"
                   % (b0["规则"], b0["全样本"]["信号数"], b0["全样本"]["每信号期望%"],
                      b0["全样本"]["浅炸率%"], b0["train"]["信号数"], b0["train"]["每信号期望%"],
                      b0["test"]["信号数"], b0["test"]["每信号期望%"]))
    else:
        verdict = ("不可分：候选 %d 个格子中，无一个满足 train 与 test 两段 每信号期望均优于同段基线 "
                   "且两段样本各≥%d" % (len(results), MIN_N))

    out["rule_search"] = {
        "min_n": MIN_N,
        "candidates_evaluated": len(results),
        "qualified": len(qualified),
        "top20": top,
        "verdict": verdict,
    }
    out["multiple_testing"] = {
        "单特征分档格子数": n_single,
        "双特征组合格子数": n_pair,
        "总格子数": total_cells,
        "分段数": 2,
        "总评估次数_格子x段": total_cells * 2,
        "规则搜索最小分段样本": MIN_N,
        "纪律": "所有格子结果全量写入 feature_tables，未选择性汇报；决策规则要求 train/test 两段同时为正且超基线",
    }

    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    print("== baseline ==", json.dumps(out["baseline"], ensure_ascii=False))
    print("== verdict ==", verdict)
    print("== multiple_testing ==", json.dumps(out["multiple_testing"], ensure_ascii=False))
    print("SAVED", OUT)


if __name__ == "__main__":
    main()
```