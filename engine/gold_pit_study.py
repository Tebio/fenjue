#!/usr/bin/env python3
"""金股 PIT 路径检验（2026-10-19 用户质问「9月金股买完就跌」「金股是胜率最大最赚钱的」后立项）。

修了两处口径错误（旧 gold_stock_backtest.py / gold_rank.py 都有）：
① **月份语义**：缓存文件名的月份是**公告月**，不是组合月（问财 query 是 `公告日期等于YYYY年M月`）。
   一次「9月」查询里 176/263 条其实是 10 月组合（9 月底发布）。本脚本一律按 `组合时间` 归月。
② **前视偏差**：只用 `公告日期 <= 入场日` 的记录，晚发布的组合不许提前知道。

入场两口径并列：
  prod = 组合月第 6 个交易日开盘（生产口径，与 gold_monthly.entry_day 一致）
  old  = 组合月首个交易日次日开盘（旧回测口径）

输出：T+1/2/3/5/10/15/20 命中率与均值、MAE（买入后最深浮亏）、最深点到 T+20 的修复率、
以及**同期全市场主板等权**基准（同窗口、同入场日、同持有期）。

用法：.venv/bin/python engine/gold_pit_study.py [组合月 如 202609]
"""
import json
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, "/opt/data/fenjue/engine")
sys.path.insert(0, "/opt/data/python-libs")
import law_pipeline as lp
import trade_calendar as tc

ROOT = Path("/opt/data/fenjue")
RAW = ROOT / "data/gold_raw"
FEE = 0.0015
HORIZONS = (1, 2, 3, 5, 10, 15, 20)

idx = json.loads((ROOT / "data/index_sh000001.json").read_text())
idays = [r["date"] for r in idx]
iclose = {r["date"]: float(r["close"]) for r in idx}


def load_cohorts():
    """组合时间 -> {code: set(公告日期)}；只留沪深主板。"""
    rows = []
    for f in sorted(RAW.glob("20[0-9][0-9]-[0-9][0-9].json")):
        rows += json.loads(f.read_text())
    seen, out = set(), {}
    for r in rows:
        code = str(r.get("股票代码", "")).split(".")[0].zfill(6)
        if code[:2] not in ("60", "00"):
            continue
        ct = str(r.get("组合时间") or "")[:6]
        ann = str(r.get("公告日期") or "")
        if len(ct) != 6:
            continue
        k = (code, r.get("研究机构"), ann, ct)
        if k in seen:
            continue
        seen.add(k)
        out.setdefault(f"{ct[:4]}-{ct[4:]}", {}).setdefault(code, set()).add(ann)
    return out


def month_days(mo):
    y = int(mo[:4])
    days = tc.trading_days(y) or []
    return [d for d in days if d.startswith(mo)]


def entry_days(mo):
    md = month_days(mo)
    if len(md) < 7:
        return None, None
    prod = md[5]                                  # 月第 6 交易日
    i = idays.index(md[0]) if md[0] in idays else None
    old = idays[i + 1] if i is not None and i + 1 < len(idays) else None
    return prod, old


def path(d, entry_day, code_ann, entry_mode="prod"):
    if entry_day not in d["date"]:
        return None
    j = d["date"].index(entry_day)
    if j >= d["n"] or d["o"][j] <= 0:
        return None
    e = d["o"][j]
    out = {"code": d["code"], "entry_day": entry_day, "entry": e, "ann_max": max(code_ann)}
    for h in HORIZONS:
        out[f"r{h}"] = (d["c"][j + h] / e - 1 - FEE) if j + h < d["n"] else None
    lows = [d["l"][j + k] / e - 1 for k in range(0, min(21, d["n"] - j))]
    out["mae"] = min(lows) if lows else None
    out["mae_day"] = d["date"][j + lows.index(min(lows))] if lows else None
    highs = [d["h"][j + k] / e - 1 for k in range(0, min(21, d["n"] - j))]
    out["mfe"] = max(highs) if highs else None
    return out


