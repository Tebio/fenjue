#!/usr/bin/env python3
"""engine/banlu_daily.py — B5 半路板每日信号（2026-09-13）

盘后（m60 日更后）计算当日 B5 信号：+6% 触发 + 量比≥2 + 梯队≥2 + 60日首板 + 市值20-400亿
+ regime∈平淡/恐慌期。落盘 data/banlu_signals.jsonl（影子记账源）+ 打印名单（cron 推送用）。
"""
import os
import json, glob, sys
from collections import defaultdict

ROOT = "/opt/data/fenjue"
D = ROOT + "/data"
TRIG, SEAL = 1.06, 1.098
sys.path.insert(0, ROOT + "/engine")
import claims_shadow as cs

stocks = cs.load_stocks()
ind = cs.industry_map()
caps = cs.stock_caps()
cal = [k["date"] for k in stocks["000001"]]
today = cal[-1]
idx = {c: {k["date"]: j for j, k in enumerate(ks)} for c, ks in stocks.items()}
timeline = {r["date"]: r["regime"] for r in json.load(open(f"{D}/regime_timeline_hcap.json"))}
regime = timeline.get(today, "?")

def first_board60(ks, j):
    return all(ks[x-1]["close"] <= 0 or ks[x]["close"]/ks[x-1]["close"]-1 < 0.098
               for x in range(max(1, j-60), j))

lad = defaultdict(int)
for c, ks in stocks.items():
    j = idx[c].get(today)
    if j and j >= 1 and ks[j-1]["close"] > 0 and ks[j]["close"]/ks[j-1]["close"]-1 >= 0.098:
        lad[ind.get(c, {}).get("industry") or "?"] += 1

sigs = []
for f in glob.glob(f"{D}/m60_cache/*.json"):
    c = f.split("/")[-1][:6]
    nm = ind.get(c, {}).get("name", c)
    if "ST" in nm or "退" in nm:
        continue
    rows = json.load(open(f))
    byday = defaultdict(list)
    for r in rows:
        byday[r["day"][:10]].append(r)
    days = sorted(byday)
    if len(days) < 6 or days[-1] != today:
        continue
    pc = float(byday[days[-2]][-1]["close"])
    if pc <= 0:
        continue
    vol5 = sum(sum(float(b["volume"]) for b in byday[pd]) for pd in days[-6:-1]) / 5
    vol_today = sum(float(b["volume"]) for b in byday[today])
    if vol5 <= 0 or vol_today < 2 * vol5:
        continue
    entry = None
    for b in byday[today]:
        if float(b["high"]) >= pc * TRIG:
            entry = max(pc * TRIG, float(b["open"]))
            break
    if entry is None:
        continue
    sealed = float(byday[today][-1]["close"]) >= pc * SEAL
    j = idx[c].get(today)
    if j is None:
        continue
    industry = ind.get(c, {}).get("industry") or "?"
    if lad.get(industry, 0) < 2 or not first_board60(stocks[c], j):
        continue
    cap = caps.get(c, {}).get(today[:7])
    if cap is None or not (20 <= cap <= 400):
        continue
    # 2026-09-18 位置细分（第二轴网格 + submit 双确认）：MA60上 +1.36%/48.7%（过闸门）、
    # MA60下 +0.39%/45.7%（REJECT 挂2/6）→ 只推 MA60 上方，"追强要高位"。
    ks = stocks[c]
    _seg = [ks[x]["close"] for x in range(j - 59, j + 1)] if j >= 59 else []
    m60 = sum(_seg) / 60 if _seg and all(x > 0 for x in _seg) else None
    pos = "MA60下" if (m60 is not None and ks[j]["close"] <= m60) else ("MA60上" if m60 is not None else "?")
    sigs.append({"date": today, "code": c, "name": nm, "industry": industry,
                 "trigger_px": round(entry, 2), "sealed": sealed,
                 "close": stocks[c][j]["close"], "ma60": round(m60, 3) if m60 else None, "pos": pos,
                 "regime_ok": regime in ("平淡期", "恐慌期"), "pos_ok": pos == "MA60上"})

# K3修（2026-09-13 夜）：同日幂等——手工复核+cron双跑会产生重复行，写入前按(date,code)去重
_lp = f"{D}/banlu_signals.jsonl"
_existing = set()
if os.path.exists(_lp):
    for _l in open(_lp):
        _l = _l.strip()
        if _l:
            try:
                _r = json.loads(_l)
                _existing.add((_r.get("date"), _r.get("code")))
            except Exception:
                pass
_new = [s for s in sigs if (s["date"], s["code"]) not in _existing]
with open(_lp, "a") as f:
    for s in _new:
        f.write(json.dumps(s, ensure_ascii=False) + "\n")
if len(_new) < len(sigs):
    print(f"[幂等] 跳过重复登记 {len(sigs) - len(_new)} 条")
ok = [s for s in sigs if s["regime_ok"]]
push = [s for s in ok if s.get("pos_ok")]
print(f"B5 半路板 · {today} · 周期={regime}")
print(f"触发 {len(sigs)} 只，周期合规（平淡/恐慌）{len(ok)} 只，位置合规（MA60上）{len(push)} 只")
for s in push:
    print(f"  {s['name']}({s['code']}) 触发价{s['trigger_px']} {'已封板' if s['sealed'] else '未封'} [{s['industry']}]")
_dropped = [s for s in ok if not s.get("pos_ok")]
if _dropped:
    print(f"（剔除 MA60 下方 {len(_dropped)} 只：submit 实测 +0.39%/45.7% 挂 2/6 闸门，"
          f"跌停接要低位、半路板要高位，别混：{'、'.join(s['name'] for s in _dropped[:8])}）")
