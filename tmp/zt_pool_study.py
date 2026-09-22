"""涨停池质量×次日溢价分组统计（2026-09-22，数据=同花顺涨停池 2025-09-08~2026-09-22，15442 行）。

核心视角：
1) 封板时段 × 次日溢价（验证「早盘板>午盘板>尾盘板」游资经验）
2) **可成交性分解（打板的逆向选择核心）**：未炸板=涨停价买不进（排队也轮不到）；炸板组=你
   能成交的（板破时轮到你）——比较两组的次日溢价差，就是打板的真实成本
3) 炸板次数梯度 / 封单强度（封单额/流通市值）五分位 / 连板数 / 换手率
4) regime 分层（读自家 regime_timeline_hcap）× 时段
5) 位置分层（big_kcache MA60 上下）
次日三价口径：相对当日涨停价。竞价板（09:25 封死）单独组=可执行性≈0 参照。
"""
import collections
import json
import math
import statistics as st

ROOT = "/opt/data/fenjue"
rows = list(__import__("csv").DictReader(open(f"{ROOT}/data/limit_up_mainboard_20250908_20260922.csv", encoding="utf-8-sig")))
tl = json.loads(open(f"{ROOT}/data/regime_timeline_hcap.json").read())
REGIME = {t["date"]: t["regime"] for t in tl}

print(f"总行数 {len(rows)}", flush=True)


def f(r, k):
    try:
        return float(r[k])
    except (TypeError, ValueError):
        return None


def zi(r):
    try:
        return int(r["炸板次数"])
    except (TypeError, ValueError):
        return 0  # 2026-09-22 实证：同花顺空值=0 次开板（与东财 0 逐只对应）


def blk(rs, label=""):
    rs = [r for r in rs if f(r, "次日收盘涨幅(%)") is not None and f(r, "次日开盘涨幅(%)") is not None and f(r, "次日最高涨幅(%)") is not None]
    if len(rs) < 10:
        return None
    o = [f(r, "次日开盘涨幅(%)") for r in rs]
    c = [f(r, "次日收盘涨幅(%)") for r in rs]
    h = [f(r, "次日最高涨幅(%)") for r in rs]
    n = len(rs)
    mo, mc, mh = st.mean(o), st.mean(c), st.mean(h)
    sd = st.stdev(c) if n > 1 else 0
    return {"label": label, "n": n, "开盘均%": round(mo, 2), "收盘均%": round(mc, 2),
            "最高均%": round(mh, 2), "收盘胜率": round(sum(1 for x in c if x > 0) / n, 3),
            "收盘t": round(mc / (sd / math.sqrt(n)), 1) if sd else None}


out = {}

# 1) 封板时段
print("\n═══ ① 封板时段 × 次日溢价 ═══")
for seg in ("竞价板", "早盘板(<10:30)", "午盘板(10:30-14:00)", "尾盘板(>=14:00)"):
    b = blk([r for r in rows if r["封板时段"] == seg], seg)
    out[f"时段_{seg}"] = b
    if b:
        print(f"  {seg:<14} n={b['n']:>5} 开盘{b['开盘均%']:+6.2f}% 收盘{b['收盘均%']:+6.2f}%(t{b['收盘t']}) 最高{b['最高均%']:+6.2f}% 胜率{b['收盘胜率']*100:.0f}%")

# 2) 可成交性分解（逆向选择核心）
print("\n═══ ② 可成交性分解（打板的真实约束）═══")
unbroken = [r for r in rows if zi(r) == 0]
broken = [r for r in rows if zi(r) > 0]
b1, b2 = blk(unbroken, "未炸板(买不进)"), blk(broken, "炸板(你能成交)")
out["可成交_未炸板"], out["可成交_炸板"] = b1, b2
print(f"  未炸板 n={b1['n']} 收盘{b1['收盘均%']:+.2f}%（排队也轮不到你）")
print(f"  炸板   n={b2['n']} 收盘{b2['收盘均%']:+.2f}%（轮到你=板破了）→ 逆向选择成本 {b2['收盘均%']-b1['收盘均%']:+.2f}pp")

