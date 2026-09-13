#!/usr/bin/env python3
"""engine/sector_vshape.py — 板块V型收复研究 v1（2026-09-13 立项，用户批准）

假设来源：洛阳钼业案例验尸（2025-04-07 金属铜指数 -7% 暴跌、次日 V 型收复，此后板块 +80%）——
「板块暴跌后秒收复 = 产业逻辑硬的指纹，可区分错杀与真死」。

事件定义（指数层，指数无成交问题）：
  crash day t0：指数单日跌幅 ≤ -5%（基准价 = t0-1 收盘）
  V收复组：t0+1..t0+10 内首个收盘 ≥ 基准价的日子 = 确认日
  未收复组：10 个交易日内未收复，对照确认点 = t0+10
入场口径：确认日收盘买入。收益：确认日收 → T+10/T+20/T+60 收盘。

三层检验：
  A. 指数层：V收复 vs 未收复 vs 随机指数日对照（seed 固定）
  B. 时间分段：2021-10→2024-05 / 2024-05→2026-09 两段同向才采信
  C. 股票层（次级证据）：事件日的**当前**成分股中当日跌≤-5% 的，确认日起 T+20/T+60
     ⚠️ PIT 偏差：成分映射是 2026-09-13 快照，历史成员不可知，方向性偏高（幸存者留在名单里）——
     股票层结果只作方向参考，不作判决依据。

诚实披露：390 个板块成分高度重叠，事件不独立（2025-04-07 关税日全板块同日暴跌=一簇），
t 值按 Newey-West(lag=5) 但仍高估独立性，判决以「两段同向 + 组间差」为准。
"""
import json, glob, random, math
from pathlib import Path
from statistics import mean, pstdev

ROOT = Path(__file__).resolve().parent.parent
IDX_DIR = ROOT / "data" / "hithink" / "index_hist"
SPLIT = "2024-05-01"          # 时间对半
CRASH = -5.0                  # 单日暴跌阈值 %
REC_DAYS = 10                 # 收复窗口
HORIZONS = {"T+10": 10, "T+20": 20, "T+60": 60}
MIN_HIST = 60                 # 事件前至少60根bar（给对照组/上下文用）
random.seed(20260913)


def nw_t(xs, lag=5):
    """Newey-West HAC t 值（均值≠0）"""
    n = len(xs)
    if n < 10:
        return float("nan")
    m = mean(xs)
    d = [x - m for x in xs]
    v = sum(x * x for x in d) / n
    for l in range(1, lag + 1):
        cov = sum(d[i] * d[i - l] for i in range(l, n)) / n
        v += 2 * (1 - l / (lag + 1)) * cov
    return m / math.sqrt(max(v, 1e-18) / n)


def load_indices():
    out = {}
    for fp in sorted(IDX_DIR.glob("*.json")):
        d = json.load(open(fp))
        bars = d.get("item") or []
        if len(bars) >= MIN_HIST + 70:
            out[d["thscode"]] = {"name": d.get("name", ""), "bars": bars}
    return out


def find_events(bars):
    """返回 [(t0, 确认日idx or None)]，事件间至少隔 REC_DAYS 避免同一簇重复计"""
    evs = []
    i = MIN_HIST
    while i < len(bars) - 61:  # 需要 T+60 前向
        pct = bars[i]["close"] / bars[i - 1]["close"] - 1
        if pct * 100 <= CRASH:
            base = bars[i - 1]["close"]
            rec = None
            for j in range(i + 1, min(i + 1 + REC_DAYS, len(bars))):
                if bars[j]["close"] >= base:
                    rec = j
                    break
            evs.append((i, rec))
            i += REC_DAYS + 1   # 同簇去重
        else:
            i += 1
    return evs


def fwd(bars, i, h):
    if i + h >= len(bars):
        return None
    return bars[i + h]["close"] / bars[i]["close"] - 1


