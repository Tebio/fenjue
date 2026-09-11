#!/usr/bin/env python3
"""fen_shadow_universe.py — 焚诀短线门·全样本历史回测 (2026-09-06)

与 fen_shadow.py（池内快照回放）互补：快照只存了池内票的 9:40 行情，
本模块把焚诀短线门套到【903 票 × 107 板块】的全样本上，用日K开盘价做决策点：
  门（全来自 T-1 及更早数据，零未来函数）：
    - 开盘涨幅 ∈ [2.0%, 8.5%]（fast scanner 默认门槛）
    - 开盘价站上 MA5 或 MA20（MA 用截至 T-1 的收盘算）
    - MA20 乖离 ≤ 35%
  排序：流动性(T-1成交额) + 开盘涨幅甜点(≈4.8%) + 板块共振(同板块当日开盘强度/只数)
  买入：D 日开盘价 → T1/T2 收盘收益
  对照：过闸候选等权 / 每日随机3票(10种子均值) / 上证指数
"""
from __future__ import annotations

import json
import random
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
sys.path.insert(0, str(ROOT))
from fen_shadow import daily_kline  # noqa: E402  复用带缓存的日K抓取

TRADING_DATES = sorted(
    p.stem.replace("snapshot_", "").replace("_0940", "")
    for p in (ROOT / "snapshots").glob("snapshot_*_0940.json")
)


def load_universe() -> dict[str, dict]:
    codes: dict[str, dict] = {}
    for f in sorted(ROOT.glob("pool_20*.json")):
        for r in json.loads(f.read_text()).get("results", []):
            c = str(r["code"]).zfill(6)
            if c.startswith(("600", "601", "603", "605", "000", "001", "002", "003")):
                codes.setdefault(c, {"name": r["name"], "sector": r.get("sector", "")})
    return codes


def iso(d: str) -> str:
    return f"{d[:4]}-{d[4:6]}-{d[6:]}"


def build_features(universe: dict[str, dict]) -> dict:
    """每票: {days, closes, by_day} 索引; MA 用 rolling。"""
    feats = {}
    for i, (code, meta) in enumerate(universe.items()):
        try:
            ks = daily_kline(("sh" if code.startswith("6") else "sz") + code)
        except Exception:
            continue
        if not ks:
            continue
        days = [k["day"] for k in ks]
        closes = [float(k["close"]) for k in ks]
        feats[code] = {"meta": meta, "days": days, "ks": ks, "closes": closes,
                       "idx": {d: j for j, d in enumerate(days)}}
        if i % 150 == 0:
            print(f"  K线进度 {i}/{len(universe)}", file=sys.stderr)
    return feats


def gate_and_rank(feats: dict, d: str, top: int | None = 3) -> list[dict]:
    """top=None 返回全部过闸候选（供「过闸等权」基线用，2026-09-06 外部审查发现#4）。"""
    d_iso = iso(d)
    rows = []
    for code, f in feats.items():
        j = f["idx"].get(d_iso)
        if j is None or j < 21:
            continue
        k = f["ks"][j]
        prev = float(f["ks"][j - 1]["close"])
        open_p = float(k["open"])
        if prev <= 0 or open_p <= 0:
            continue
        open_pct = (open_p - prev) / prev * 100
        if not (2.0 <= open_pct <= 8.5):
            continue
        ma5 = sum(f["closes"][j - 5:j]) / 5
        ma20 = sum(f["closes"][j - 20:j]) / 20
        if not (open_p > ma5 or open_p > ma20):
            continue
        ma20_gap = (open_p - ma20) / ma20 * 100
        if ma20_gap > 35:
            continue
        t1_amt = float(f["ks"][j - 1].get("volume", 0)) * prev / 1e8
        rows.append({"code": code, "name": f["meta"]["name"], "sector": f["meta"]["sector"],
                     "open_pct": open_pct, "buy": open_p, "t1_amt": t1_amt, "ma20_gap": ma20_gap,
                     "j": j})
    if not rows:
        return []
    max_amt = max(r["t1_amt"] for r in rows) or 1
    sec_pct = defaultdict(list)
    for r in rows:
        sec_pct[r["sector"]].append(r["open_pct"])
    sec_mean = {s: sum(v) / len(v) for s, v in sec_pct.items()}
    max_sec = max(sec_mean.values()) or 1
    sec_cnt = defaultdict(int)
    for r in rows:
        sec_cnt[r["sector"]] += 1
    max_cnt = max(sec_cnt.values()) or 1
    for r in rows:
        sweet = max(0, 6.5 - abs(r["open_pct"] - 4.8)) / 6.5
        r["score"] = ((r["t1_amt"] / max_amt) * 40 + sweet * 20
                      + (max(sec_mean[r["sector"]], 0) / max_sec) * 30
                      + (sec_cnt[r["sector"]] / max_cnt) * 10)
    rows.sort(key=lambda x: x["score"], reverse=True)
    return rows if top is None else rows[:top]


