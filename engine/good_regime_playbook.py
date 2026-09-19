#!/usr/bin/env python3
"""good_regime_playbook.py — 情绪好时玩什么（2026-09-19 用户批评「只有恐慌策略」立项）。

全注册表 × 4 regime × T+1/T+5 扫描，找主线期/妖股期的正期望格。
每格要求 n≥100 才显示；标 t 值。产出「情绪好时的可玩清单」。
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import law_pipeline as lp

ROOT = Path(__file__).resolve().parent.parent
FEE = 0.0015


def fwd(d, i, h):
    ei = i + 1
    if ei + h >= d["n"] or d["o"][ei] <= 0 or d["o"][ei] <= d["c"][i] * 0.905:
        return None
    return d["c"][ei + h] / d["o"][ei] - 1 - FEE


def stat(rs):
    rs = [r for r in rs if r is not None]
    if len(rs) < 100:
        return None
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    m = sum(rs) / len(rs)
    sd = (sum((x - m) ** 2 for x in rs) / len(rs)) ** 0.5 or 1e-9
    odds = (sum(wins) / len(wins)) / abs(sum(losses) / len(losses)) if wins and losses else None
    return {"n": len(rs), "win%": round(100 * len(wins) / len(rs), 1), "mean%": round(100 * m, 2),
            "t": round(m / sd * len(rs) ** 0.5, 1), "赔率": round(odds, 2) if odds else None}


# ---- 情绪好时的专用检测器（2026-09-19 加：注册表全是抄底味，补两只强势侧）----
def _strong_pullback_ma5(d, i):
    """强势股回踩MA5：近20日≥2次涨停（强势证明）+ 收盘在MA10上 + 今日盘中跌破MA5收回（回踩）。"""
    c, l, n = d["c"], d["l"], d["n"]
    if i < 25 or c[i] <= 0:
        return False
    boards = sum(1 for j in range(i - 20, i) if c[j] > 0 and c[j - 1] > 0 and c[j] / c[j - 1] - 1 >= 0.098)
    if boards < 2:
        return False
    ma5 = sum(c[i - 4:i + 1]) / 5
    ma10 = sum(c[i - 9:i + 1]) / 10
    return l[i] < ma5 <= c[i] and c[i] > ma10


def _strong_pullback_ma10(d, i):
    """强势股回踩MA10（更深一档回调）。"""
    c, l, n = d["c"], d["l"], d["n"]
    if i < 25 or c[i] <= 0:
        return False
    boards = sum(1 for j in range(i - 20, i) if c[j] > 0 and c[j - 1] > 0 and c[j] / c[j - 1] - 1 >= 0.098)
    if boards < 2:
        return False
    ma10 = sum(c[i - 9:i + 1]) / 10
    ma20 = sum(c[i - 19:i + 1]) / 20
    return l[i] < ma10 <= c[i] and c[i] > ma20


def main():
    stocks = lp.load_universe()
    lp.build_xsection(stocks)
    regime = lp.load_regime()
    registry = dict(lp.REGISTRY)
    registry["强势股回踩MA5"] = _strong_pullback_ma5
    registry["强势股回踩MA10"] = _strong_pullback_ma10
    # 每信号 × regime × horizon
    out = {}
    for name, det in registry.items():
        cells = defaultdict(list)
        for code, d in stocks.items():
            for i in range(61, d["n"] - 21):
                rg = regime.get(d["date"][i])
                if rg is None:
                    continue
                try:
                    if det(d, i):
                        r1 = fwd(d, i, 1)
                        r5 = fwd(d, i, 5)
                        if r1 is not None:
                            cells[(rg, 1)].append(r1)
                        if r5 is not None:
                            cells[(rg, 5)].append(r5)
                except Exception:
                    pass
        good = {}
        for rg in ("主线期", "妖股期"):
            for h in (1, 5):
                s = stat(cells.get((rg, h), []))
                if s:
                    good[f"{rg}_T+{h}"] = s
        if good:
            out[name] = good
    # 打印：主线期/妖股期里 T+5 为正的格子
    print("== 情绪好时（主线期/妖股期）T+5 正期望格 ==")
    found = []
    for name, g in out.items():
        for k, s in g.items():
            if s["mean%"] > 0 and s["t"] >= 2:
                found.append((k, name, s))
    found.sort(key=lambda x: -x[2]["mean%"])
    for k, name, s in found:
        print(f"  {k} | {name}: n={s['n']} 胜{s['win%']}% 均{s['mean%']}% t={s['t']} 赔{s['赔率']}")
    if not found:
        print("  （无 t≥2 正格）")
    (ROOT / "data/good_regime_playbook_20260919.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("saved")


if __name__ == "__main__":
    main()