def main():
    indices = load_indices()
    print(f"指数就绪 {len(indices)} 个")

    v_rec, v_non, rnd = [], [], []
    all_days = []  # 随机对照池 (code, i)
    for code, d in indices.items():
        bars = d["bars"]
        for i in range(MIN_HIST, len(bars) - 61):
            all_days.append((code, i))
        for t0, rec in find_events(bars):
            row = {"code": code, "name": d["name"], "date": bars[t0]["date"],
                   "crash_pct": (bars[t0]["close"] / bars[t0 - 1]["close"] - 1) * 100}
            ci = rec if rec is not None else min(t0 + REC_DAYS, len(bars) - 61)
            row["rec_days"] = (rec - t0) if rec is not None else None
            for hn, h in HORIZONS.items():
                r = fwd(bars, ci, h)
                if r is not None:
                    row[hn] = r * 100
            if "T+60" not in row:
                continue
            (v_rec if rec is not None else v_non).append(row)

    for code, i in random.sample(all_days, min(2000, len(all_days))):
        row = {"code": code, "date": indices[code]["bars"][i]["date"]}
        for hn, h in HORIZONS.items():
            r = fwd(indices[code]["bars"], i, h)
            if r is not None:
                row[hn] = r * 100
        if "T+60" in row:
            rnd.append(row)

    def report(group, label):
        tr = [g for g in group if g["date"] < SPLIT]
        te = [g for g in group if g["date"] >= SPLIT]
        out = {"label": label, "n": len(group)}
        for hn in HORIZONS:
            xs = [g[hn] for g in group]
            out[hn] = {"mean%": round(mean(xs), 2), "t": round(nw_t(xs), 1),
                       "win%": round(mean([1 if x > 0 else 0 for x in xs]) * 100, 1),
                       "train%": round(mean([g[hn] for g in tr]), 2) if tr else None,
                       "test%": round(mean([g[hn] for g in te]), 2) if te else None}
        return out

    reps = [report(v_rec, "V收复组"), report(v_non, "未收复组"), report(rnd, "随机对照")]
    for r in reps:
        print(json.dumps(r, ensure_ascii=False))

    # 主判决：V收复 vs 未收复 组间差，T+20/T+60，两段同向
    verdict = {}
    for hn in ["T+20", "T+60"]:
        a = [g[hn] for g in v_rec]; b = [g[hn] for g in v_non]
        diff = mean(a) - (mean(b) if b else 0)
        a_tr = [g[hn] for g in v_rec if g["date"] < SPLIT]
        a_te = [g[hn] for g in v_rec if g["date"] >= SPLIT]
        verdict[hn] = {"V-未收复 diff%": round(diff, 2),
                       "两段同向": (a_tr and a_te and mean(a_tr) > 0 and mean(a_te) > 0)}
    print("VERDICT " + json.dumps(verdict, ensure_ascii=False))

    # ── C. 股票层（PIT 偏差注记，次级证据）──
    sec_map = json.load(open(sorted(glob.glob(str(ROOT / "data/hithink/sectors/stock_sectors_*.json")))[-1]))
    # 反转：指数code → 成分股
    idx2stk = {}
    for stk, lst in sec_map.items():
        for e in lst:
            idx2stk.setdefault(e.get("code") or e.get("thscode"), []).append(stk)
    kcache = ROOT / "data" / "big_kcache"
    s_rec, s_non = [], []
    for grp, bag in [(v_rec, s_rec), (v_non, s_non)]:
        for ev in grp[:300]:  # 限300事件控加载量
            for stk in idx2stk.get(ev["code"], [])[:60]:
                fp = kcache / f"{stk}.json"
                if not fp.exists():
                    continue
                try:
                    kb = json.load(open(fp))
                except Exception:
                    continue
                dates = [b["date"] for b in kb]
                if ev["date"] not in dates:
                    continue
                i0 = dates.index(ev["date"])
                if i0 < 1:
                    continue
                spct = (kb[i0]["close"] / kb[i0 - 1]["close"] - 1) * 100
                if spct > -5:  # 只取当日自己也暴跌的
                    continue
                # 确认日（指数层的事件行里没存确认日，简化为从crash日后第 rec_days 天）
                rd = ev["rec_days"] if ev["rec_days"] is not None else REC_DAYS
                ci = i0 + rd
                if ci + 60 >= len(kb):
                    continue
                e20 = (kb[ci + 20]["close"] / kb[ci]["close"] - 1) * 100
                e60 = (kb[ci + 60]["close"] / kb[ci]["close"] - 1) * 100
                bag.append({"stk": stk, "date": ev["date"], "T+20": e20, "T+60": e60})
    for bag, label in [(s_rec, "股票层·V收复板块内暴跌股"), (s_non, "股票层·未收复板块内暴跌股")]:
        if len(bag) >= 10:
            x20 = [b["T+20"] for b in bag]; x60 = [b["T+60"] for b in bag]
            print(f"{label}: n={len(bag)} T+20 {mean(x20):+.2f}%/t{nw_t(x20):.1f} T+60 {mean(x60):+.2f}%/t{nw_t(x60):.1f}")

    # 多重检验披露
    n_cells = 3 * len(HORIZONS) + 2
    print(f"DISCLOSE 总评估格≈{n_cells}（3组×{len(HORIZONS)}期+2判决），事件独立性受板块重叠/同簇限制，判决以两段同向+组间差为准")

    out = ROOT / "data" / "sector_vshape_20260913.json"
    out.write_text(json.dumps({"index_level": reps, "verdict": verdict,
                               "stock_level_n": {"rec": len(s_rec), "non": len(s_non)}},
                              ensure_ascii=False, indent=1))
    print("SAVED", out)


if __name__ == "__main__":
    main()
