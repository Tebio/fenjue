"""深档低位升级口径预跑（c 方案证据包，2026-09-22 夜班）。

今早裁决候选：推送口径从「裸 跌停×MA60下」升级为「深跌确认件」（距MA60≤-25%）。
本脚本把升级后口径按生产推送格式重算全史：生产镜像宇宙（现存主板剔ST/退），
信号= pct≤-9.5% 且 c<ma60 且 c≤ma60×0.75（深跌件），闸门=成簇≥5（同口径同信号日计数）。
输出：T+1/3/5/10/20 衰减、逐年、regime、vs 裸口径对照（读昨晚审计 JSON）。
另附「如果过去一年按升级口径推」的近一年实测（裁决最关心的）。
"""
import collections, json, math, statistics as st, sys
sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

ROOT = "/opt/data/fenjue"
FEE = 0.0015
HZ = [1, 3, 5, 10, 20]

names = {str(s["code"]).zfill(6): s.get("name", "")
         for s in json.loads(open(f"{ROOT}/data/main_board_codes.json").read())["stocks"]}
tl = json.loads(open(f"{ROOT}/data/regime_timeline_hcap.json").read())
REGIME = {t["date"]: t["regime"] for t in tl}

stocks = lp.load_universe()
print(f"universe {len(stocks)}", flush=True)

cluster = collections.Counter()
raw = []
for code, d in stocks.items():
    if code[:2] not in ("60", "00") or code not in names:
        continue
    nm = names.get(code, "")
    if "ST" in nm or "退" in nm:
        continue
    for i in range(60, d["n"] - 1):
        ma = d["ma60"][i]
        if ma is None or ma <= 0 or d["c"][i - 1] <= 0:
            continue
        if d["c"][i] / d["c"][i - 1] - 1 <= -0.095 and d["c"][i] <= ma * 0.75:
            cluster[d["date"][i]] += 1
            raw.append((code, i, d["date"][i]))

recs = []
for code, i, dt in raw:
    d = stocks[code]
    if i + 1 >= d["n"]:
        continue
    e = d["o"][i + 1]
    if e <= 0:
        continue
    r = {"date": dt, "year": dt[:4], "regime": REGIME.get(dt, "?"), "cluster": cluster[dt]}
    for h in HZ:
        j = i + h
        r[h] = (d["c"][j] / e - 1 - FEE) if j < d["n"] else None
    recs.append(r)
print(f"深跌件事件 {len(recs)}（成簇日 {sum(1 for r in recs if r['cluster']>=5)}）", flush=True)


def blk(rows):
    if not rows:
        return {"n": 0}
    o = {"n": len(rows)}
    for h in HZ:
        xs = [r[h] for r in rows if r.get(h) is not None]
        if xs:
            m = st.mean(xs)
            sd = st.stdev(xs) if len(xs) > 1 else 0
            o[f"T+{h}"] = {"wr": round(sum(1 for x in xs if x > 0) / len(xs), 4),
                           "mean": round(m, 5),
                           "t": round(m / (sd / math.sqrt(len(xs))), 1) if sd else None, "n": len(xs)}
    return o


def bucket(rows, key):
    g = collections.defaultdict(list)
    for r in rows:
        g[key(r)].append(r)
    return {k: blk(v) for k, v in sorted(g.items())}


result = {
    "口径": "pct<=-9.5% 且 c<=ma60*0.75（深跌确认件），入场次日开盘，净-0.15%，现存主板剔ST/退",
    "全史": blk(recs),
    "成簇日≥5": blk([r for r in recs if r["cluster"] >= 5]),
    "零星日": blk([r for r in recs if r["cluster"] < 5]),
    "逐年": bucket(recs, lambda r: r["year"]),
    "regime": bucket(recs, lambda r: r["regime"]),
    "近一年(2025-09后)": blk([r for r in recs if r["date"] >= "2025-09-01"]),
    "2026": blk([r for r in recs if r["year"] == "2026"]),
}
json.dump(result, open(f"{ROOT}/data/deep_low_upgraded_20260922.json", "w"), ensure_ascii=False, indent=1)

print("\n═══ 升级口径（深跌件 c≤ma60×0.75）═══")
for k in ("全史", "成簇日≥5", "零星日", "近一年(2025-09后)", "2026"):
    b = result[k]
    t1, t5 = b.get("T+1", {}), b.get("T+5", {})
    print(f"  {k:<14} n={b['n']:>5}  T+1 {t1.get('wr',0)*100:.1f}%/{t1.get('mean',0)*100:+.2f}%  T+5 {t5.get('wr',0)*100:.1f}%/{t5.get('mean',0)*100:+.2f}% t={t5.get('t')}")
print("\n逐年 T+5:", {y: f"{b['T+5']['wr']*100:.0f}%/{b['T+5']['mean']*100:+.2f}%"
                 for y, b in result["逐年"].items() if "T+5" in b})
print("regime T+5:", {g: f"{b['T+5']['wr']*100:.0f}%/{b['T+5']['mean']*100:+.2f}%(n={b['n']})"
                  for g, b in result["regime"].items() if "T+5" in b})
print("\nsaved data/deep_low_upgraded_20260922.json")
