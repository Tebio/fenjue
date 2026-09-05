#!/usr/bin/env python3
"""engine/entryexit_matrix.py — 进出场×周期×票型全矩阵回测 (2026-09-06)

不猜。信号 × 买点 × 卖点 × 市场状态 × 票型，全部用 300 只分层样本 2019-2026 日K实测：
  信号：反转(T-1收跌≥3%) / 追高(开盘+2~8.5%) / 首板次日(T-1涨停)
  买点：开盘买 / 尾盘买(D日收盘) / 盘中低吸(挂T-1收盘×0.99，最低价触及才成交)
  卖点：次日开盘卖 / 次日尾盘卖 / 次日盘中止盈(挂买点×1.02，最高价触及成交，否则尾盘)
  市场状态：D日上证 vs MA60（线上=强市/线下=弱市）
  票型：银行 vs 科技(半导体/光学光电/通信设备/元件/消费电子) vs 其他
一字/涨跌停不可成交剔除。零未来函数。
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
KCACHE = ROOT / "data" / "big_kcache"

BANKS = {"601665", "002948", "002142", "601838", "601963", "601939", "600926", "601229",
         "601398", "601288", "601988", "601328", "601077", "600919", "601009",
         "600015", "601166", "601818", "600016", "000001", "601169", "600036", "601825", "601997", "002807", "002839"}
TECH_SEC = {"半导体", "光学光电", "通信设备", "元件", "消费电子", "计算机", "软件"}


def load_sectors() -> dict[str, str]:
    out = {}
    for f in sorted(ROOT.glob("pool_2026*.json")):
        for r in json.loads(f.read_text()).get("results", []):
            out[str(r["code"]).zfill(6)] = r.get("sector", "")
    return out


def pct(a, b):
    return (a - b) / b * 100 if b else 0.0


def stock_group(code: str, sectors: dict[str, str]) -> str:
    if code in BANKS:
        return "银行"
    if sectors.get(code, "") in TECH_SEC:
        return "科技"
    return "其他"


def main() -> None:
    sectors = load_sectors()
    # 上证 MA60 状态序列
    idx = json.loads((KCACHE / "000001.json").read_text())
    idx_c = [float(k["close"]) for k in idx]
    idx_strong = {}
    for i, k in enumerate(idx):
        idx_strong[k["date"]] = idx_c[i] > (sum(idx_c[max(0, i - 60):i]) / max(1, len(idx_c[max(0, i - 60):i]))) if i >= 20 else True

    # stats[信号][买][卖][市态][票型] = [returns]
    stats = defaultdict(list)
    stats_total = defaultdict(list)  # 不分段的总量矩阵
    for f in sorted(KCACHE.glob("*.json")):
        if f.stem == "000001":
            continue
        ks = json.loads(f.read_text())
        n = len(ks)
        if n < 120:
            continue
        group = stock_group(f.stem, sectors)
        for j in range(21, n - 2):
            prev, today, nxt = ks[j - 1], ks[j], ks[j + 1]
            pc, tc = float(prev["close"]), float(today["close"])
            if pc <= 0 or tc <= 0:
                continue
            prev_cc = pct(pc, float(ks[j - 2]["close"]))
            today_o, today_l = float(today["open"]), float(today["low"])
            nxt_o, nxt_h, nxt_c = float(nxt["open"]), float(nxt["high"]), float(nxt["close"])
            open_pct = pct(today_o, pc)
            if abs(open_pct) >= 9.8:
                continue
            strong = idx_strong.get(today["date"], True)
            regime = "强市" if strong else "弱市"

            sig = None
            if prev_cc <= -3.0:
                sig = "反转"
            elif 2.0 <= open_pct <= 8.5:
                sig = "追高"
            elif prev_cc >= 9.8:
                sig = "首板次日"
            if not sig:
                continue

            for buy_mode in ("开盘", "尾盘", "盘中低吸"):
                if buy_mode == "开盘":
                    buy = today_o
                elif buy_mode == "尾盘":
                    buy = tc
                else:
                    limit = pc * 0.99
                    if today_l > limit:
                        continue  # 未成交
                    buy = limit
                for sell_mode in ("次日开盘", "次日尾盘", "次日止盈2%"):
                    if sell_mode == "次日开盘":
                        sell = nxt_o
                    elif sell_mode == "次日尾盘":
                        sell = nxt_c
                    else:
                        target = buy * 1.02
                        sell = target if nxt_h >= target else nxt_c
                    stats[(sig, buy_mode, sell_mode, regime, group)].append(pct(sell, buy))
                    stats_total[(sig, buy_mode, sell_mode)].append(pct(sell, buy))

    # 汇总打印：先总矩阵（全市态），再按市态、票型拆
    def agg(rows):
        if len(rows) < 30:
            return None
        return {"n": len(rows), "win%": round(sum(1 for x in rows if x > 0) / len(rows) * 100, 1),
                "avg%": round(sum(rows) / len(rows), 3)}

    out = {"matrix": {}, "by_regime": {}, "by_group": {}}
    for (sig, b, s), rows in sorted(stats_total.items()):
        a = agg(rows)
        if a:
            out["matrix"].setdefault(sig, {}).setdefault(b, {})[s] = a
    for (sig, b, s, reg, grp), rows in sorted(stats.items()):
        a = agg(rows)
        if a:
            out["by_regime"].setdefault(reg, {}).setdefault(sig, {}).setdefault(b, {})[s] = a
            out["by_group"].setdefault(grp, {}).setdefault(sig, {}).setdefault(b, {})[s] = a
    (ROOT / "data" / "entryexit_matrix.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))

    for sig in ("反转", "追高", "首板次日"):
        print(f"\n══ {sig} ══")
        for b in ("开盘", "尾盘", "盘中低吸"):
            for s in ("次日开盘", "次日尾盘", "次日止盈2%"):
                a = out["matrix"].get(sig, {}).get(b, {}).get(s)
                if a:
                    print(f"  {b}买→{s}卖: n={a['n']} 胜率{a['win%']}% 均值{a['avg%']:+.3f}%")


if __name__ == "__main__":
    main()
