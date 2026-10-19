#!/usr/bin/env python3
"""engine/line_t1_recheck.py — 打板类信号线「T+1 开盘卖」口径重算（2026-10-19 一次性研究卡）

背景：涨停池数据测算显示打板的钱在「次日开盘卖」（严格档 +4.00%/胜73%/13月全正），
而 line_health 现行评估口径是 T+5/T+20 持有，可能严重低估打板线的真实边际。
本脚本对已上线打板类信号线，用【其自身注册信号口径】生成信号日，统一重算：
  入场 = 信号日收盘价（打板成交口径；BANLU_B5 按注册口径 trigger6=前收×1.06）
  出场 = T+1开盘 / T+1收盘 / T+2收盘 / T+5收盘 / T+20收盘，扣双边 0.2%
输出每卖点的 均值/胜率/中位数/n + 逐月均值，与 data/line_health.json 的 T+5 roll 口径并列。

RESEAL_CONFIRM_AM 的注册 detector 是「涨停池数据（炸板次数+最后封板时间）」，不在
law_pipeline.REGISTRY（依赖分时/封单数据），日K无法精确复现 → 用涨停池 csv 近似：
炸板次数>=1 且 最后封板时间<=11:30，入场=涨停价，出场=次日开盘（csv 自带，交叉验证
用 universe 前复权价重算）。

只读现有文件，只写 data/line_t1_recheck_20261019.txt。不改任何现有文件。
用法：PYTHONPATH=/opt/data/python-libs:/opt/data/fenjue/engine \
      .venv/bin/python engine/line_t1_recheck.py
"""
import csv, json, statistics as st, sys
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
DATA = ROOT / "data"
OUT = DATA / "line_t1_recheck_20261019.txt"
POOL_CSV = DATA / "limit_up_mainboard_20250908_20260922.csv"
FEE = 0.002  # 双边 0.2%（买0.1%+卖0.1% 合并简化）

sys.path.insert(0, str(ROOT / "engine"))
sys.path.insert(0, "/opt/data/python-libs")

# 待重算的线：(line_id, registry_detector, entry_mode)
# entry_mode: signal_close=信号日收盘(打板口径) / trigger6=前收×1.06(半路板盘中触发代理)
LINES = [
    ("FRONTRUN_FIRSTBOARD_V2", "frontrun_v2", "signal_close"),
    ("BANLU_B5", "banlu_b5_MA60上", "trigger6"),
    ("DEMON_CRADLE_CLUSTER", "妖股摇篮_成簇", "signal_close"),
    ("YAO_LAUNCH_FIRSTBOARD", "妖股启动期首板_v1", "signal_close"),
    ("COMP_TOUCH_NOT_SEAL_LOW", "组合_触板未封_低位", "signal_close"),
]
HORIZONS = [("T+1开盘", "o", 1), ("T+1收盘", "c", 1), ("T+2收盘", "c", 2),
            ("T+5收盘", "c", 5), ("T+20收盘", "c", 20)]


def entry_px(d, i, mode):
    if mode == "signal_close":
        return d["c"][i]
    if mode == "trigger6":
        return d["c"][i - 1] * 1.06
    raise ValueError(mode)


def stats(rs):
    if not rs:
        return {"n": 0}
    return {"n": len(rs), "mean_pp": round(100 * st.mean(rs), 2),
            "win": round(100 * sum(1 for r in rs if r > 0) / len(rs), 1),
            "median_pp": round(100 * st.median(rs), 2)}


def monthly(dates, rs):
    m = {}
    for dt, r in zip(dates, rs):
        m.setdefault(dt[:7], []).append(r)
    return {k: round(100 * st.mean(v), 2) for k, v in sorted(m.items())}


