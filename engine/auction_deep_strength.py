#!/usr/bin/env python3
"""engine/auction_deep_strength.py — DEEP 竞价量维度全量重测（卡 t_2bcb8552，销 #282④ 欠账）。

问题：#282④ 在 DEEP 竞价字段回填子集（26/65 事件日，n=41 命中）上登记了假设级结论——
竞价量比 vr 高低分组、竞价未匹配量正负分组对 T+1/T+5 的差异。回填补齐到全量后重测同口径。

口径（逐条复刻 #282 产物 data/auction_deep_strength_20261016.json 的生成方式；
已对 26 日版 41 条事件逐值回归：ret1/ret5/vr 全等，分组 n/均值/胜率全等——见 --verify-old）：
  signal  = 事件 date 字段（T，出票日，收盘判定）
  entry   = 事件 entry_date 字段（T+1，9:25 竞价撮合价开盘 = 9:32 确认看到的价）
  exit    = entry 日 + h 个交易日收盘，h∈{1,5}，净费 FLAT_RT（0.15%）
  ret     = c[entry+h] / o[entry] - 1 - FEE
  vr      = 竞价量 / mean(volume[T-5 .. T-1])   ← 分母为信号日 T 之前 5 个交易日（#282 原口径）
  vr_alt  = 竞价量 / mean(volume[T-4 .. T])     ← 备选口径（含信号日），敏感性对照
  unmatched = 竞价未匹配量原始值（正 = 买方未匹配量，买盘堆积）
  分组    = vr 以样本中位数为界（<=med / >med）；unmatched <0 / >=0
缓存：data/research/auction_deep/<entry_date>.json（问财 PIT 缓存，历史日不可变不重拉）。
产物：data/auction_deep_strength_<BJT日期>.json
用法：.venv/bin/python engine/auction_deep_strength.py [--tag YYYYMMDD] [--verify-old]
"""
import argparse
import json
import math
import statistics as st
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
CACHE = ROOT / "data" / "research" / "auction_deep"
EVENTS = ROOT / "data" / "auction_confirm_events_20261016.json"
KC = ROOT / "data" / "big_kcache"
OLD = ROOT / "data" / "auction_deep_strength_20261016.json"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from costs import FLAT_RT  # noqa: E402  TAX-01 唯一真源 engine/costs.py

FEE = FLAT_RT
BJT = timezone(timedelta(hours=8))


def kcache(code: str):
    fp = KC / f"{code}.json"
    if not fp.exists():
        return None
    try:
        return json.loads(fp.read_text())
    except Exception:
        return None


def build_rows():
    """返回 (rows, days_used, days_total, n_found_raw)。"""
    deep = json.loads(EVENTS.read_text())["DEEP"]
    by_day = {}
    for e in deep:
        by_day.setdefault(e["entry_date"], []).append(e)

    rows, days_used, n_found_raw = [], 0, 0
    for day in sorted(by_day):
        fp = CACHE / f"{day}.json"
        if not fp.exists():
            continue
        days_used += 1
        cache = {it["code"]: it for it in json.loads(fp.read_text()).get("items", [])}
        for e in by_day[day]:
            it = cache.get(e["code"])
            if not it or not it.get("found"):
                continue
            n_found_raw += 1
            ks = kcache(e["code"])
            if not ks:
                continue
            dts = [k["date"] for k in ks]
            if e["date"] not in dts or day not in dts:
                continue
            j = dts.index(e["date"])          # 信号日 T
            i = dts.index(day)                # 入场日 T+1
            if j < 5 or i + 5 >= len(ks):
                continue
            o = ks[i]["open"]
            if o <= 0:
                continue
            av = it.get("auction_volume")
            den5 = sum(k["volume"] for k in ks[j - 5:j]) / 5     # #282 原口径
            den5b = sum(k["volume"] for k in ks[j - 4:j + 1]) / 5  # 备选（含信号日）
            rows.append({
                "code": e["code"], "entry": day, "signal": e["date"], "gap": e.get("gap"),
                "vr": (av / den5) if (isinstance(av, (int, float)) and den5 > 0) else None,
                "vr_alt": (av / den5b) if (isinstance(av, (int, float)) and den5b > 0) else None,
                "unmatched": it.get("unmatched_volume"),
                "ret1": ks[i + 1]["close"] / o - 1 - FEE,
                "ret5": ks[i + 5]["close"] / o - 1 - FEE,
                "rating": it.get("auction_rating"), "abn": it.get("abnormal_type")})
    return rows, days_used, len(by_day), n_found_raw


def nw_t(rs, lag):
    """Newey-West HAC t（重叠窗口修正；与 law_pipeline.nw_t 同实现，避免 import 重依赖）。"""
    n = len(rs)
    if n < lag + 30:
        return None
    m = st.mean(rs)
    g0 = sum((r - m) ** 2 for r in rs) / n
    lrv = g0
    for k in range(1, lag + 1):
        gk = sum((rs[t] - m) * (rs[t - k] - m) for t in range(k, n)) / n
        lrv += 2 * (1 - k / (lag + 1)) * gk
    return round(m / math.sqrt(lrv / n), 2) if lrv > 0 else None


