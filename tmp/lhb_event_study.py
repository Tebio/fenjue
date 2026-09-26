"""龙虎榜上榜事件研究（2026-09-26 深夜，用户「研究龙虎榜本身」——席位画像#40 之外的另一半）。

事件=当日上榜（lhb_all.json 的 stock_items），257 个 HiThink 日。特征：当日涨跌幅/净买入率/
游资净额/上榜理由。前瞻 T+1/5/20（次日开盘入，费0.15%）。
分桶：涨停上榜 vs 跌停上榜 vs 普通；净买入正/负；游资净额正/负；regime。
"""
import glob
import json
import statistics as st
import sys

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

ROOT = "/opt/data/fenjue"
FEE = 0.0015
stocks = lp.load_universe()
regime = lp.load_regime()

events = []
for fp in sorted(glob.glob(f"{ROOT}/data/hithink/*/lhb_all.json")):
    day = fp.split("/")[-2]
    try:
        items = (json.load(open(fp)).get("data") or {}).get("stock_items") or []
    except Exception:
        continue
    for it in items:
        code = str(it.get("ticker") or "").zfill(6)
        if code[:2] not in ("60", "00"):
            continue
        events.append({"date": day, "code": code,
                       "chg": float(it.get("change") or 0),
                       "net_rate": float(it.get("net_rate") or 0),
                       "hot_net": float(it.get("hot_money_net_value") or 0),
                       "range_days": int(it.get("range_days") or 1)})
print(f"上榜事件 {len(events)}（{len(set(e['date'] for e in events))} 天）", flush=True)

recs = []
for e in events:
    d = stocks.get(e["code"])
    if not d or e["date"] not in d["date"]:
        continue
    i = d["date"].index(e["date"])
    if i + 21 >= d["n"] or d["o"][i + 1] <= 0:
        continue
    entry = d["o"][i + 1]
    recs.append({**e, "rg": regime.get(e["date"], "?"),
                 "t1": d["c"][i + 1] / entry - 1 - FEE,
                 "t5": d["c"][i + 5] / entry - 1 - FEE,
                 "t20": d["c"][i + 20] / entry - 1 - FEE})
print(f"可计算 {len(recs)}")


def blk(rows, lb):
    if len(rows) < 25:
        print(f"  {lb}: n={len(rows)} 不足")
        return
    line = f"  {lb:<20} n={len(rows):>5}"
    for h in ("t1", "t5", "t20"):
        xs = [r[h] for r in rows]
        wr = sum(1 for x in xs if x > 0) / len(xs)
        line += f" | {h.upper()} {wr * 100:4.0f}%/{st.mean(xs) * 100:+5.2f}%"
    print(line)


print("\n═══ 上榜日类型 ═══")
blk(recs, "全部上榜")
blk([r for r in recs if r["chg"] >= 0.098], "涨停上榜")
blk([r for r in recs if r["chg"] <= -0.098], "跌停上榜")
blk([r for r in recs if abs(r["chg"]) < 0.098], "普通上榜")
print("\n═══ 净买入方向 ═══")
blk([r for r in recs if r["net_rate"] > 0], "席位净买入>0")
blk([r for r in recs if r["net_rate"] < 0], "席位净卖出")
blk([r for r in recs if r["hot_net"] > 0], "游资净买入>0")
blk([r for r in recs if r["hot_net"] < 0], "游资净卖出")
print("\n═══ 交叉：涨停上榜×游资方向 ═══")
blk([r for r in recs if r["chg"] >= 0.098 and r["hot_net"] > 0], "涨停+游资净买")
blk([r for r in recs if r["chg"] >= 0.098 and r["hot_net"] < 0], "涨停+游资净卖(派发?)")
blk([r for r in recs if r["chg"] <= -0.098 and r["hot_net"] > 0], "跌停+游资净买(抄底)")
print("\n═══ 连板高度（range_days） ═══")
for lo, hi, lb in ((1, 2, "1天"), (2, 3, "2天"), (3, 99, "≥3天")):
    blk([r for r in recs if lo <= r["range_days"] < hi], f"连板{lb}")
print("\n═══ regime ═══")
for g in ("恐慌期", "平淡期", "妖股期", "主线期"):
    blk([r for r in recs if r["rg"] == g], g)
print("\n═══ 恐慌期×跌停上榜（恐慌抄底资金榜） ═══")
blk([r for r in recs if r["rg"] == "恐慌期" and r["chg"] <= -0.098], "恐慌期跌停上榜")
blk([r for r in recs if r["rg"] == "恐慌期" and r["chg"] <= -0.098 and r["hot_net"] > 0], "恐慌期跌停+游资净买")
json.dump(recs, open(f"{ROOT}/data/lhb_event_study_20260926.json", "w"), ensure_ascii=False)
print("\nsaved")
