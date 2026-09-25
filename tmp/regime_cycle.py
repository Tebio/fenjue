"""周期契机与持续性分析（2026-09-25，用户 Q1+Q8：各周期出现的契机、持续性、启动期/退潮期）。

输入：data/regime_timeline_hcap.json（8 年权威时间轴）+ index_sh000001.json。
输出：①各 regime 段的持续时间分布 ②regime 转移矩阵 ③转移前后指数表现（契机画像）
④段内相位：段的前 1/3=启动期、中 1/3=发酵期、后 1/3=退潮期的指数收益对比。
"""
import collections
import json
import statistics as st

ROOT = "/opt/data/fenjue"
regime = json.load(open(f"{ROOT}/data/regime_timeline_hcap.json"))
tl = regime if isinstance(regime, list) else regime.get("timeline") or list(regime.items())
days = [(x["date"], x["regime"], x) for x in tl]  # 带 boards/downs/idx 特征

idx = json.loads(open(f"{ROOT}/data/index_sh000001.json").read())
idx_map = {k["date"]: float(k["close"]) for k in idx}
cal = sorted(idx_map)

# ① 切段
segs = []
cur_r, start = days[0][1], days[0][0]
prev = days[0][0]
for d, r, f in days[1:]:
    if r != cur_r:
        segs.append({"regime": cur_r, "start": start, "end": prev, "n": None})
        cur_r, start = r, d
    prev = d
segs.append({"regime": cur_r, "start": start, "end": days[-1][0], "n": None})
for s in segs:
    s["n"] = sum(1 for d in cal if s["start"] <= d <= s["end"])
print(f"总段数 {len(segs)}")

print("\n═══ ① 各 regime 持续时间分布 ═══")
for g in ("妖股期", "恐慌期", "平淡期", "主线期"):
    ns = sorted(s["n"] for s in segs if s["regime"] == g)
    if not ns:
        continue
    print(f"  {g}: {len(ns)} 段 | 中位 {ns[len(ns)//2]} 天 | 均值 {st.mean(ns):.0f} 天 | 最短 {ns[0]} | 最长 {ns[-1]} | 段占比 {sum(ns)/sum(s['n'] for s in segs)*100:.0f}%")

print("\n═══ ② 转移矩阵（行=从，列=到） ═══")
trans = collections.Counter()
for a, b in zip(segs, segs[1:]):
    trans[(a["regime"], b["regime"])] += 1
gs = ("妖股期", "恐慌期", "平淡期", "主线期")
print("       " + "  ".join(f"{g:>5}" for g in gs))
for g1 in gs:
    row = [f"{g1:>4}"] + [f"{trans.get((g1, g2), 0):>5}" for g2 in gs]
    print(" ".join(row))

print("\n═══ ③ 转移契机画像（转移日前后指数） ═══")
def idx_ret(d0, d1):
    if d0 in idx_map and d1 in idx_map and idx_map[d0] > 0:
        return idx_map[d1] / idx_map[d0] - 1
    return None

def cal_before(d, k):
    i = cal.index(d) if d in cal else None
    return cal[i - k] if i is not None and i >= k else None

def cal_after(d, k):
    i = cal.index(d) if d in cal else None
    return cal[i + k] if i is not None and i + k < len(cal) else None

for g2 in gs:
    into = [s for s in segs[1:] if s["regime"] == g2]
    before5, after5, after20 = [], [], []
    for s in into:
        b5 = cal_before(s["start"], 5)
        a5, a20 = cal_after(s["start"], 5), cal_after(s["start"], 20)
        r1 = idx_ret(b5, s["start"]) if b5 else None
        r2 = idx_ret(s["start"], a5) if a5 else None
        r3 = idx_ret(s["start"], a20) if a20 else None
        if r1 is not None: before5.append(r1)
        if r2 is not None: after5.append(r2)
        if r3 is not None: after20.append(r3)
    if before5:
        print(f"  →{g2}(n={len(into)}): 前5日指数 {st.mean(before5)*100:+.2f}% | 后5日 {st.mean(after5)*100:+.2f}% | 后20日 {st.mean(after20)*100:+.2f}%")

print("\n═══ ③b 转移契机·特征画像（转入各 regime 前 3 日的涨停/跌停/指数） ═══")
day_feat = {d: f for d, r, f in days}
day_idx = {d: k for k, (d, r, f) in enumerate(days)}
for g2 in gs:
    into = [s for s in segs[1:] if s["regime"] == g2]
    bb, dd, ii = [], [], []
    for s in into:
        k = day_idx.get(s["start"])
        if k is None or k < 3:
            continue
        pre = [days[j][2] for j in range(k - 3, k)]
        bb.append(st.mean(float(x.get("boards") or 0) for x in pre))
        dd.append(st.mean(float(x.get("downs") or 0) for x in pre))
        ii.append(st.mean(float(x.get("idx") or 0) for x in pre))
    if bb:
        print(f"  →{g2}(n={len(bb)}): 前3日均 涨停{st.mean(bb):.0f} 跌停{st.mean(dd):.1f} 指数{st.mean(ii):+.2f}%")

print("\n═══ ④ 段内相位（启动/发酵/退潮 三等分，指数收益） ═══")
for g in gs:
    phases = {0: [], 1: [], 2: []}
    for s in segs:
        if s["regime"] != g or s["n"] < 9:
            continue
        days_in = [d for d in cal if s["start"] <= d <= s["end"]]
        third = len(days_in) // 3
        for ph, (a, b) in ((0, (0, third)), (1, (third, 2 * third)), (2, (2 * third, len(days_in) - 1))):
            if b > a:
                r = idx_ret(days_in[a], days_in[b])
                if r is not None:
                    phases[ph].append(r)
    if phases[0]:
        print(f"  {g}: 启动期 {st.mean(phases[0])*100:+.2f}%(n{len(phases[0])}) | 发酵期 {st.mean(phases[1])*100:+.2f}%(n{len(phases[1])}) | 退潮期 {st.mean(phases[2])*100:+.2f}%(n{len(phases[2])})")

print("\n═══ ⑤ 当前所处段 ═══")
last = segs[-1]
print(f"  当前 {last['regime']} 自 {last['start']} 起，已 {last['n']} 个交易日")
json.dump({"segs": segs, "trans": {f"{a}>{b}": n for (a, b), n in trans.items()}},
          open(f"{ROOT}/data/regime_cycle_20260925.json", "w"), ensure_ascii=False)
print("saved data/regime_cycle_20260925.json")