def scan_registry_lines(stocks):
    from law_pipeline import REGISTRY
    out = {}
    for cid, det_name, entry in LINES:
        det = REGISTRY[det_name]
        need = max(h for _, _, h in HORIZONS)
        res = {lbl: ([], []) for lbl, _, _ in HORIZONS}  # lbl -> (dates, rets)
        for code, d in stocks.items():
            n = d["n"]
            if n < 62:
                continue
            c, o = d["c"], d["o"]
            for i in range(61, n - need - 1):
                try:
                    if not det(d, i):
                        continue
                except Exception:
                    continue
                ep = entry_px(d, i, entry)
                if ep <= 0:
                    continue
                for lbl, fld, h in HORIZONS:
                    px = (o if fld == "o" else c)[i + h]
                    if px > 0:
                        res[lbl][0].append(d["date"][i])
                        res[lbl][1].append(px / ep - 1 - FEE)
        out[cid] = {
            "detector": det_name, "entry": entry,
            "sells": {lbl: {**stats(rs), "monthly_mean_pp": monthly(ds, rs)}
                      for lbl, (ds, rs) in res.items()},
        }
    return out


def scan_reseal_pool(stocks):
    """RESEAL_CONFIRM_AM 近似：涨停池 csv 中 炸板>=1 且 最后封板<=11:30 的行。
    入场=涨停价（未复权，csv 口径）；出场用 universe 前复权价重算 T+1开盘等，
    与 csv 自带「次日开盘涨幅%」交叉验证。"""
    # code -> date -> index 映射（universe 前复权价定位）
    idx = {}
    for code, d in stocks.items():
        idx[code] = {dt: i for i, dt in enumerate(d["date"])}
    rows = []
    with POOL_CSV.open(encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            try:
                zb = int(float(r.get("炸板次数") or 0))
            except Exception:
                zb = 0
            last = (r.get("最后封板时间") or "").strip()
            if zb < 1 or not last or last > "11:30:00":
                continue
            rows.append(r)
    res = {lbl: ([], []) for lbl, _, _ in HORIZONS}
    csv_t1o = []  # csv 自带次日开盘涨幅（未扣费），交叉验证
    skipped = 0
    for r in rows:
        code, dt = r["代码"], r["日期"]
        d = stocks.get(code)
        if d is None:
            skipped += 1
            continue
        i = idx[code].get(dt)
        if i is None or i + 20 >= d["n"]:
            skipped += 1
            continue
        # 入场价：用当日收盘价（前复权）。前复权下 信号日收盘≈涨停价，比例收益等价。
        ep = d["c"][i]
        if ep <= 0:
            skipped += 1
            continue
        for lbl, fld, h in HORIZONS:
            px = (d["o"] if fld == "o" else d["c"])[i + h]
            if px > 0:
                res[lbl][0].append(dt)
                res[lbl][1].append(px / ep - 1 - FEE)
        try:
            csv_t1o.append(float(r["次日开盘涨幅(%)"]))
        except Exception:
            pass
    out = {"detector": "涨停池csv近似(炸板>=1+最后封板<=11:30)", "entry": "signal_close(前复权,≈涨停价)",
           "note": f"csv命中{len(rows)}行, 跳过{skipped}(缺行情/尾部不足), "
                   f"csv自带次日开盘涨幅均值={round(st.mean(csv_t1o),2)}%(未扣费,n={len(csv_t1o)})",
           "sells": {lbl: {**stats(rs), "monthly_mean_pp": monthly(ds, rs)}
                     for lbl, (ds, rs) in res.items()}}
    return out


def fmt_sell(lbl, s):
    if s.get("n", 0) == 0:
        return f"    {lbl}: 无样本"
    m = s["monthly_mean_pp"]
    mstr = " ".join(f"{k}:{v:+.2f}" for k, v in m.items())
    neg = sum(1 for v in m.values() if v < 0)
    return (f"    {lbl}: n={s['n']} 均值={s['mean_pp']:+.2f}pp 胜率={s['win']}% "
            f"中位={s['median_pp']:+.2f}pp | 逐月({len(m)}月,负{neg}月): {mstr}")


def main():
    import line_health as lh
    print("[line_t1_recheck] loading universe (lean)...", file=sys.stderr, flush=True)
    stocks = lh.load_universe_lean()
    from law_pipeline import build_xsection
    build_xsection(stocks)
    print(f"[line_t1_recheck] universe {len(stocks)} 票, xsection ready", file=sys.stderr, flush=True)

    results = scan_registry_lines(stocks)
    print("[line_t1_recheck] registry lines done", file=sys.stderr, flush=True)
    results["RESEAL_CONFIRM_AM"] = scan_reseal_pool(stocks)
    print("[line_t1_recheck] reseal pool approx done", file=sys.stderr, flush=True)

    health = json.loads((DATA / "line_health.json").read_text())
    hl = health.get("lines", {})

    L = []
    L.append("=" * 100)
    L.append("打板类信号线「T+1 开盘卖」口径重算报告  (2026-10-19)")
    L.append("口径: 入场=信号日收盘(打板口径; BANLU_B5=trigger6 前收×1.06) → 各卖点, 扣双边0.2%")
    L.append("对比基准: data/line_health.json 现有 roll 口径(滚动250交易日, 相对随机/位置对照的超额pp)")
    L.append("注意: 本报告新口径是【绝对收益pp】, line_health 的 roll_pp 是【相对对照超额pp】——")
    L.append("      两者口径不同, 并列仅用于「卖点结构」判断(T+1钱 vs T+5/T+20钱), 不直接比大小。")
    L.append("=" * 100)
    for cid, _, _ in LINES + [("RESEAL_CONFIRM_AM", None, None)]:
        r = results[cid]
        L.append("")
        L.append(f"■ {cid}  (detector={r['detector']}, entry={r['entry']})")
        if r.get("note"):
            L.append(f"  注: {r['note']}")
        hr = (hl.get(cid) or {}).get("horizons") or {}
        if hr:
            bits = []
            for h, v in sorted(hr.items(), key=lambda kv: int(kv[0])):
                bits.append(f"T+{h} roll_pp={v.get('roll_pp')} roll_win={v.get('roll_win')} "
                            f"roll_n={v.get('roll_n')} full_pp={v.get('full_pp')}")
            L.append("  现有 line_health 口径: " + " | ".join(bits))
        else:
            L.append("  现有 line_health 口径: (无 horizons 记录)")
        L.append("  新口径(绝对收益, 信号日收盘上车):")
        for lbl, _, _ in HORIZONS:
            L.append(fmt_sell(lbl, r["sells"][lbl]))
        # 关键对比句：T+1开盘 vs T+5收盘
        s1, s5 = r["sells"]["T+1开盘"], r["sells"]["T+5收盘"]
        if s1.get("n") and s5.get("n"):
            diff = s1["mean_pp"] - s5["mean_pp"]
            roll5 = (hr.get("5") or {})
            L.append(f"  ⇒ T+1开盘卖({s1['mean_pp']:+.2f}pp/胜{s1['win']}%) vs "
                     f"T+5收盘卖({s5['mean_pp']:+.2f}pp/胜{s5['win']}%): "
                     f"T+1高 {diff:+.2f}pp"
                     + (f"；line_health T+5 roll_pp={roll5.get('roll_pp')}" if roll5 else ""))
    L.append("")
    L.append("=" * 100)
    txt = "\n".join(L) + "\n"
    OUT.write_text(txt)
    print(txt)
    # 机器可读摘要到 stdout 尾部（供上级解析）
    summary = {}
    for cid, r in results.items():
        hr = (hl.get(cid) or {}).get("horizons") or {}
        s1 = r["sells"]["T+1开盘"]
        summary[cid] = {
            "t1_open_mean": s1.get("mean_pp"), "t1_open_win": s1.get("win"),
            "n": s1.get("n", 0),
            "t5_roll_pp": (hr.get("5") or {}).get("roll_pp"),
            "t5_roll_win": (hr.get("5") or {}).get("roll_win"),
        }
    print("@@SUMMARY@@" + json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