# 炸板次数梯度
print("\n═══ ③ 炸板次数梯度 ═══")
for lo, hi, lb in ((1, 1, "1次"), (2, 3, "2-3次"), (4, 999, "≥4次")):
    b = blk([r for r in rows if lo <= zi(r) <= hi], lb)
    out[f"炸板_{lb}"] = b
    if b:
        print(f"  炸板{lb:<6} n={b['n']:>5} 收盘{b['收盘均%']:+6.2f}%(t{b['收盘t']}) 胜率{b['收盘胜率']*100:.0f}%")

# 封单强度五分位（在炸板组内——只有这组你可成交）
print("\n═══ ④ 封单强度（封单额/流通市值）五分位 ═══")
for grp_name, grp in (("全样本", rows), ("炸板组(可成交)", broken)):
    vals = sorted((f(r, "封单额/流通市值(%)") for r in grp if f(r, "封单额/流通市值(%)") is not None))
    if len(vals) < 100:
        continue
    qs = [vals[int(len(vals) * p)] for p in (0.2, 0.4, 0.6, 0.8)]
    print(f"  ── {grp_name}（五分位切点 {[round(q,2) for q in qs]}）──")
    buckets = collections.defaultdict(list)
    for r in grp:
        v = f(r, "封单额/流通市值(%)")
        if v is None:
            continue
        k = sum(v > q for q in qs)
        buckets[k].append(r)
    for k in range(5):
        b = blk(buckets[k], f"Q{k}")
        out[f"封单强度_{grp_name}_Q{k}"] = b
        if b:
            print(f"    Q{k} n={b['n']:>5} 收盘{b['收盘均%']:+6.2f}%(t{b['收盘t']}) 胜率{b['收盘胜率']*100:.0f}%")

# 连板数
print("\n═══ ⑤ 连板数 ═══")
for lo, hi, lb in ((1, 1, "首板"), (2, 2, "2板"), (3, 3, "3板"), (4, 999, "4板+")):
    b = blk([r for r in rows if lo <= int(r["连板数"]) <= hi], lb)
    out[f"连板_{lb}"] = b
    if b:
        print(f"  {lb:<5} n={b['n']:>5} 收盘{b['收盘均%']:+6.2f}%(t{b['收盘t']}) 胜率{b['收盘胜率']*100:.0f}%")

# 换手率
print("\n═══ ⑥ 换手率（封板质量代理）═══")
for lo, hi, lb in ((0, 5, "<5%"), (5, 15, "5-15%"), (15, 30, "15-30%"), (30, 999, ">30%")):
    b = blk([r for r in rows if f(r, "换手率(%)") is not None and lo <= f(r, "换手率(%)") < hi], lb)
    out[f"换手_{lb}"] = b
    if b:
        print(f"  换手{lb:<7} n={b['n']:>5} 收盘{b['收盘均%']:+6.2f}%(t{b['收盘t']}) 胜率{b['收盘胜率']*100:.0f}%")

# regime × 时段
print("\n═══ ⑦ regime × 时段（次日收盘%）═══")
for rg in ("妖股期", "恐慌期", "平淡期", "主线期"):
    seg_stats = {}
    for seg in ("竞价板", "早盘板(<10:30)", "午盘板(10:30-14:00)", "尾盘板(>=14:00)"):
        b = blk([r for r in rows if r["封板时段"] == seg and REGIME.get(r["日期"]) == rg])
        if b and b["n"] >= 30:
            seg_stats[seg] = f"{b['收盘均%']:+.2f}%(n{b['n']})"
            out[f"regime_{rg}_{seg}"] = b
    print(f"  {rg}: {seg_stats}")

json.dump(out, open(f"{ROOT}/data/zt_pool_study_20260922.json", "w"), ensure_ascii=False, indent=1)
print("\nsaved data/zt_pool_study_20260922.json")
