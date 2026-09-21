"""big_kcache 完整性审计（2026-09-21 baostock 断链事故后，用户问：历史胜率有没有被污染）。

两项检查：
1. 逐日覆盖率：2026-09-12（日更器上线）以来每个交易日，big_kcache 有当日 bar 的文件占比。
   若某天像 9/21 这样大面积缺失 → 该天信号/收益在所有回测里被低估，需重跑。
2. 全历史空洞：每只票在自己存续期内缺多少个交易日（vs 指数日历）。
   个别票长期停牌的缺是正常的；大面积同日缺才是断链签名。
"""
import collections
import glob
import json

KC = "/opt/data/fenjue/data/big_kcache"
idx = json.load(open("/opt/data/fenjue/data/index_sh000001.json"))
cal = [k["date"] for k in idx]
recent = [d for d in cal if "2026-09-12" <= d <= "2026-09-18"]  # 日更器上线后到事故前
full_cal_set = set(cal)

files = sorted(glob.glob(f"{KC}/*.json"))
per_day = collections.Counter()
holes_dist = []
hole_examples = collections.Counter()  # 哪些日期最常出现在空洞里

for fp in files:
    code = fp.split("/")[-1][:6]
    if code == "000001":
        continue
    try:
        ks = json.load(open(fp))
    except Exception:
        continue
    dates = set(k["date"] for k in ks)
    # 1. 近期逐日覆盖
    for d in recent:
        if d in dates:
            per_day[d] += 1
    # 2. 全历史空洞（只在票自己的存续窗口内算）
    if not dates:
        continue
    span = [d for d in cal if min(dates) <= d <= max(dates)]
    holes = [d for d in span if d not in dates]
    holes_dist.append(len(holes))
    for d in holes:
        hole_examples[d] += 1

print("═══ 1. 近期逐日覆盖率（9/12-9/18，日更器运行的全部交易日）═══")
n = len(files) - 1
for d in recent:
    c = per_day[d]
    flag = "⚠️" if c < n * 0.95 else "✓"
    print(f"  {d}: {c}/{n}（{c / n * 100:.1f}%）{flag}")

print("\n═══ 2. 全历史空洞分布 ═══")
holes_dist.sort()
import statistics
print(f"  中位数 {holes_dist[len(holes_dist) // 2]} 天/票，P95 {holes_dist[int(len(holes_dist) * 0.95)]}，最大 {holes_dist[-1]}")
print(f"  空洞>30 天的票: {sum(1 for h in holes_dist if h > 30)} 只（多为长期停牌）")
print("\n  空洞最集中的日期 TOP10（若集中在同一交易日=断链签名）:")
for d, c in hole_examples.most_common(10):
    print(f"    {d}: {c} 只缺")
