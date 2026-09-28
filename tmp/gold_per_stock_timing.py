"""金股分票择时测试（2026-09-28 上午，用户问「每只金股的技术买点都不一样吧」）。

基线=第6日开盘一刀切。变体（名单发布后窗口内，每票等自己的触发点）：
  C1 首次收盘上穿 MA5 时买（弱势转强的瞬间）
  C2 首次放量（量比>1.5）突破入场日高点时买（启动确认）
  C3 首次回踩 MA10 不破（收盘≥MA10 且当日最低价≤MA10×1.01）时买（回踩买点）
  C4 第6日开盘只买强态（MA5线上或MACD柱放大），弱态跳过（已验证的过滤版）
窗口=第6日起 10 个交易日内，没触发就当月不进场。出场=各自买入日起 T+20 机械出。
口径：费 0.15%，超额 vs 沪深300 同期。缓存段 2020-01~2023-12（49 个月）。
"""
import bisect
import collections
import glob
import json
import os
import statistics as st
import sys

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

ROOT = "/opt/data/fenjue"
FEE = 0.0015
stocks = lp.load_universe()
idx = json.load(open(f"{ROOT}/data/index_sh000001.json"))
idays = [r["date"] for r in idx]
iclose = {r["date"]: r["close"] for r in idx}

picks = {}
for fp in sorted(glob.glob(f"{ROOT}/data/gold_stock_cache/*.json")):
    mo = os.path.basename(fp)[:-5]
    rows = json.load(open(fp))
    if rows:
        picks[mo] = sorted({r["code"] for r in rows})
months = sorted(picks)
print(f"月份 {len(months)}（{months[0]}→{months[-1]}）", flush=True)

def macd_state(c, i):
    """MACD 柱放大？（EMA12/26/9，窗口 120）"""
    if i < 40:
        return None
    seg = c[max(0, i - 120):i + 1]
    def ema(xs, n):
        k = 2 / (n + 1)
        out = [xs[0]]
        for x in xs[1:]:
            out.append(out[-1] + k * (x - out[-1]))
        return out
    e12, e26 = ema(seg, 12), ema(seg, 26)
    difs = [a - b for a, b in zip(e12, e26)]
    dea = sum(difs[-9:]) / 9
    dea_prev = sum(difs[-10:-1]) / 9
    return (difs[-1] - dea) > (difs[-2] - dea_prev)

cells = collections.defaultdict(list)
n_events = 0
for mo in months:
    mdays = [d for d in idays if d.startswith(mo)]
    if len(mdays) < 6:
        continue
    d6 = mdays[5]
    i6 = bisect.bisect_left(idays, d6)
    for code in picks[mo]:
        d = stocks.get(code)
        if not d:
            continue
        i0 = bisect.bisect_left(d["date"], d6)
        if i0 >= d["n"] or d["date"][i0] != d6 or d["o"][i0] <= 0:
            continue
        n_events += 1
        c, o, h, l, v = d["c"], d["o"], d["h"], d["l"], d["v"]

        def fwd(i_buy):
            """买入日 i_buy 开盘入，T+20 收盘出，超额 vs 指数"""
            if i_buy + 21 >= d["n"]:
                return None
            t = c[i_buy + 20] / o[i_buy] - 1 - FEE
            j = bisect.bisect_left(idays, d["date"][i_buy])
            if j + 20 >= len(idays):
                return None
            return t - (iclose[idays[j + 20]] / iclose[idays[j]] - 1)

        # A 基线：第6日开盘
        ex = fwd(i0)
        if ex is not None:
            cells["A 一刀切"].append(ex)
        # C4 强态过滤：MA5线上或MACD柱放大
        if i0 >= 5:
            ma5 = sum(c[i0 - 5:i0]) / 5
            if c[i0 - 1] > ma5 or macd_state(c, i0 - 1):
                ex = fwd(i0)
                if ex is not None:
                    cells["C4 强态才买"].append(ex)
        # C1 窗口内首次收上 MA5
        for j in range(i0, min(i0 + 10, d["n"] - 21)):
            if j >= 5:
                ma5p = sum(c[j - 5:j]) / 5
                ma5n = sum(c[j - 4:j + 1]) / 5
                if c[j - 1] <= ma5p and c[j] > ma5n and o[j + 1] > 0:
                    ex = fwd(j + 1)
                    if ex is not None:
                        cells["C1 收上MA5"].append(ex)
                    break
        # C2 窗口内首次量比>1.5 且突破第6日高点
        hi6 = h[i0]
        for j in range(i0, min(i0 + 10, d["n"] - 21)):
            vbase = [x for x in v[j - 5:j] if x > 0]
            if vbase and v[j] / (sum(vbase) / len(vbase)) > 1.5 and h[j] > hi6 and o[j + 1] > 0:
                ex = fwd(j + 1)
                if ex is not None:
                    cells["C2 放量突破"].append(ex)
                break
        # C3 窗口内首次回踩 MA10 不破
        for j in range(i0, min(i0 + 10, d["n"] - 21)):
            if j >= 10:
                ma10 = sum(c[j - 10:j]) / 10
                if l[j] <= ma10 * 1.01 and c[j] >= ma10 and o[j + 1] > 0:
                    ex = fwd(j + 1)
                    if ex is not None:
                        cells["C3 回踩MA10"].append(ex)
                    break

print(f"事件 {n_events}")
print("═══ 金股分票择时（T+20 超额，各自触发日入场） ═══")
for lb in ("A 一刀切", "C4 强态才买", "C1 收上MA5", "C2 放量突破", "C3 回踩MA10"):
    xs = cells.get(lb, [])
    if len(xs) < 100:
        print(f"  {lb:<12}: n={len(xs)} 薄")
        continue
    wr = sum(1 for x in xs if x > 0) / len(xs)
    print(f"  {lb:<12}: n={len(xs):>4} 超额 {wr * 100:.0f}%/{st.mean(xs) * 100:+.2f}pp")
