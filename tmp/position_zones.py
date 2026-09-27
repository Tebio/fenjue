"""位置分带地图（2026-09-27 午后，用户点名）：持仓在 MA20/MA60 各区间的前向收益。

分带（收盘价相对 MA20/MA60）：
  Z1 双线上（c>MA20 且 MA20>MA60，多头排列强势）
  Z2 双线死叉上（c>MA20 但 MA20<MA60，反弹区）
  Z3 回踩区·多头（MA60<c<MA20 且 MA20>MA60）← 用户持仓现在在这
  Z4 回踩区·空头（MA60<c<MA20 且 MA20<MA60）
  Z5 浅跌破（MA60×0.9<c<MA60）
  Z6 中度深跌（MA60×0.75<c≤MA60×0.9）
  Z7 深档区（MA60×0.65<c≤MA60×0.75）
  Z8 极深区（c≤MA60×0.65）
前向 T+5/20/60（当日收盘为锚，费0.15%）。再 × regime 看「回踩区」在什么时候最安全。
"""
import bisect
import collections
import json
import statistics as st
import sys

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

FEE = 0.0015
stocks = lp.load_universe()
regime = lp.load_regime()

def ma(c, i, n):
    if i < n:
        return None
    xs = c[i - n:i]
    return sum(xs) / n if all(x > 0 for x in xs) else None

cells = collections.defaultdict(list)
reg_cells = collections.defaultdict(list)
print("扫描全市场位置分带…", flush=True)
for code, d in stocks.items():
    if code[:2] not in ("60", "00"):
        continue
    c = d["c"]
    n = d["n"]
    for i in range(65, n - 61):
        dt = d["date"][i]
        if dt < "2019-07-01":
            continue
        m20, m60 = ma(c, i, 20), ma(c, i, 60)
        if not m20 or not m60 or c[i] <= 0:
            continue
        px = c[i]
        if px > m20:
            z = "Z1双线上·多头" if m20 > m60 else "Z2双线上·空头"
        elif px > m60:
            z = "Z3回踩·多头" if m20 > m60 else "Z4回踩·空头"
        elif px > m60 * 0.9:
            z = "Z5浅跌破"
        elif px > m60 * 0.75:
            z = "Z6中度深跌"
        elif px > m60 * 0.65:
            z = "Z7深档区"
        else:
            z = "Z8极深区"
        r5 = c[i + 5] / px - 1 - FEE
        r20 = c[i + 20] / px - 1 - FEE
        r60 = c[i + 60] / px - 1 - FEE
        cells[z].append((r5, r20, r60))
        if z.startswith("Z3") or z.startswith("Z4"):
            reg_cells[(z, regime.get(dt, "平淡期"))].append(r20)

print("═══ 位置分带地图（全市场 2019-07→2026-09） ═══")
print(f"{'带':<16} {'n':>8} | {'T+5':>15} | {'T+20':>15} | {'T+60':>15}")
order = ["Z1双线上·多头", "Z2双线上·空头", "Z3回踩·多头", "Z4回踩·空头", "Z5浅跌破", "Z6中度深跌", "Z7深档区", "Z8极深区"]
for z in order:
    rows = cells.get(z, [])
    if not rows:
        continue
    line = f"{z:<16} {len(rows):>8}"
    for j in range(3):
        xs = [r[j] for r in rows]
        wr = sum(1 for x in xs if x > 0) / len(xs)
        line += f" | {wr * 100:4.0f}%/{st.mean(xs) * 100:+5.2f}%"
    print(line)

print("\n═══ 回踩区 × regime（T+20） ═══")
for z in ("Z3回踩·多头", "Z4回踩·空头"):
    for g in ("恐慌期", "平淡期", "妖股期", "主线期"):
        xs = reg_cells.get((z, g), [])
        if len(xs) < 500:
            continue
        wr = sum(1 for x in xs if x > 0) / len(xs)
        print(f"  {z}×{g}: n={len(xs):>7} {wr * 100:.0f}%/{st.mean(xs) * 100:+.2f}%")
json.dump({k: {"n": len(v), "t20_wr": sum(1 for r in v if r[1] > 0) / len(v), "t20_avg": st.mean(r[1] for r in v)}
           for k, v in cells.items()}, open("/opt/data/fenjue/data/position_zones_20260927.json", "w"), ensure_ascii=False)
print("saved")
