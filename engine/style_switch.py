#!/usr/bin/env python3
"""engine/style_switch.py — 风格切换日研究（2026-09-13，清欠账 #37⑤）

问题（#37 残留）：「我们亏钱的日子谁在赚钱」→ 大小盘风格切换日是否有可交易结构。
定义（全部当日收盘后可算，无未来函数）：
  风格差 D(t) = 小盘组(市值最低五分位)日收益中位数 - 大盘组(最高五分位)日收益中位数
  切换日：sign(D(t)) ≠ sign(mean(D(t-3..t-1))) 且 |D(t)| > 1%（果断翻转才算）
检验：切换日次日开盘等权买入「新领先风格组」T+1/T+5 vs 同组随机日对照（净-0.15%）；
      对照臂：买入「落后风格组」（赌切换失败反转）。
输出：data/style_switch_20260913.json + 双段(2019-22/2023-26)。
"""
import json, glob, random, statistics as st, math
from collections import defaultdict
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
D = ROOT / "data"
FEE = 0.0015

stocks = {}
for f in glob.glob(str(D / "big_kcache/*.json")):
    stocks[Path(f).stem] = json.load(open(f))
cal = [k["date"] for k in stocks["000001"]]

# 月市值 → 五分位标签（code, month) -> q
capq = {}
for f in glob.glob(str(D / "cap_hist/*.json")):
    code = Path(f).stem
    for date, _px, cap in json.load(open(f)):
        capq[(code, date[:7])] = cap
months = sorted({m for _, m in capq})
qbound = {}
for m in months:
    vals = sorted(v for (c, mm), v in capq.items() if mm == m)
    if len(vals) >= 500:
        qbound[m] = (vals[int(len(vals) * 0.2)], vals[int(len(vals) * 0.8)])

idx = {c: {k["date"]: j for j, k in enumerate(ks)} for c, ks in stocks.items()}

# 每日两组收益
small_ret, big_ret = defaultdict(dict), defaultdict(dict)  # date -> code -> ret
for c, ks in stocks.items():
    for j in range(1, len(ks)):
        if ks[j - 1]["close"] <= 0:
            continue
        b = qbound.get(ks[j]["date"][:7])
        if not b:
            continue
        cap = capq.get((c, ks[j]["date"][:7]))
        if cap is None:
            continue
        r = ks[j]["close"] / ks[j - 1]["close"] - 1
        if cap <= b[0]:
            small_ret[ks[j]["date"]][c] = r
        elif cap >= b[1]:
            big_ret[ks[j]["date"]][c] = r

Dd = {}
for d in cal:
    if d in small_ret and d in big_ret and len(small_ret[d]) >= 200 and len(big_ret[d]) >= 200:
        Dd[d] = st.median(small_ret[d].values()) - st.median(big_ret[d].values())

switch_days = []
for t in range(3, len(cal) - 1):
    d = cal[t]
    if d not in Dd:
        continue
    prev = [Dd[x] for x in cal[t - 3:t] if x in Dd]
    if len(prev) < 3:
        continue
    m = st.mean(prev)
    if abs(Dd[d]) > 0.01 and (Dd[d] > 0) != (m > 0):
        switch_days.append((d, "小盘" if Dd[d] > 0 else "大盘"))
print(f"切换日 {len(switch_days)} 天 / 总 {len(Dd)} 天", flush=True)

def group_next(code_group, d, h):
    """d 日组内个股 次日开盘买→+h日收盘 的净收益"""
    rs = []
    for c in code_group:
        j = idx[c].get(d)
        if j is None or j + h + 1 >= len(stocks[c]):
            continue
        o = stocks[c][j + 1]["open"]
        if o <= 0:
            continue
        rs.append(stocks[c][j + h]["close"] / o - 1 - FEE)
    return rs

random.seed(7)
out = {}
for h in (1, 5):
    for arm in ("新领先", "落后"):
        sig, ctl = [], []
        for d, winner in switch_days:
            grp = (small_ret if winner == "小盘" else big_ret)[d]
            lag = (big_ret if winner == "小盘" else small_ret)[d]
            sig += group_next(list(grp) if arm == "新领先" else list(lag), d, h)
        alld = [d for d in cal if d in Dd]
        for d in random.sample(alld, min(len(switch_days) * 3, len(alld))):
            # 随机日对照：等概率买大盘/小盘组
            grp = random.choice([small_ret[d], big_ret[d]])
            ctl += group_next(list(grp), d, h)
        def summ(rs):
            if len(rs) < 30:
                return None
            m = st.mean(rs)
            sd = st.stdev(rs)
            return {"n": len(rs), "mean%": round(100 * m, 2),
                    "win%": round(100 * sum(r > 0 for r in rs) / len(rs), 1),
                    "t": round(m / (sd / math.sqrt(len(rs))), 1) if sd else None}
        s_sig, s_ctl = summ(sig), summ(ctl)
        # 双段
        seg = {}
        for lo, hi, tag in (("2019", "2022", "2019-22"), ("2023", "2026", "2023-26")):
            sub = []
            for d, winner in switch_days:
                if not (lo <= d[:4] <= hi):
                    continue
                grp = (small_ret if winner == "小盘" else big_ret)[d] if arm == "新领先" else \
                      (big_ret if winner == "小盘" else small_ret)[d]
                sub += group_next(list(grp), d, h)
            seg[tag] = summ(sub)
        out[f"T+{h}_{arm}"] = {"切换日臂": s_sig, "随机对照": s_ctl, "双段": seg,
                              "边际pp": round(100 * (st.mean(sig) - st.mean(ctl)), 2) if s_sig and s_ctl else None}

print(json.dumps(out, ensure_ascii=False, indent=1))
(D / "style_switch_20260913.json").write_text(json.dumps(
    {"meta": {"切换日定义": "风格差D符号翻转且|D|>1%", "切换日数": len(switch_days),
              "费": FEE, "对照": "随机日随机风格组"}, "result": out}, ensure_ascii=False, indent=1))
print("SAVED data/style_switch_20260913.json")