def agg(sub):
    """基础聚合 + 扎堆鲁棒性诊断（DEEP 事件按簇日扎堆=样本非独立，必须并列看）：
    n_days=不同入场日数、day_eq_T+5%=按日等权（1票/日的极端去扎堆口径）、
    t_NW=T+5 事件级 HAC t（lag=5）。"""
    if not sub:
        return None
    r1 = [r["ret1"] for r in sub]
    r5 = [r["ret5"] for r in sub]
    by_day = {}
    for r in sub:
        by_day.setdefault(r["entry"], []).append(r["ret5"])
    day_means = [st.mean(v) for v in by_day.values()]
    return {"n": len(sub), "n_days": len(by_day),
            "T+1_mean%": round(100 * st.mean(r1), 2),
            "T+1_win%": round(100 * sum(1 for x in r1 if x > 0) / len(r1), 1),
            "T+5_mean%": round(100 * st.mean(r5), 2),
            "T+5_win%": round(100 * sum(1 for x in r5 if x > 0) / len(r5), 1),
            "day_eq_T+5%": round(100 * st.mean(day_means), 2),
            "day_eq_T+5_win%": round(100 * sum(1 for x in day_means if x > 0) / len(day_means), 1),
            "t_NW_T+5": nw_t(r5, 5)}


def groups_of(rows, vkey="vr"):
    vrs = sorted(r[vkey] for r in rows if r.get(vkey) is not None)
    med = st.median(vrs) if vrs else None
    g = {"all": agg(rows),
         "vr_low(<=med)": agg([r for r in rows if r.get(vkey) is not None and med is not None and r[vkey] <= med]),
         "vr_high(>med)": agg([r for r in rows if r.get(vkey) is not None and med is not None and r[vkey] > med]),
         "unmatched_neg": agg([r for r in rows if isinstance(r["unmatched"], (int, float)) and r["unmatched"] < 0]),
         "unmatched_nonneg": agg([r for r in rows if isinstance(r["unmatched"], (int, float)) and r["unmatched"] >= 0])}
    return g, med


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default=datetime.now(BJT).strftime("%Y%m%d"))
    ap.add_argument("--verify-old", action="store_true")
    args = ap.parse_args()

    rows, days_used, days_total, n_raw = build_rows()
    g, med = groups_of(rows)
    g_alt, med_alt = groups_of(rows, "vr_alt")

    if args.verify_old:
        old = json.loads(OLD.read_text())
        om = {(e["code"], e["entry"]): e for e in old["events"]}
        rm = {(r["code"], r["entry"]): r for r in rows}
        sub = {k: rm[k] for k in om if k in rm}
        bad = 0
        for k, o in om.items():
            r = sub.get(k)
            if not r:
                print("MISSING", k)
                bad += 1
                continue
            if abs(o["ret5"] - r["ret5"]) > 1e-9 or abs(o["ret1"] - r["ret1"]) > 1e-9:
                print("RET MISMATCH", k, o["ret1"], r["ret1"], o["ret5"], r["ret5"])
                bad += 1
            if (o["vr"] is None) != (r["vr"] is None) or (o["vr"] is not None and abs(o["vr"] - r["vr"]) > 1e-9):
                print("VR MISMATCH", k, o["vr"], r["vr"])
                bad += 1
        print(f"verify-old: {len(om)} old rows, {len(sub)} matched, mismatches={bad}")
        og, omed = groups_of(list(sub.values()))
        print("old-file groups:", json.dumps(old["groups"], ensure_ascii=False))
        print("recomputed   :", json.dumps(og, ensure_ascii=False), "med", omed, "vs", old["vr_median"])

    out = {
        "_meta": {"generated_at": datetime.now(BJT).isoformat(timespec="seconds"),
                  "card": "t_2bcb8552",
                  "scope": f"DEEP 深档低位v2 事件 T+1 日问财竞价字段回填（{days_used}/{days_total} 事件日）",
                  "note": "#282④ 假设级结论的全量重测；entry=T+1 开盘, exit=T+1+h 收盘, 净费 0.15%",
                  "vr_def": "竞价量 / mean(volume of 5 trading days before signal day T)（#282 原口径）",
                  "vr_alt_def": "竞价量 / mean(volume T-4..T)（含信号日，敏感性对照）",
                  "days_used": days_used, "days_missing": days_total - days_used},
        "n_event_days_cached": days_used, "n_event_days_total": days_total,
        "n_found_raw": n_raw, "n_events": len(rows),
        "vr_median": round(med, 4) if med is not None else None,
        "groups": g, "vr_median_alt": round(med_alt, 4) if med_alt is not None else None,
        "groups_vr_alt": g_alt, "events": rows}

    outpath = ROOT / "data" / f"auction_deep_strength_{args.tag}.json"
    outpath.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"事件日 {days_used}/{days_total}（缺 {days_total - days_used}），可用事件 {len(rows)}（原始命中 {n_raw}）")
    print(json.dumps(g, ensure_ascii=False, indent=1))
    print("vr_alt:", json.dumps(g_alt, ensure_ascii=False))
    print(f"-> {outpath}")


if __name__ == "__main__":
    main()
