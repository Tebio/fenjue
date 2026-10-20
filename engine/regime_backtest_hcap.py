#!/usr/bin/env python3
"""engine/regime_backtest_hcap.py — 历史市值版周期仪回验 (2026-09-06)

销欠账 #4：与 regime_backtest.py 同规则，但小市值判定用
cap_hist（baostock 换手率反推的当日流通市值），不再是 2026-09-04 常数快照。
产出：与旧 regime_timeline.json 的逐日对比 + 月度分布差异 + 锚点复验。
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
sys.path.insert(0, str(ROOT))
from engine.regime_core import classify as core_classify, load_pct_series  # noqa: E402
KCACHE = ROOT / "data" / "big_kcache"
CAPDIR = ROOT / "data" / "cap_hist"
FULL_N = 3194

_capcache: dict[str, dict[str, float]] = {}


def cap_at(code: str, date: str) -> float | None:
    """当日流通市值（亿）。该日无记录（停牌/无换手）取最近前一日。"""
    if code not in _capcache:
        f = CAPDIR / f"{code}.json"
        _capcache[code] = {r[0]: r[2] for r in json.loads(f.read_text())} if f.exists() else {}
    m = _capcache[code]
    if date in m:
        return m[date]
    prior = [d for d in m if d <= date]
    return m[max(prior)] if prior else None


def load_sectors() -> dict[str, str]:
    out = {}
    imap = ROOT / "data" / "industry_map.json"
    if imap.exists():
        import re as _re
        for c, v in json.loads(imap.read_text()).items():
            out[c] = _re.sub(r"^[A-Z]\d+", "", v.get("industry", ""))
    return out


def main() -> None:
    sectors = load_sectors()
    idx = json.loads((KCACHE.parent / "index_sh000001.json").read_text())  # 2026-09-14 撞代码修复：000001.json=平安银行
    idx_pct = {k["date"]: 0.0 for k in idx}
    for i in range(1, len(idx)):
        idx_pct[idx[i]["date"]] = (float(idx[i]["close"]) / float(idx[i - 1]["close"]) - 1) * 100

    day_boards, day_downs = {}, {}
    for f in sorted(KCACHE.glob("*.json")):
        ks = json.loads(f.read_text())
        for j in range(1, len(ks)):
            pc, tc = float(ks[j - 1]["close"]), float(ks[j]["close"])
            if pc > 0 and (tc - pc) / pc * 100 >= 9.8:
                day_boards.setdefault(ks[j]["date"], []).append(f.stem)
            if pc > 0 and (tc - pc) / pc * 100 <= -9.8:
                day_downs.setdefault(ks[j]["date"], []).append(f.stem)

    def chain(sec):
        if any(k in sec for k in ("计算机", "通信", "电子", "光学", "元件", "半导体", "消费电子", "软件")):
            return "AI电子链"
        return sec

    timeline = []
    pct_series = load_pct_series()  # 分位序列（同 regime_meter 用的那一份）
    for d in sorted(day_boards):
        if d < "2019-01-01":
            continue
        boards = day_boards[d]
        n = len(boards)
        small = sum(1 for c in boards if (cap_at(c, d) or 999) < 100)
        small_ratio = small / n if n else 0
        secs = Counter(chain(sectors.get(c, "其他")) for c in boards)
        known = {k: v for k, v in secs.items() if k != "其他"}
        conc = max(known.values()) / n if known else 0
        ip = idx_pct.get(d, 0)
        nd = len(day_downs.get(d, []))
        # 2026-10-20：判定统一委托 engine/regime_core.py（唯一出处）。
        # 腿一用滚动 250 日分位（合计口径，来自 emotion_series.jsonl），
        # 不再用 `nd >= 20` 这种跨年不可比的绝对门槛。
        regime, _advice = core_classify(
            limit_ups=n,
            index_pct=ip,
            small_cap_ratio=small_ratio,
            top_sector_conc=conc,
            limit_downs_abs=nd,
            pct_limit_down=pct_series.get(d),
        )
        timeline.append({"date": d, "regime": regime, "boards": n, "downs": nd,
                         "small%": round(small_ratio, 2), "conc": round(conc, 2), "idx": round(ip, 2)})

    (ROOT / "data" / "regime_timeline_hcap.json").write_text(json.dumps(timeline, ensure_ascii=False, indent=2))

    # 与旧版（常数市值）逐日对比
    old = {t["date"]: t for t in json.loads((ROOT / "data" / "regime_timeline.json").read_text())}
    flips = Counter()
    flip_days = []
    for t in timeline:
        o = old.get(t["date"])
        if o and o["regime"] != t["regime"]:
            flips[(o["regime"], t["regime"])] += 1
            flip_days.append((t["date"], o["regime"], t["regime"], o["small%"], t["small%"]))
    total = sum(1 for t in timeline if t["date"] in old)
    print(f"可比天数 {total}，翻转 {sum(flips.values())} 天（{sum(flips.values())/max(total,1):.1%}）")
    for (a, b), c in flips.most_common():
        print(f"  {a} → {b}: {c} 天")
    print("\n翻转日明细（前20）：日期 旧→新 旧small%→新small%")
    for d, a, b, s1, s2 in flip_days[:20]:
        print(f"  {d} {a}→{b} {s1:.0%}→{s2:.0%}")

    by_month_new = {}
    for t in timeline:
        by_month_new.setdefault(t["date"][:7], Counter())[t["regime"]] += 1
    by_month_old = {}
    for t in old.values():
        by_month_old.setdefault(t["date"][:7], Counter())[t["regime"]] += 1
    print("\n月度分布差异（只列有变化的月份）:")
    for m in sorted(by_month_new):
        if by_month_new[m] != by_month_old.get(m):
            print(f"  {m}: 旧{dict(by_month_old.get(m, {}))} → 新{dict(by_month_new[m])}")


if __name__ == "__main__":
    main()
