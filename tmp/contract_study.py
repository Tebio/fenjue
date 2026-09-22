"""合同公告事件研究·分析端（2026-09-22）：读 contract_events_raw，算前瞻收益。

口径：事件日=公告日（NOTICE_DATE），若为非交易日则顺延到下一交易日（公告多盘后）；
入场=事件对齐日次日开盘；T+1/5/10/20 收盘出；费 0.15%；含退市股。
对照：同股 MA60 同位置随机日（2 万样本）。
分层：标题类型（中标/合同/订单/签约）×regime×市值五分位×位置。
预登记活格：n≥300 且 t≥3 且双段同正 且 位置匹配边际>0。
"""
import collections
import json
import math
import random
import statistics as st
import sys

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

ROOT = "/opt/data/fenjue"
FEE = 0.0015

events = json.loads(open(f"{ROOT}/data/contract_events_raw_20260922.json").read())
stocks = lp.load_universe()
regime = lp.load_regime()
print(f"事件 {len(events)}", flush=True)

idx = json.loads(open(f"{ROOT}/data/index_sh000001.json").read())
cal = [k["date"] for k in idx]
import bisect


def align_day(nd):
    j = bisect.bisect_left(cal, nd)
    return cal[j] if j < len(cal) else None


def kind(title):
    if "中标" in title:
        return "中标"
    if "订单" in title:
        return "订单"
    if "签约" in title:
        return "签约"
    return "合同"


recs = []
for e in events:
    code = e["code"]
    d = stocks.get(code)
    if not d:
        continue
    day = align_day(e["date"])
    if not day:
        continue
    i = d["date"].index(day) if day in d["date"] else None
    if i is None or i < 60 or i + 21 >= d["n"] or d["o"][i + 1] <= 0:
        continue
    entry = d["o"][i + 1]
    rec = {"code": code, "date": day, "kind": kind(e["title"]), "title": e["title"],
           "regime": regime.get(day, "?"), "year": day[:4],
           "seg": "2024-2025" if day < "2026" else "2026",
           "pos": "low" if d["ma60"][i] and d["c"][i] <= d["ma60"][i] else "high"}
    for h in (1, 5, 10, 20):
        rec[h] = d["c"][i + h] / entry - 1 - FEE
    recs.append(rec)
print(f"可计算事件 {len(recs)}", flush=True)


def blk(rows):
    n = len(rows)
    if n < 30:
        return None
    out = {"n": n}
    for h in (1, 5, 10, 20):
        xs = [r[h] for r in rows if r.get(h) is not None]
        if xs:
            m = st.mean(xs)
            sd = st.stdev(xs) if len(xs) > 1 else 0
            out[f"T+{h}"] = {"wr": round(sum(1 for x in xs if x > 0) / len(xs), 3),
                             "mean": round(m * 100, 2),
                             "t": round(m / (sd / math.sqrt(len(xs))), 1) if sd else None}
    return out


out = {"全部": blk(recs)}
print(f"全部: {out['全部']}")
for k in ("中标", "合同", "订单", "签约"):
    b = blk([r for r in recs if r["kind"] == k])
    out[k] = b
    if b and "T+5" in b:
        print(f"{k}: n={b['n']} T+1 {b['T+1']['wr'] * 100:.0f}%/{b['T+1']['mean']:+.2f}% T+5 {b['T+5']['wr'] * 100:.0f}%/{b['T+5']['mean']:+.2f}%(t{b['T+5']['t']}) T+20 {b.get('T+20', {}).get('mean', 0):+.2f}%")

print("\n分段:", {s: blk([r for r in recs if r["seg"] == s]) for s in ("2024-2025", "2026")})
def fmt5(b):
    if b and "T+5" in b:
        return f"{b['T+5']['mean']:+.2f}%(n{b['n']})"
    return "-"


print("regime:", {g: fmt5(blk([r for r in recs if r["regime"] == g])) for g in ("妖股期", "恐慌期", "平淡期", "主线期")})
print("位置:", {p: fmt5(blk([r for r in recs if r["pos"] == p])) for p in ("low", "high")})

json.dump(out, open(f"{ROOT}/data/contract_study_20260922.json", "w"), ensure_ascii=False, indent=1, default=str)
print("saved data/contract_study_20260922.json")
