"""反复吃肉票解剖（2026-09-21 用户立项：「这几周一直出现的票，为什么能吃肉」）。

1. 肉在哪：近4周（8/24-9/18）大涨日（≥+9.5%）按行业聚合
2. 反复出现的票：窗口内大涨日≥3 的票，画像（行业/位置/连板属性/咱家影子覆盖）
3. 用户主张检验：「10:30就能看出情绪」→ 巨簇日（缺口低簇≥20·妖股/恐慌期）
   当日尾盘接（close→T+3close）vs 次日开盘接（next_open→T+3close）
列式数据结构：d['date']/d['c']/d['o']/d['ma60']/d['amt']/d['n']。
"""
import collections
import glob
import json
import sys

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

WIN0, WIN1 = "2026-08-24", "2026-09-18"
BIG = 0.095
ROOT = "/opt/data/fenjue"

stocks = lp.load_universe()
regime = lp.load_regime()
idx = json.loads(open(f"{ROOT}/data/index_sh000001.json").read())
cal = [k["date"] for k in idx]
win = [d for d in cal if WIN0 <= d <= WIN1]
print(f"窗口 {win[0]}~{win[-1]} 共 {len(win)} 交易日，宇宙 {len(stocks)}")

_ind = json.loads(open(f"{ROOT}/data/industry_map.json").read())
c2i = {str(k).zfill(6): v["industry"] for k, v in _ind.items() if isinstance(v, dict) and v.get("industry")}
names = {str(s["code"]).zfill(6): s.get("name", "")
         for s in json.loads(open(f"{ROOT}/data/main_board_codes.json").read()).get("stocks", [])}

# ── 1/2. 逐票大涨日统计 ──
stock_stat = {}
ind_big = collections.Counter()
for code, d in stocks.items():
    didx = {dt: i for i, dt in enumerate(d["date"])}
    bigs = []
    for day in win:
        i = didx.get(day)
        if i is not None and i >= 1 and d["c"][i - 1] > 0 and d["c"][i] / d["c"][i - 1] - 1 >= BIG:
            bigs.append(day)
    if not bigs:
        continue
    i0, i1 = didx.get(win[0]), didx.get(win[-1])
    tot = (d["c"][i1] / d["c"][i0 - 1] - 1) * 100 if i0 and i1 and i0 >= 1 else None
    ind = c2i.get(code, "未知")
    stock_stat[code] = {"big_days": len(bigs), "dates": bigs, "tot": tot, "ind": ind,
                        "name": names.get(code, code)}
    ind_big[ind] += len(bigs)

print("\n═══ 肉在哪：大涨日（≥+9.5%）行业分布 TOP12 ═══")
tot_big = sum(ind_big.values())
for ind, n in ind_big.most_common(12):
    print(f"{ind:<10} {n:>4} 次（{n / tot_big * 100:.1f}%）")

rec = sorted(((c, s) for c, s in stock_stat.items() if s["big_days"] >= 3),
             key=lambda x: (-x[1]["big_days"], -(x[1]["tot"] or 0)))
print(f"\n═══ 反复吃肉票（大涨日≥3，共 {len(rec)} 只）═══")
for c, s in rec[:30]:
    print(f"{s['name']}({c}) {s['ind']:<8} 大涨{s['big_days']}天 窗口累计{(s['tot'] or 0):+.0f}%  {','.join(d[5:] for d in s['dates'])}")

if rec:
    inds = collections.Counter(s["ind"] for _, s in rec)
    print(f"\n反复票行业: {dict(inds.most_common(8))}")
    up = dn = 0
    for c, s in rec:
        d = stocks[c]
        didx = {dt: i for i, dt in enumerate(d["date"])}
        i0 = didx.get(win[0])
        if i0 is not None and d["ma60"][i0] is not None:
            if d["c"][i0] >= d["ma60"][i0]:
                up += 1
            else:
                dn += 1
    print(f"窗口首日位置: MA60上 {up} / MA60下 {dn}")
    # 连板属性：窗口内最大连续大涨天数
    chains = []
    for c, s in rec:
        d = stocks[c]
        didx = {dt: i for i, dt in enumerate(d["date"])}
        mx = 0
        for day in s["dates"]:
            i = didx[day]
            ln = 1
            j = i - 1
            while j >= 1 and d["c"][j] / d["c"][j - 1] - 1 >= BIG:
                ln += 1
                j -= 1
            mx = max(mx, ln)
        chains.append(mx)
    print(f"最大连板分布: {dict(collections.Counter(chains))}")

