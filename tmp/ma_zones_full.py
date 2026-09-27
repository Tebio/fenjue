"""全均线位置地图（2026-09-27，用户点名「别的指标线呢」）。

A. 六根均线（5/10/20/60/120/250）各自的深度分带：线上 / 0~-5% / -5~-15% / -15~-25% / ≤-25%，前向 T+20。
B. 均线排列状态：完美多头(5>10>20>60>120) / 完美空头(反向) / 纠缠。
C. 判决：哪根线的「线下深度」判别力最强（最深带-线上带 的 T+20 差值排序）。
"""
import collections
import json
import statistics as st
import sys

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

FEE = 0.0015
stocks = lp.load_universe()

def ma(c, i, n):
    if i < n:
        return None
    xs = c[i - n:i]
    return sum(xs) / n if all(x > 0 for x in xs) else None

MA_SET = (5, 10, 20, 60, 120, 250)
zone_cells = collections.defaultdict(list)   # (ma_n, zone) -> [t20]
align_cells = collections.defaultdict(list)  # alignment -> [t20]

print("扫描中（470 万 bar 级 × 6 均线）…", flush=True)
for code, d in stocks.items():
    if code[:2] not in ("60", "00"):
        continue
    c = d["c"]
    n = d["n"]
    for i in range(255, n - 21):  # 需要 250 根历史 → 样本起点后移
        dt = d["date"][i]
        if dt < "2019-07-01" or c[i] <= 0:
            continue
        mas = {m: ma(c, i, m) for m in MA_SET}
        if any(v is None for v in mas.values()):
            continue
        t20 = c[i + 20] / c[i] - 1 - FEE
        for m in MA_SET:
            dev = c[i] / mas[m] - 1
            z = "线上" if dev > 0 else ("0~-5%" if dev > -0.05 else ("-5~-15%" if dev > -0.15 else ("-15~-25%" if dev > -0.25 else "≤-25%")))
            zone_cells[(m, z)].append(t20)
        # 排列状态（5>10>20>60>120）
        seq = [mas[5], mas[10], mas[20], mas[60], mas[120]]
        if all(seq[j] > seq[j + 1] for j in range(4)):
            al = "完美多头"
        elif all(seq[j] < seq[j + 1] for j in range(4)):
            al = "完美空头"
        else:
            al = "纠缠"
        align_cells[al].append(t20)

print("\n═══ A. 各均线的深度分带（T+20） ═══")
zones = ["线上", "0~-5%", "-5~-15%", "-15~-25%", "≤-25%"]
header = f"{'均线':<7}" + "".join(f" | {z:<14}" for z in zones)
print(header)
spread = {}
for m in MA_SET:
    line = f"MA{m:<4}"
    for z in zones:
        xs = zone_cells.get((m, z), [])
        if len(xs) < 1000:
            line += f" | {'n薄':<14}"
            continue
        wr = sum(1 for x in xs if x > 0) / len(xs)
        line += f" | {wr * 100:3.0f}%/{st.mean(xs) * 100:+5.2f}%"
        if z == "线上":
            spread[m] = [-st.mean(xs), len(xs)]
        elif z == "≤-25%":
            spread[m][0] += st.mean(xs)
    print(line)

print("\n═══ B. 均线排列状态（T+20） ═══")
for al in ("完美多头", "纠缠", "完美空头"):
    xs = align_cells.get(al, [])
    wr = sum(1 for x in xs if x > 0) / len(xs)
    print(f"  {al}: n={len(xs):>7} {wr * 100:.0f}%/{st.mean(xs) * 100:+.2f}%")

print("\n═══ C. 哪根线的深度最有信息量（最深带 vs 线上带 的 T+20 差值） ═══")
for m, (sp, _) in sorted(spread.items(), key=lambda kv: -kv[1][0]):
    print(f"  MA{m:<4}: 深度利差 {sp * 100:+.2f}pp")
json.dump({f"{m}|{z}": {"n": len(v), "wr": sum(1 for x in v if x > 0) / len(v), "avg": st.mean(v)}
           for (m, z), v in zone_cells.items()}, open("/opt/data/fenjue/data/ma_zones_full_20260927.json", "w"), ensure_ascii=False)
print("saved")