def mkt_baseline(entry_day, h, U):
    """同期全市场主板等权：同入场日开盘 → 第 h 日收盘。"""
    xs = []
    for d in U.values():
        if entry_day not in d["date"]:
            continue
        j = d["date"].index(entry_day)
        if j == 0 or d["o"][j] <= 0 or j + h >= d["n"]:
            continue
        xs.append(d["c"][j + h] / d["o"][j] - 1 - FEE)
    return (st.mean(xs), sum(1 for x in xs if x > 0) / len(xs), len(xs)) if xs else (None, None, 0)


def report(label, rows, U, entry_day):
    rows = [r for r in rows if r]
    if not rows:
        print(f"{label}: 无样本")
        return {}
    print(f"\n━━ {label}  n={len(rows)}  入场 {entry_day} ━━")
    res = {}
    for h in HORIZONS:
        xs = [r[f"r{h}"] for r in rows if r[f"r{h}"] is not None]
        if len(xs) < 5:
            continue
        win = sum(1 for x in xs if x > 0) / len(xs)
        mk, mkw, mkn = mkt_baseline(entry_day, h, U)
        ex = f" | 全市场等权 {mk*100:+.2f}%/胜{mkw*100:.0f}%(n={mkn}) → 超额 {(st.mean(xs)-mk)*100:+.2f}pp" if mk is not None else ""
        print(f"  T+{h:<2} 胜率 {win*100:5.1f}%  均值 {st.mean(xs)*100:+6.2f}%  中位 {st.median(xs)*100:+6.2f}%{ex}")
        res[f"T{h}"] = (win, st.mean(xs), len(xs))
    maes = [r["mae"] for r in rows if r["mae"] is not None]
    mfes = [r["mfe"] for r in rows if r["mfe"] is not None]
    r20 = [r["r20"] for r in rows if r["r20"] is not None]
    if maes:
        print(f"  买入后最深浮亏 MAE: 中位 {st.median(maes)*100:+.2f}%  均值 {st.mean(maes)*100:+.2f}%  最深 {min(maes)*100:+.2f}%")
    if mfes:
        print(f"  买入后最高浮盈 MFE: 中位 {st.median(mfes)*100:+.2f}%  均值 {st.mean(mfes)*100:+.2f}%")
    if r20 and maes:
        rec = sum(1 for r in rows if r["r20"] is not None and r["mae"] is not None and r["r20"] > 0)
        dip = sum(1 for r in rows if (r["mae"] or 0) < -0.03)
        print(f"  买完先跌(MAE<-3%) 的占 {dip/len(maes)*100:.0f}%，其中 T+20 转正 {rec/len(r20)*100:.0f}%")
    return res


def main():
    U = lp.load_universe()
    cohorts = load_cohorts()
    want = sys.argv[1] if len(sys.argv) > 1 else None
    for mo in sorted(cohorts):
        if want and mo.replace("-", "") != want:
            continue
        prod, old = entry_days(mo)
        if not prod:
            print(f"\n{mo}: 交易日不足，跳过")
            continue
        codes = cohorts[mo]
        rows = []
        for code, anns in codes.items():
            d = U.get(code)
            if not d:
                continue
            # PIT：只用入场日前已公告的
            if min(anns) > prod.replace("-", ""):
                continue
            r = path(d, prod, anns)
            if r:
                r["anns"] = sorted(anns)
                rows.append(r)
        uniq = {c: a for c, a in codes.items()}
        print(f"\n════ 组合 {mo}：主板名单 {len(uniq)} 只，PIT 可用 {len(rows)} 只（入场 {prod}）════")
        report(f"{mo} 生产口径(月第6交易日开盘入)", rows, U, prod)
        # 近月名单的热度分布
        cnt = sorted(((len(a), c) for c, a in uniq.items()), reverse=True)
        solo = [c for n, c in cnt if n == 1]
        print(f"  独家(仅1家推荐) {len(solo)} 只 / 抱团(≥3家) {sum(1 for n,_ in cnt if n>=3)} 只")


if __name__ == "__main__":
    main()
