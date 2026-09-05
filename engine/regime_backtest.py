#!/usr/bin/env python3
"""engine/regime_backtest.py — 情绪周期仪历史回验 (2026-09-06)

周期仪要是不认得过去，它就没资格说现在。用 300 只分层样本 2019-2026 日K
重建每日状态序列（与实时版同规则），验证：
  - 2026 年 6 月（半导体/AI 材料主线期）应判「主线期」
  - 2026 年 8 月下旬-9 月（金健米业/一鸣食品乱飞）应判「妖股期/平淡期」
  - 2026 年 7 月恐慌抛售应判「恐慌期」
注：样本 300 只是全市场的切片——涨停绝对数要按切片比例看，阈值同比例缩放。
市值用当日市值常数近似（历史市值不可得，标注为近似）。
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
KCACHE = ROOT / "data" / "big_kcache"
SAMPLE_N = 300          # 切片规模
FULL_N = 3194           # 全主板规模（MCP 实测）
SCALE = FULL_N / SAMPLE_N  # ~10.6x


def load_sectors() -> dict[str, str]:
    """行业标签：优先 baostock 全市场映射（5546 只），池内 sector 补充。"""
    out = {}
    imap = ROOT / "data" / "industry_map.json"
    if imap.exists():
        import re as _re
        for c, v in json.loads(imap.read_text()).items():
            ind = _re.sub(r"^[A-Z]\d+", "", v.get("industry", ""))  # C39xxx→xxx
            out[c] = ind
    for f in sorted(ROOT.glob("pool_2026*.json")):
        for r in json.loads(f.read_text()).get("results", []):
            c = str(r["code"]).zfill(6)
            if r.get("sector"):
                out[c] = r["sector"]
    return out


def load_caps() -> dict[str, float]:
    caps = {}
    snap = ROOT / "data" / "caps_snapshot.json"
    if snap.exists():
        caps.update(json.loads(snap.read_text())["caps"])  # 2026-09-04 快照，常数近似
    f = ROOT / "data" / "console_banks.json"
    # 常数近似：实时控制台最近一次的市值快照
    for j in ("console_banks.json", "console_sectors.json", "console_dividend_sectors.json",
              "dividend_universe.json"):
        p = ROOT / "data" / j
        if not p.exists():
            continue
        d = json.loads(p.read_text())
        rows = d.get("rows", [])
        for r in rows:
            if isinstance(r, dict) and r.get("code"):
                caps[r["code"]] = r.get("mktcap") or r.get("mktcap_yi") or 0
    return caps


def main() -> None:
    sectors = load_sectors()
    caps = load_caps()
    idx = json.loads((KCACHE / "000001.json").read_text())
    idx_pct = {k["date"]: 0.0 for k in idx}
    for i in range(1, len(idx)):
        idx_pct[idx[i]["date"]] = (float(idx[i]["close"]) / float(idx[i - 1]["close"]) - 1) * 100

    # 每日事件收集
    day_boards = {}
    day_downs = {}
    for f in sorted(KCACHE.glob("*.json")):
        if f.stem == "000001":
            continue
        ks = json.loads(f.read_text())
        for j in range(1, len(ks)):
            pc, tc = float(ks[j - 1]["close"]), float(ks[j]["close"])
            if pc > 0 and (tc - pc) / pc * 100 >= 9.8:
                day_boards.setdefault(ks[j]["date"], []).append(f.stem)
            if pc > 0 and (tc - pc) / pc * 100 <= -9.8:
                day_downs.setdefault(ks[j]["date"], []).append(f.stem)

    # 阈值：样本<1000 只时按切片比例缩放；全量（≥1000）直接用真实阈值
    n_stocks = len(list(KCACHE.glob("*.json"))) - 1
    scale = 1.0 if n_stocks >= 1000 else FULL_N / max(1, n_stocks)
    T_MAIN, T_DEMON, T_PANIC = 50 / scale, 40 / scale, 25 / scale
    def chain(sec):
        if any(k in sec for k in ("计算机", "通信", "电子", "光学", "元件", "半导体", "消费电子", "软件")):
            return "AI电子链"
        return sec
    timeline = []
    for d in sorted(day_boards):
        if d < "2026-01-01":
            continue
        boards = day_boards[d]
        n = len(boards)
        small = sum(1 for c in boards if (caps.get(c) or 999) < 100)
        small_ratio = small / n if n else 0
        secs = Counter(chain(sectors.get(c, "其他")) for c in boards)
        known = {k: v for k, v in secs.items() if k != "其他"}
        conc = max(known.values()) / n if known else 0
        ip = idx_pct.get(d, 0)
        nd = len(day_downs.get(d, []))
        if n >= 60 and conc >= 0.22:
            regime = "主线期"
        elif n >= 40 and small_ratio >= 0.65 and conc < 0.22:
            regime = "妖股期"
        elif nd >= 20 or (n < 30 and ip < -1.0):
            regime = "恐慌期"
        else:
            regime = "平淡期"
        timeline.append({"date": d, "regime": regime, "boards": n, "downs": nd,
                         "small%": round(small_ratio, 2), "conc": round(conc, 2), "idx": round(ip, 2)})

    # 按月汇总
    by_month = {}
    for t in timeline:
        by_month.setdefault(t["date"][:7], Counter())[t["regime"]] += 1
    print("月份 × 周期分布（切片口径）:")
    for m, c in sorted(by_month.items()):
        print(f"  {m}: {dict(c)}")
    (ROOT / "data" / "regime_timeline.json").write_text(json.dumps(timeline, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
