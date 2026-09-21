"""T1-MEGA 恐慌背景假设验证（2026-09-22 夜班）。

背景（#138）：8/31 巨簇批 -8.43%（历史 2% 分位）vs 最肥批次全带恐慌背景（2025-04-08 +12.9%、
2020-02-04 +10.7%）。假设：妖股期巨簇日的批次质量由「恐慌背景」决定——上涨中继型巨簇是差批次来源。
若是真的 → T1-MEGA 出票时应按恐慌背景调仓（或拒接上涨中继型）。

方法：全 8 年妖股期簇≥20 日（生产口径探测器=组合_缺口低开_低位阳线_避周一），
批次=次日开盘等权接前 10（生产排序：梯队→量比），T+3 收盘出（生产规则）。
恐慌背景四种切法（全部用信号日及以前数据，无前视）：
  bg1 信号日指数涨跌（<0=恐慌背景）
  bg2 信号日前 5 日指数累计（<-3%=恐慌背景）
  bg3 信号日全市场跌停数（≥30=恐慌背景，=X2 ldc 门）
  bg4 信号日前 5 日内有恐慌期日
输出：每切法两组的批次均值分布（P10/中位/P90/均）+ 8/31 落点。
"""
import collections
import json
import statistics as st
import sys
from datetime import date

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

ROOT = "/opt/data/fenjue"
FEE = 0.0015

stocks = lp.load_universe()
lp.build_xsection(stocks)
regime = lp.load_regime()
det = lp.REGISTRY["组合_缺口低开_低位阳线_避周一"]
print(f"universe {len(stocks)}", flush=True)

idx = json.loads(open(f"{ROOT}/data/index_sh000001.json").read())
ical = [k["date"] for k in idx]
iclose = {k["date"]: k["close"] for k in idx}
ipos = {d: i for i, d in enumerate(ical)}


def idx_ret(d0, d1):
    return iclose.get(d1, 0) / iclose.get(d0, 1) - 1 if d0 in iclose and d1 in iclose else None


# ── 事件池：妖股期簇≥20 日的全部缺口低信号（生产口径排序字段）──
by_day = collections.defaultdict(list)
for code, d in stocks.items():
    n = d["n"]
    for i in range(lp.START, n - 5):
        dt = d["date"][i]
        if lp._epx(d, i) <= 0:
            continue
        try:
            if not det(d, i):
                continue
        except Exception:
            continue
        vols = [d["v"][x] for x in range(max(1, i - 5), i)]
        vr = d["v"][i] / (sum(vols) / len(vols)) if vols and sum(vols) > 0 else 1
        by_day[dt].append({"code": code, "i": i, "vr": vr, "lad": lp._ladder(d, i)})

mega_days = sorted(dt for dt, rows in by_day.items()
                   if len(rows) >= 20 and regime.get(dt) == "妖股期")
print(f"妖股期巨簇日 {len(mega_days)} 天", flush=True)

# ── 批次收益（生产规则：次日开盘接排序前10，T+3 收盘出）──
batches = []
for dt in mega_days:
    rows = sorted(by_day[dt], key=lambda r: (-r["lad"], -r["vr"]))[:10]
    rs = []
    for r in rows:
        d = stocks[r["code"]]
        i = r["i"]
        ep = lp._epx(d, i)
        if i + 4 < d["n"]:
            rs.append(d["c"][i + 4] / ep - 1 - FEE)
    if not rs:
        continue
    p = ipos.get(dt)
    if p is None or p < 6:  # 防负下标回绕
        continue
    bg = {
        "bg1_当日指数跌": idx_ret(ical[p - 1], dt) is not None and idx_ret(ical[p - 1], dt) < 0,
        "bg2_前5日指数<-3%": idx_ret(ical[p - 5], dt) is not None and idx_ret(ical[p - 5], dt) < -0.03,
        "bg3_当日跌停≥30": lp._XLDC.get(dt, 0) >= 30,
        "bg4_前5日有恐慌期": any(regime.get(ical[q]) == "恐慌期" for q in range(max(0, p - 5), p + 1)),
    }
    batches.append({"date": dt, "batch": st.mean(rs), "n": len(rs),
                    "idx1": idx_ret(ical[p - 1], dt), "ldc": lp._XLDC.get(dt, 0), **bg})

print(f"有效批次 {len(batches)}", flush=True)


def dist(xs):
    xs = sorted(xs)
    if not xs:
        return None
    q = lambda p: xs[min(len(xs) - 1, int(len(xs) * p))]
    return {"n": len(xs), "mean": round(st.mean(xs) * 100, 2), "P10": round(q(0.1) * 100, 2),
            "med": round(q(0.5) * 100, 2), "P90": round(q(0.9) * 100, 2),
            "win": round(sum(1 for x in xs if x > 0) / len(xs) * 100, 0)}


out = {}
print("\n═══ 恐慌背景四切法（批次级 T+3 均值%）═══")
for key in ("bg1_当日指数跌", "bg2_前5日指数<-3%", "bg3_当日跌停≥30", "bg4_前5日有恐慌期"):
    yes = [b["batch"] for b in batches if b[key]]
    no = [b["batch"] for b in batches if not b[key]]
    out[key] = {"恐慌背景": dist(yes), "非恐慌背景": dist(no)}
    print(f"  {key}:")
    print(f"    恐慌背景   {dist(yes)}")
    print(f"    非恐慌背景 {dist(no)}")

b0831 = next((b for b in batches if b["date"] == "2026-08-31"), None)
if b0831:
    print(f"\n8/31 批次: {b0831['batch'] * 100:+.2f}% 指数当日 {b0831['idx1'] * 100:+.2f}%  ldc={b0831['ldc']}  "
          f"bg1={b0831['bg1_当日指数跌']} bg2={b0831['bg2_前5日指数<-3%']} bg3={b0831['bg3_当日跌停≥30']} bg4={b0831['bg4_前5日有恐慌期']}")
    out["b0831"] = b0831

out["批次明细"] = [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in b.items()} for b in batches]
json.dump(out, open(f"{ROOT}/data/t1mega_panic_bg_20260922.json", "w"), ensure_ascii=False, indent=1)
print("\nsaved data/t1mega_panic_bg_20260922.json")
