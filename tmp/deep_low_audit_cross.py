"""深档低位终审补刀：regime×成簇 交叉格 + 2026 成簇日细节（复用同一口径重算）。"""
import collections, glob, json, math, statistics, sys
sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

ROOT = "/opt/data/fenjue"
FEE = 0.0015
names = {str(s["code"]).zfill(6): s.get("name", "")
         for s in json.loads(open(f"{ROOT}/data/main_board_codes.json").read())["stocks"]}
tl = json.loads(open(f"{ROOT}/data/regime_timeline_hcap.json").read())
REGIME = {t["date"]: t["regime"] for t in tl}

def blk(rs):
    if not rs: return {"n": 0}
    o = {"n": len(rs)}
    for h in (1, 5):
        xs = [r[h] for r in rs if r.get(h) is not None]
        if xs:
            o[f"T+{h}"] = {"wr": round(sum(1 for x in xs if x > 0) / len(xs), 4),
                           "mean": round(statistics.mean(xs), 5)}
    return o

stocks = lp.load_universe()
cluster = collections.Counter()
events = []
for code, d in stocks.items():
    if code[:2] not in ("60", "00") or code not in names:
        continue
    nm = names.get(code, "")
    if "ST" in nm or "退" in nm:
        continue
    for i in range(60, d["n"] - 1):
        ma = d["ma60"][i]
        if ma is None or d["c"][i - 1] <= 0:
            continue
        if d["c"][i] / d["c"][i - 1] - 1 <= -0.095 and d["c"][i] < ma:
            cluster[d["date"][i]] += 1
            events.append((code, i, d["date"][i]))

recs = []
for code, i, date in events:
    d = stocks[code]
    if i + 1 >= d["n"]: continue
    e = d["o"][i + 1]
    if e <= 0: continue
    rec = {"date": date, "regime": REGIME.get(date, "?"), "cluster": cluster[date],
           "year": date[:4]}
    for h in (1, 5):
        j = i + h
        rec[h] = (d["c"][j] / e - 1 - FEE) if j < d["n"] else None
    recs.append(rec)

cross = collections.defaultdict(list)
for r in recs:
    cross[(r["regime"], "成簇" if r["cluster"] >= 5 else "零星")].append(r)

print("═══ regime × 成簇 交叉（生产镜像）═══")
for (g, c), v in sorted(cross.items()):
    b = blk(v)
    t5 = b.get("T+5", {})
    print(f"  {g}×{c}: n={b['n']:>6}  T+1 {b.get('T+1',{}).get('wr',0)*100:.1f}%/{b.get('T+1',{}).get('mean',0)*100:+.2f}%  T+5 {t5.get('wr',0)*100:.1f}%/{t5.get('mean',0)*100:+.2f}%")

print("\n═══ 逐年 × 成簇（T+5）═══")
yb = collections.defaultdict(list)
for r in recs:
    yb[(r["year"], "成簇" if r["cluster"] >= 5 else "零星")].append(r)
for (y, c), v in sorted(yb.items()):
    b = blk(v)
    t5 = b.get("T+5", {})
    print(f"  {y}×{c}: n={b['n']:>5}  {t5.get('wr',0)*100:.1f}%/{t5.get('mean',0)*100:+.2f}%")

json.dump({"cross": {f"{g}|{c}": blk(v) for (g, c), v in cross.items()},
           "year_cluster": {f"{y}|{c}": blk(v) for (y, c), v in yb.items()}},
          open(f"{ROOT}/data/deep_low_audit_cross_20260922.json", "w"), ensure_ascii=False, indent=1)
print("\nsaved data/deep_low_audit_cross_20260922.json")