# ── 3. 咱家影子覆盖 ──
try:
    sh = [json.loads(x) for x in open(f"{ROOT}/data/xrules_shadow.jsonl") if x.strip()]
    sh_codes = {e["code"] for e in sh}
    hit = [(c, s) for c, s in rec if c in sh_codes]
    print(f"\n咱家影子单覆盖反复票: {len(hit)}/{len(rec)} → {[s['name'] for _, s in hit]}")
except FileNotFoundError:
    pass

# ── 4. 巨簇日 尾盘接 vs 次日开盘接（T1-MEGA 口径，全史 2019 起）──
print("\n═══ 巨簇日（缺口低簇≥20·妖股/恐慌期）尾盘接 vs 次日开盘接，出场=T+3收盘 ═══")
det = lp.REGISTRY["组合_缺口低开_低位阳线_避周一"]
by_date = collections.defaultdict(list)
for code, d in stocks.items():
    for i in range(lp.START, d["n"] - 1):
        if d["c"][i - 1] > 0 and det(d, i):
            by_date[d["date"][i]].append((code, i))
FEE = 0.003
res = {"close": [], "open": []}
mega_days = 0
for day in sorted(by_date):
    if day < "2019-01-01" or len(by_date[day]) < 20 or regime.get(day) not in ("妖股期", "恐慌期"):
        continue
    mega_days += 1
    di = cal.index(day)
    if di + 4 >= len(cal):
        continue
    e_day, x_day = cal[di + 1], cal[di + 3]   # open-entry：次日开盘买，T+3=信号日+3 收盘（对齐 xrules: entry=di+1, exit=di+3 即入场后第2天？）
    # 对齐 xrules_daily 影子口径：entry=次交易日开盘，exit=entry后第3个交易日收盘=cal[di+4]
    x_day_open = cal[di + 4] if di + 4 < len(cal) else None
    for code, i in by_date[day][:10]:
        d = stocks[code]
        didx = {dt: j for j, dt in enumerate(d["date"])}
        # close-entry
        i_c, i_xc = didx.get(day), didx.get(x_day)
        if i_c is not None and i_xc is not None and d["c"][i_c] > 0:
            res["close"].append(d["c"][i_xc] / d["c"][i_c] - 1 - FEE)
        # open-entry
        i_e = didx.get(e_day)
        i_xo = didx.get(x_day_open) if x_day_open else None
        if i_e is not None and i_xo is not None and d["o"][i_e] > 0:
            res["open"].append(d["c"][i_xo] / d["o"][i_e] - 1 - FEE)


def agg(rs):
    if not rs:
        return "n=0"
    wr = sum(1 for r in rs if r > 0) / len(rs)
    return f"n={len(rs)} 胜率{wr * 100:.0f}% 均值{sum(rs) / len(rs) * 100:+.2f}%"


print(f"巨簇日 {mega_days} 天（2019至今全史）")
print(f"当日尾盘接: {agg(res['close'])}")
print(f"次日开盘接: {agg(res['open'])}")

json.dump({"win": [win[0], win[-1]], "top_ind": ind_big.most_common(12),
           "recurring": [{**s, "code": c} for c, s in rec],
           "mega_close_vs_open": {k: {"n": len(v),
                                      "mean": sum(v) / len(v) if v else None,
                                      "wr": sum(1 for r in v if r > 0) / len(v) if v else None}
                                  for k, v in res.items()}},
          open(f"{ROOT}/data/recurring_winners_20260921.json", "w"), ensure_ascii=False, indent=1)
print("\n落盘 data/recurring_winners_20260921.json")