def fwd(feats: dict, code: str, j: int, buy: float, horizon: int) -> float | None:
    if j + horizon >= len(feats[code]["ks"]):
        return None
    return round((float(feats[code]["ks"][j + horizon]["close"]) - buy) / buy * 100, 2)


def main() -> int:
    top = 3
    universe = load_universe()
    print(f"全样本: {len(universe)} 票", file=sys.stderr)
    feats = build_features(universe)
    print(f"K线就绪: {len(feats)} 票", file=sys.stderr)

    idx_ks = daily_kline("sh000001")
    idx_by_day = {k["day"]: k for k in idx_ks}

    per_day = []
    for d in TRADING_DATES:
        gate_all = gate_and_rank(feats, d, top=None)
        if not gate_all:
            continue
        picks = gate_all[:top]
        # 对照组A：当日全宇宙随机3票 × 10种子（2026-09-06 外部审查发现#4修复：
        # 旧版单种子 Random(42) 一次抽样，跟 docstring 承诺的 10 种子均值不符）
        all_codes = [c for c, f in feats.items() if iso(d) in f["idx"] and f["idx"][iso(d)] >= 21]
        rand_picks = []
        for seed in range(10):
            rng = random.Random(seed)
            rand_picks.extend(rng.sample(all_codes, min(3, len(all_codes))))
        day = {"date": d, "picks": [], "rand": [], "gate": [], "index": {}}
        for p in picks:
            t1, t2 = fwd(feats, p["code"], p["j"], p["buy"], 1), fwd(feats, p["code"], p["j"], p["buy"], 2)
            day["picks"].append({**{k: p[k] for k in ("code", "name", "sector", "open_pct", "score")}, "T1": t1, "T2": t2})
        # 对照组B：当日全部过闸候选等权（测「闸门之后打分排序有没有加分」，发现#4 补充）
        for p in gate_all:
            t1, t2 = fwd(feats, p["code"], p["j"], p["buy"], 1), fwd(feats, p["code"], p["j"], p["buy"], 2)
            day["gate"].append({"code": p["code"], "T1": t1, "T2": t2})
        for c in rand_picks:
            j = feats[c]["idx"][iso(d)]
            buy = float(feats[c]["ks"][j]["open"])
            day["rand"].append({"code": c, "T1": fwd(feats, c, j, buy, 1), "T2": fwd(feats, c, j, buy, 2)})
        dk = idx_by_day.get(iso(d))
        if dk:
            buy = float(dk["open"])
            for hz, off in (("T1", 1), ("T2", 2)):
                j = [k["day"] for k in idx_ks].index(iso(d))
                if j + off < len(idx_ks):
                    day["index"][hz] = round((float(idx_ks[j + off]["close"]) - buy) / buy * 100, 2)
        per_day.append(day)
        top1 = day["picks"][0] if day["picks"] else None
        print(f"{d}: Top1 {top1['name']} T1 {top1['T1']:+.1f}%" if top1 and top1["T1"] is not None else f"{d}: n/a", file=sys.stderr)

    def agg(rows, key):
        vals = [r[key] for r in rows if r.get(key) is not None]
        if not vals:
            return {"n": 0}
        wins = sum(1 for v in vals if v > 0)
        return {"n": len(vals), "win%": round(wins / len(vals) * 100, 1), "avg%": round(sum(vals) / len(vals), 2)}

    all_picks = [p for d in per_day for p in d["picks"]]
    all_rand = [p for d in per_day for p in d["rand"]]
    all_gate = [p for d in per_day for p in d["gate"]]
    idx_rows = [d["index"] for d in per_day if d["index"]]
    out = {
        "universe": len(feats), "days": len(per_day),
        "fenjue": {"T1": agg(all_picks, "T1"), "T2": agg(all_picks, "T2")},
        "gate_equal_weight": {"T1": agg(all_gate, "T1"), "T2": agg(all_gate, "T2")},
        "random3_10seed": {"T1": agg(all_rand, "T1"), "T2": agg(all_rand, "T2")},
        "index": {"T1": agg(idx_rows, "T1"), "T2": agg(idx_rows, "T2")},
        "by_month": {},
    }
    # 动态月份（发现#4附带修复：旧版硬编码 202605-202607，之后的月份静默丢失）
    months = sorted({d["date"][:6] for d in per_day})
    for m in months:
        mp = [p for d in per_day if d["date"].startswith(m) for p in d["picks"]]
        mr = [p for d in per_day if d["date"].startswith(m) for p in d["rand"]]
        if mp:
            out["by_month"][m] = {"fenjue_T1": agg(mp, "T1"), "random_T1": agg(mr, "T1")}
    (ROOT / "data" / "shadow_universe.json").write_text(json.dumps({"summary": out, "per_day": per_day}, ensure_ascii=False, indent=2))
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
