#!/usr/bin/env python3
"""regime_full_study.py — 全 regime 覆盖 + 风格剧变期研究（2026-09-19 用户两连令）。

A. 全 regime（主线/妖股/恐慌/平淡）× 关键信号 × T+1/T+5 完整表（一个不落）
B. 风格剧变期：regime 日度转移矩阵 + 翻转窗口识别 +「regime 不稳日」（今日≠昨日）信号表现
"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import law_pipeline as lp

ROOT = Path(__file__).resolve().parent.parent
FEE = 0.0015
SIGS = ["跌停接_MA60下", "组合_跌停低_三连阴", "组合_跌停低_长周期_超跌20", "组合_跌停低_深跌_跌停潮",
        "组合_缺口低开_低位阳线", "组合_触板未封_低位", "强势股回踩MA5", "强势股回踩MA10",
        "反转族_T-1大跌", "金叉_MACD", "TD9买入"]


def fwd(d, i, h):
    ei = i + 1
    if ei + h >= d["n"] or d["o"][ei] <= 0 or d["o"][ei] <= d["c"][i] * 0.905:
        return None
    return d["c"][ei + h] / d["o"][ei] - 1 - FEE


def stat(rs):
    rs = [r for r in rs if r is not None]
    if len(rs) < 50:
        return None
    return {"n": len(rs), "win%": round(100 * sum(x > 0 for x in rs) / len(rs), 1),
            "mean%": round(100 * sum(rs) / len(rs), 2)}


def main():
    stocks = lp.load_universe()
    lp.build_xsection(stocks)
    regime = lp.load_regime()
    tl = json.loads((ROOT / "data/regime_timeline_hcap.json").read_text())
    tl_map = {x["date"]: x["regime"] for x in tl}
    days = sorted(tl_map)

    # B1 转移矩阵 + 翻转率
    trans = Counter()
    flip_days = set()
    for k in range(1, len(days)):
        trans[(tl_map[days[k - 1]], tl_map[days[k]])] += 1
        if tl_map[days[k]] != tl_map[days[k - 1]]:
            flip_days.add(days[k])
    total = sum(trans.values())
    print("== regime 日度转移 ==")
    same = sum(v for (a, b), v in trans.items() if a == b)
    print(f"延续 {same}/{total} = {100*same/total:.1f}%；日翻转率 {100-100*same/total:.1f}%")
    for (a, b), v in trans.most_common(8):
        if a != b:
            print(f"  {a}→{b}: {v} 次")

    # 翻转窗口：10 日内 ≥4 次翻转 = 剧变窗口
    win_flip = {}
    for k in range(len(days)):
        win_flip[days[k]] = sum(1 for d2 in days[max(0, k - 9):k + 1] if d2 in flip_days)
    violent = [d for d in days if win_flip[d] >= 4]
    print(f"\n剧变窗口日（10日内翻转≥4次）: {len(violent)} 天，占 {100*len(violent)/len(days):.1f}%")
    yr = Counter(d[:4] for d in violent)
    print("剧变日分年:", dict(sorted(yr.items())))

    # A+B2 信号 × regime × 稳定/翻转
    print("\n== 信号 × regime ×（稳定日/翻转日）T+5 ==")
    header = f"{'信号':<22}"
    for rg in ("主线期", "妖股期", "恐慌期", "平淡期"):
        header += f"{rg}(稳/翻)".rjust(20)
    print(header)
    out = {}
    for name in SIGS:
        det = lp.REGISTRY.get(name)
        if det is None:
            continue
        cells = defaultdict(list)
        for code, d in stocks.items():
            for i in range(61, d["n"] - 6):
                dt = d["date"][i]
                rg = tl_map.get(dt)
                if rg is None:
                    continue
                try:
                    if det(d, i):
                        r = fwd(d, i, 5)
                        if r is not None:
                            cells[(rg, dt not in flip_days)].append(r)
                except Exception:
                    pass
        line = f"{name:<22}"
        out[name] = {}
        for rg in ("主线期", "妖股期", "恐慌期", "平淡期"):
            ss = stat(cells.get((rg, True), []))
            fs = stat(cells.get((rg, False), []))
            out[name][rg] = {"稳定": ss, "翻转": fs}
            cell = f"{ss['win%']}/{ss['mean%']}n{ss['n']}" if ss else "-"
            cellf = f"{fs['win%']}/{fs['mean%']}" if fs else "-"
            line += f"{cell}|{cellf}".rjust(20)
        print(line, flush=True)

    (ROOT / "data/regime_full_study_20260919.json").write_text(json.dumps({
        "转移矩阵": {f"{a}->{b}": v for (a, b), v in trans.items()},
        "翻转率%": round(100 - 100 * same / total, 1),
        "剧变窗口日数": len(violent), "剧变分年": dict(sorted(yr.items())),
        "信号表": out}, ensure_ascii=False, indent=1))
    print("saved")


if __name__ == "__main__":
    main()
