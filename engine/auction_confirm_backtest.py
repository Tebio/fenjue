#!/usr/bin/env python3
"""engine/auction_confirm_backtest.py — 9:32 竞价确认规则历史回测（卡 t_85004326）。

问题：反转链 9:32 竞价确认规则（剔除 T+1 一字跌停开；宽清单 >1/3 高开≥1% 则作废）
从来没有历史回测，只有 20 天前向影子。本脚本用 big_kcache 日K重建三个事件族，
做三组对照：
  A 无确认裸执行  = 全部事件次日开盘买
  B 现确认规则    = 剔除 T+1 开盘 gap≤-9.5%（一字跌停开作废）；WIDE 另加日级作废
                    （当日可执行票中高开≥+1% 占比 >1/3 → 整日作废，对齐 reversal_daily.confirm）
  C 反向组        = 被剔除的票（C1=一字跌停开个股；C2=被整日作废日的事件）实际表现
                  → 回答「剔除规则是在省钱还是在漏钱」
口径：信号日 T 收盘判定，入场 T+1 开盘（=9:25 竞价撮合价=9:32 确认时的开盘价），
出场 T+1+h 收盘，h∈{1,2,3,5,10,20}，净费 0.15%。
统计：事件级 n/胜率/均值/中位/NW-t（lag=h）+ 日历时间日度超额 NW-t（对齐 law_pipeline）。
窗口：全史（2019-2026）+ 近 2 年（signal_date ≥ 2024-10-01）双口径；分年明细主 horizon。

事件族（生产口径复刻，定义逐条对齐 /opt/data/scripts/reversal_daily.py 与 law_pipeline REGISTRY）：
  WIDE   反转族确认名单：T 收收 ≤-3%；T 当日开/昨收 >-9.5%（剔信号日一字开）；
         成交额代理 v*c ≥ 8e7（big_kcache 无 amount 字段，v*c 近似）；历史无 ST 标记
         （台账先例：方向=拉低边际，照实声明）。
  DEEP   深档低位v2 出手票：WIDE 过滤内 ∩ T 收收≤-9.5% ∩ 收≤MA60 ∩ 深度(c/ma60-1)≤-35%；
         簇门：当日「收收≤-9.5% ∩ 收≤MA60 ∩ 深度≤-25%」票数 ≥5（少于此=零星日不出手）。
  LD     跌停接触发：law_pipeline._limitdown（跌停≤-9.5% 剔全天一字锁死）∩ 收≤MA60
         （=LIMITDOWN_LOW_MA60 生产口径）。

内存纪律：宇宙加载独占（单进程，期间不跑其他重任务）。
产出：data/auction_confirm_backtest_20261016.json + 事件清单（供竞价回填）。
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
import law_pipeline as lp  # noqa: E402  (仅复用 nw_t / START 常量；不走它的 load_universe)

ROOT = Path("/opt/data/fenjue")
KC = ROOT / "data" / "big_kcache"
from costs import FLAT_RT  # TAX-01 唯一真源 engine/costs.py（AGENTS #287）
FEE = FLAT_RT
HORIZONS = [1, 2, 3, 5, 10, 20]
RECENT_FROM = "2024-10-01"   # 近 2 年窗口
OUT = ROOT / "data" / "auction_confirm_backtest_20261016.json"


def load_universe_lean():
    """内存纪律：15GB 机+并发 worker 下 lp.load_universe 的 Python list 宇宙会 OOM（实测 exit 137）。
    精简版：numpy 数组 + 只留 c/o/h/l/v/date/ma60。ma60 与 lp.load_universe 逐值一致
    （含今日收盘的 60 日均，i<59 为 NaN）。"""
    stocks = {}
    for fp in glob.glob(str(KC / "*.json")):
        ks = json.loads(open(fp).read())
        if len(ks) < 300:
            continue
        c = np.array([k["close"] for k in ks])
        S = np.concatenate([[0.0], np.cumsum(c)])
        ma60 = np.full(len(c), np.nan)
        ma60[59:] = (S[60:] - S[:-60]) / 60
        stocks[Path(fp).stem] = {
            "code": Path(fp).stem, "c": c,
            "o": np.array([k["open"] for k in ks]),
            "h": np.array([k["high"] for k in ks]),
            "l": np.array([k["low"] for k in ks]),
            "v": np.array([k.get("volume", 0) for k in ks]),
            "ma60": ma60, "date": [k["date"] for k in ks], "n": len(ks),
        }
    return stocks


def _limitdown_np(d, i):
    """跌停次日接（逐条对齐 law_pipeline._limitdown：剔全天一字锁死）。"""
    c, o, h, l = d["c"], d["o"], d["h"], d["l"]
    if c[i - 1] <= 0 or c[i] / c[i - 1] - 1 > -0.095:
        return False
    if o[i] / c[i - 1] - 1 <= -0.09 and (h[i] - l[i]) / c[i - 1] < 0.01:
        return False
    return True


# ---------------------------------------------------------------- 事件构建

def build_events(stocks):
    """返回 dict family -> list[event]。event=(code, i)。

    DEEP 口径锚定既有台账（deep_batches_full_20260927.json 65 批，本脚本重建命中 64/65，
    边界差 1 天各一=深度四舍五入/宇宙差）：跌停(收收≤-9.5%) ∩ 收≤MA60 ∩ 深度≤-25% 计簇，
    簇≥5 触发，出手票=深度≤-35% 按深度升序取前 5（production confirm() 的 [:5] 截断）。
    **不套 WIDE 的成交额过滤**——台账口径无此过滤；实测若套 v*c≥8e7，2020-02-03 型
    一字封死恐慌日深档件量额坍缩，簇被误灭（27 只深档件只剩 1 只过额门）。
    """
    wide, ld = [], []
    deep25_by_date = defaultdict(int)
    deep_cand = []   # (code, i, depth)
    for code, d in stocks.items():
        c, o, v, ma60, date, n = d["c"], d["o"], d["v"], d["ma60"], d["date"], d["n"]
        for i in range(lp.START, n - 2):          # 至少要 i+1 入场 + 部分 horizon
            pc = c[i - 1]
            if pc <= 0:
                continue
            cc = c[i] / pc - 1
            # ---- WIDE（反转族确认名单，生产 scan 口径） ----
            if cc <= -0.03 and o[i] / pc - 1 > -0.095 and v[i] * c[i] >= 8e7:
                wide.append((code, i))
            # ---- DEEP 深档件（台账口径：无额门/无一字开剔除） ----
            if (cc <= -0.095 and np.isfinite(ma60[i]) and ma60[i] > 0
                    and c[i] <= ma60[i]):
                depth = c[i] / ma60[i] - 1
                if depth <= -0.25:
                    deep25_by_date[date[i]] += 1
                    deep_cand.append((code, i, depth))
            # ---- LD 跌停接（生产探测器原定义，不套 WIDE 流动性过滤） ----
            if np.isfinite(ma60[i]) and c[i] <= ma60[i] and _limitdown_np(d, i):
                ld.append((code, i))
    # 簇门：≥5 深档件（≤-25%）的日子才出手，出手票=深度≤-35% 最深前 5
    picks_by_day = defaultdict(list)
    for code, i, depth in deep_cand:
        if depth <= -0.35 and deep25_by_date[stocks[code]["date"][i]] >= 5:
            picks_by_day[stocks[code]["date"][i]].append((code, i))
    deep = []
    for day, lst in picks_by_day.items():
        lst.sort(key=lambda x: stocks[x[0]]["c"][x[1]] / stocks[x[0]]["ma60"][x[1]] - 1)
        deep.extend(lst[:5])
    return {"WIDE": wide, "DEEP": deep, "LD": ld}


# ---------------------------------------------------------------- 收益与分组

def enrich(events, stocks):
    """给每个事件补 T+1 gap 与全 horizon 净收益（尾部不足的 horizon 记 None）。"""
    out = []
    for code, i in events:
        d = stocks[code]
        c, o, n = d["c"], d["o"], d["n"]
        if i + 1 >= n or o[i + 1] <= 0 or c[i] <= 0:
            continue
        gap = o[i + 1] / c[i] - 1
        rets = {}
        for h in HORIZONS:
            j = i + 1 + h
            rets[h] = (c[j] / o[i + 1] - 1 - FEE) if j < n else None
        out.append({"code": code, "i": i, "date": d["date"][i], "entry_date": d["date"][i + 1],
                    "gap": gap, "rets": rets})
    return out


def split_groups(events, day_void=True):
    """A=全部裸执行；B_ps=仅个股剔除（一字跌停开作废）；B=生产确认规则
    （B_ps + 日级作废，仅 WIDE 有日级作废——confirm() 原话「归档，不影响深档低位组」）；
    C1=被剔除的一字跌停开个股；C2=被整日作废日的事件（诊断：日级作废在省钱还是漏钱）。
    日级作废口径对齐 confirm()：高开计数在剔除一字后的 ok 集上，>1/3 则整日作废。"""
    by_day = defaultdict(list)
    for e in events:
        by_day[e["entry_date"]].append(e)
    voided_days = set()
    for day, es in by_day.items():
        kept = [e for e in es if e["gap"] > -0.095]
        if kept and sum(1 for e in kept if e["gap"] >= 0.01) / len(kept) > 1 / 3:
            voided_days.add(day)
    A = events
    C1 = [e for e in events if e["gap"] <= -0.095]
    B_ps = [e for e in events if e["gap"] > -0.095]
    if day_void:
        B = [e for e in B_ps if e["entry_date"] not in voided_days]
        C2 = [e for e in B_ps if e["entry_date"] in voided_days]
    else:
        B, C2 = B_ps, []
    return {"A": A, "B": B, "B_ps": B_ps, "C1": C1, "C2": C2,
            "voided_days": sorted(voided_days)}


# ---------------------------------------------------------------- 统计

def stats(rs, h):
    rs = [r for r in rs if r is not None]
    if len(rs) < 10:
        return {"n": len(rs)}
    n = len(rs)
    m = st.mean(rs)
    return {"n": n, "win%": round(100 * sum(r > 0 for r in rs) / n, 1),
            "mean%": round(100 * m, 3), "med%": round(100 * st.median(rs), 3),
            "odds": round(st.mean([r for r in rs if r > 0]) / abs(st.mean([r for r in rs if r < 0])), 2)
            if any(r > 0 for r in rs) and any(r < 0 for r in rs) else None,
            "t_NW": lp.nw_t(rs, h)}


def cal_t(events, uni_mean, h):
    """日历时间：事件按入场日聚日度组合 - 当日全宇宙均值（同窗口），NW t。"""
    by_date = defaultdict(list)
    for e in events:
        r = e["rets"][h]
        if r is not None:
            by_date[e["entry_date"]].append(r)
    series = [st.mean(v) - uni_mean[h][dt] for dt, v in sorted(by_date.items()) if dt in uni_mean[h]]
    if len(series) < 30:
        return None
    return {"days": len(series), "excess_pp/day": round(100 * st.mean(series), 3),
            "t_NW": lp.nw_t(series, h)}


def build_uni_mean(stocks, all_dates):
    """全宇宙日度均值（next_open 口径，对齐 law_pipeline.calendar_time）：uni_mean[h][entry_date]=mean。
    内存纪律：用 (sum,count) 向量累加，不存逐笔收益（37M float 的 list 曾在 15GB 机上 OOM）。
    基线不剔一字跌停开（对齐 calendar_time 惯例，与历史日历口径数字可比）。"""
    nd = len(all_dates)
    sums = {h: np.zeros(nd) for h in HORIZONS}
    cnts = {h: np.zeros(nd) for h in HORIZONS}
    darr = np.asarray(all_dates)
    for code, d in stocks.items():
        c = np.asarray(d["c"]); o = np.asarray(d["o"]); n = d["n"]
        if n < lp.START + max(HORIZONS) + 2:
            continue
        dates = np.asarray(d["date"])
        prev_c = c[:-1]
        for h in HORIZONS:
            i0, i1 = lp.START, n - h - 1          # i ∈ [START, n-h-2]
            ent = o[i0 + 1:i1 + 1]
            ex = c[i0 + 1 + h:i1 + 1 + h]
            pc = prev_c[i0:i1]
            ok = (ent > 0) & (pc > 0)
            if not ok.any():
                continue
            idx = np.searchsorted(darr, dates[i0 + 1:i1 + 1][ok])
            np.add.at(sums[h], idx, ex[ok] / ent[ok] - 1 - FEE)
            np.add.at(cnts[h], idx, 1)
    return {h: {dt: float(sums[h][j] / cnts[h][j]) for j, dt in enumerate(all_dates) if cnts[h][j] > 0}
            for h in HORIZONS}


def eval_group(events, uni_mean, label):
    res = {}
    for h in HORIZONS:
        s = stats([e["rets"][h] for e in events], h)
        s["cal"] = cal_t(events, uni_mean, h)
        res[f"T+{h}"] = s
    return {"label": label, "n_events": len(events), "horizons": res}


def per_year(events, h=5):
    by = defaultdict(list)
    for e in events:
        r = e["rets"][h]
        if r is not None:
            by[e["date"][:4]].append(r)
    return {y: {"n": len(v), "win%": round(100 * sum(r > 0 for r in v) / len(v), 1),
                "mean%": round(100 * st.mean(v), 2)} for y, v in sorted(by.items()) if len(v) >= 5}


# ---------------------------------------------------------------- ④ 竞价强度连续版

def gap_bins(events, h):
    edges = [(-99, -0.095), (-0.095, -0.05), (-0.05, -0.03), (-0.03, -0.01),
             (-0.01, 0.0), (0.0, 0.01), (0.01, 0.02), (0.02, 0.04), (0.04, 99)]
    out = []
    for lo, hi in edges:
        rs = [e["rets"][h] for e in events if lo < e["gap"] <= hi and e["rets"][h] is not None]
        if len(rs) >= 10:
            out.append({"bin": f"({lo},{hi}]", "n": len(rs),
                        "win%": round(100 * sum(r > 0 for r in rs) / len(rs), 1),
                        "mean%": round(100 * st.mean(rs), 3)})
    return out


def highopen_frac_bins(events):
    """日级：按当日（剔一字后）高开≥1% 占比分档，看日级作废阈值的连续信息。"""
    by_day = defaultdict(list)
    for e in events:
        by_day[e["entry_date"]].append(e)
    rows = []
    for day, es in by_day.items():
        kept = [e for e in es if e["gap"] > -0.095]
        if len(kept) < 3:
            continue
        frac = sum(1 for e in kept if e["gap"] >= 0.01) / len(kept)
        for e in kept:
            if e["rets"][5] is not None:
                rows.append((frac, e["rets"][5]))
    out = []
    for lo, hi in [(0, 0.0001), (0.0001, 1 / 6), (1 / 6, 1 / 3), (1 / 3, 0.5), (0.5, 1.01)]:
        rs = [r for f, r in rows if lo < f <= hi]
        if len(rs) >= 10:
            out.append({"frac_bin": f"({lo:.2f},{hi:.2f}]", "n": len(rs),
                        "win%": round(100 * sum(r > 0 for r in rs) / len(rs), 1),
                        "mean_T5%": round(100 * st.mean(rs), 3)})
    return out


# ---------------------------------------------------------------- main

def main():
    print("加载宇宙（精简 numpy 版，独占内存）...", flush=True)
    stocks = load_universe_lean()
    print(f"宇宙 {len(stocks)} 票", flush=True)

    events_raw = build_events(stocks)
    # 全局交易日轴（活跃参照股 000001 尾部锚定纪律：用 000001 的日期轴，不 union 全宇宙）
    all_dates = stocks["000001"]["date"] if "000001" in stocks else sorted(
        {dt for d in stocks.values() for dt in d["date"]})
    uni_mean = build_uni_mean(stocks, all_dates)
    print("宇宙均值表建成", flush=True)

    result = {"_meta": {"generated_at": "2026-10-16", "fee": FEE, "horizons": HORIZONS,
                        "entry": "next_open(T+1 开盘=竞价撮合价)", "exit": "T+1+h 收盘",
                        "universe": "big_kcache 全主板(含退市)", "recent_from": RECENT_FROM,
                        "note": "9:32 竞价确认规则历史回测（卡 t_85004326）"},
              "families": {}}

    event_dump = {}
    for fam, ev in events_raw.items():
        ev_full = enrich(ev, stocks)
        ev_recent = [e for e in ev_full if e["date"] >= RECENT_FROM]
        day_void = (fam == "WIDE")   # 日级作废是宽清单专属规则（confirm() 明示不影响深档组）
        groups_full = split_groups(ev_full, day_void)
        groups_rec = split_groups(ev_recent, day_void)
        fam_res = {
            "n_events_full": len(ev_full), "n_events_recent": len(ev_recent),
            "voided_days_full": len(groups_full["voided_days"]),
            "voided_days_recent": len(groups_rec["voided_days"]),
            "full": {g: eval_group(groups_full[g], uni_mean, g)
                     for g in ("A", "B", "B_ps", "C1", "C2") if groups_full[g] or g in ("A", "B", "B_ps")},
            "recent_2y": {g: eval_group(groups_rec[g], uni_mean, g)
                          for g in ("A", "B", "B_ps", "C1", "C2") if groups_rec[g] or g in ("A", "B", "B_ps")},
            "per_year_T5": {g: per_year(groups_full[g], 5) for g in ("A", "B_ps", "C1")},
            "gap_bins_full": {f"T+{h}": gap_bins(ev_full, h) for h in (1, 5)},
            "gap_bins_recent": {f"T+{h}": gap_bins(ev_recent, h) for h in (1, 5)},
        }
        if fam == "WIDE":
            fam_res["highopen_frac_bins_T5_full"] = highopen_frac_bins(ev_full)
            fam_res["highopen_frac_bins_T5_recent"] = highopen_frac_bins(ev_recent)
        result["families"][fam] = fam_res
        event_dump[fam] = [{"code": e["code"], "date": e["date"], "entry_date": e["entry_date"],
                            "gap": round(e["gap"], 4)} for e in ev_full]
        print(f"[{fam}] full n={len(ev_full)} recent n={len(ev_recent)} "
              f"voided_days={len(groups_full['voided_days'])}/{len(groups_rec['voided_days'])}", flush=True)

    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    (ROOT / "data" / "auction_confirm_events_20261016.json").write_text(
        json.dumps(event_dump, ensure_ascii=False), encoding="utf-8")
    print(f"-> {OUT}", flush=True)

    # 控制台摘要：三族 × A/B/C1 的 T+1/T+5
    for fam in result["families"]:
        fr = result["families"][fam]
        print(f"\n=== {fam} ===")
        for win in ("full", "recent_2y"):
            print(f" [{win}]")
            for g in ("A", "B_ps", "B", "C1", "C2"):
                if g not in fr[win]:
                    continue
                gres = fr[win][g]["horizons"]
                r1, r5 = gres["T+1"], gres["T+5"]
                cal5 = r5.get("cal") or {}
                print(f"  {g:4s} n={gres['T+1'].get('n', 0):6d} "
                      f"T+1 {r1.get('mean%', '-')}%/{r1.get('win%', '-')}% t={r1.get('t_NW')} | "
                      f"T+5 {r5.get('mean%', '-')}%/{r5.get('win%', '-')}% t={r5.get('t_NW')} "
                      f"cal_t={cal5.get('t_NW')} xs={cal5.get('excess_pp/day')}")


if __name__ == "__main__":
    main()
