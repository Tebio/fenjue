#!/usr/bin/env python3
"""engine/banlu_backtest.py — 半路板回测（2026-09-13，自选冲刺：fill 死后的活路）

逻辑：打板排队的死法是"封死买不进/开缝是坑"。半路板=冲到 +6% 就市价买（秒成交），
博它封板后的隔夜溢价；封不上=冲板失败次日开盘走。

口径（防混复权坑）：入场/出场全程用 m60 不复权价（前收=前一交易日 15:00 bar 收盘），
历史背景（60日无板/梯队/市值带/池籍）用 kcache 比率（比率复权安全）。
变体：B2 全量（量比≥2）/ B1 观察池籍 / B3 当日板块梯队≥2 / RND 随机对照。
出场：封板→断板即跑（次日未板→尾盘卖；再板→隔夜次早卖）；未封→次日开盘卖。
净 -0.15%/边。T+1 合规（买入日不卖）。
"""
import json, glob, sys
from collections import defaultdict

ROOT = "/opt/data/fenjue"
D = ROOT + "/data"
START = "2024-08-26"
FEE = 0.0015
TRIG = 1.06   # +6% 触发
SEAL = 1.098  # 封板判定

# kcache 背景层
stocks_k = {}
for f in glob.glob(f"{D}/big_kcache/*.json"):
    stocks_k[f.split("/")[-1][:6]] = json.load(open(f))
names = {c: v.get("name", "") for c, v in json.load(open(f"{D}/industry_map.json")).items()}
ind_map = json.load(open(f"{D}/industry_map.json"))
cal = [k["date"] for k in stocks_k["000001"]]
dates = [d for d in cal if d >= START]
idx_k = {c: {k["date"]: j for j, k in enumerate(ks)} for c, ks in stocks_k.items()}

# 每日梯队（kcache 比率，复权安全）
ladder = {}
for d in dates:
    lad = defaultdict(int)
    for c, ks in stocks_k.items():
        j = idx_k[c].get(d)
        if j and j >= 1 and ks[j-1]["close"] > 0 and ks[j]["close"]/ks[j-1]["close"]-1 >= 0.098:
            lad[ind_map.get(c, {}).get("industry") or "?"] += 1
    ladder[d] = lad

# 池籍：前15日内触发过 B 变体池信号（量比≥3、涨幅1~7.5%、未板、复牌守卫、额≥2亿）
import datetime as dtmod
def in_pool(ks, j):
    for k in range(max(6, j-15), j):
        if ks[k-1]["close"] <= 0:
            continue
        try:
            d0 = dtmod.date.fromisoformat(ks[k-5]["date"]); d1 = dtmod.date.fromisoformat(ks[k]["date"])
        except Exception:
            continue
        if (d1-d0).days > 12 or any(ks[x]["volume"] <= 0 for x in range(k-5, k)):
            continue
        pj = (ks[k]["close"]/ks[k-1]["close"]-1)*100
        if not (1.0 <= pj <= 7.5):
            continue
        base = [ks[x]["volume"] for x in range(k-5, k)]
        mb = sum(base)/len(base)
        if mb <= 0 or ks[k]["volume"]/mb < 3.0:
            continue
        if ks[k]["volume"]*ks[k]["close"] < 2e8:
            continue
        return True
    return False

# m60 主层
res = {"B2_全量": {"sealed": [], "failed": []}, "B1_池籍": {"sealed": [], "failed": []},
       "B3_梯队": {"sealed": [], "failed": []},
       "B4_梯队+首板+市值带": {"sealed": [], "failed": []},
       "B5_B4+反人群期": {"sealed": [], "failed": []},
       "B6_B4+早盘触发": {"sealed": [], "failed": []}}
trigger_days = 0
b5_trades = []
sys.path.insert(0, ROOT + "/engine")
import claims_shadow as cs
caps = cs.stock_caps()
timeline = {r["date"]: r["regime"] for r in json.load(open(f"{D}/regime_timeline_hcap.json"))}

def first_board60(ks, j):
    return all(ks[x-1]["close"] <= 0 or ks[x]["close"]/ks[x-1]["close"]-1 < 0.098
               for x in range(max(1, j-60), j))
files = glob.glob(f"{D}/m60_cache/*.json")
for fi, f in enumerate(files):
    c = f.split("/")[-1][:6]
    if c not in stocks_k or "ST" in names.get(c, "") or "退" in names.get(c, ""):
        continue
    rows = json.load(open(f))
    byday = defaultdict(list)
    for r in rows:
        byday[r["day"][:10]].append(r)
    days_have = sorted(d for d in byday if d >= START)
    for di, d in enumerate(days_have[:-1]):
        prev_d = days_have[di - 1] if di >= 1 else None
        if prev_d is None:
            continue
        pc = float(byday[prev_d][-1]["close"])   # 前收（不复权自洽）
        if pc <= 0:
            continue
        bars = byday[d]
        vol_today = sum(float(b["volume"]) for b in bars)
        # 前5日 m60 均量（量比用，自洽）
        vol5 = sum(sum(float(b["volume"]) for b in byday[pd]) for pd in days_have[max(0, di-5):di]) / 5 if di >= 5 else 0
        if vol5 <= 0 or vol_today < 2 * vol5:
            continue  # 量比≥2 过滤
        # 触发：首根 high≥+6% 的 bar，买入价=max(触发价, bar开盘)
        entry = None
        entry_bar_idx = None
        for bi, b in enumerate(bars):
            if float(b["high"]) >= pc * TRIG:
                entry = max(pc * TRIG, float(b["open"]))
                entry_bar_idx = bi
                break
        if entry is None:
            continue
        trigger_days += 1
        sealed = float(bars[-1]["close"]) >= pc * SEAL
        # 次日（d+1）出场
        nb = byday[days_have[di + 1]]
        nclose = float(nb[-1]["close"])
        nopen = float(nb[0]["open"])
        if sealed:
            nsealed = nclose >= pc * 1.1 * SEAL  # 次日相对今日收（约）
            nsealed = nclose >= float(bars[-1]["close"]) * SEAL  # 次日再板判定=次日收/今日收
            if nsealed:
                # 隔夜，d+2 开盘卖
                if di + 2 < len(days_have):
                    px_out = float(byday[days_have[di + 2]][0]["open"])
                else:
                    px_out = nclose
            else:
                px_out = nclose   # 断板→次日尾盘
        else:
            px_out = nopen        # 未封→次日开盘
        if px_out <= 0:
            continue
        ret = px_out / entry - 1 - 2 * FEE
        key = "sealed" if sealed else "failed"
        res["B2_全量"][key].append(ret)
        # B2 按周期拆（B5 的反人群 lift 对照）
        res.setdefault(f"B2_reg_{timeline.get(d,'?')}", {"sealed": [], "failed": []})[key].append(ret)
        jk = idx_k[c].get(d)
        if jk is not None:
            industry = ind_map.get(c, {}).get("industry") or "?"
            if in_pool(stocks_k[c], jk):
                res["B1_池籍"][key].append(ret)
            if ladder[d].get(industry, 0) >= 2:
                res["B3_梯队"][key].append(ret)
                # B4-B6 精细层
                cap = caps.get(c, {}).get(d[:7])
                if first_board60(stocks_k[c], jk) and cap is not None and 20 <= cap <= 400:
                    res["B4_梯队+首板+市值带"][key].append(ret)
                    if timeline.get(d) in ("平淡期", "恐慌期"):
                        res["B5_B4+反人群期"][key].append(ret)
                        b5_trades.append({"date": d, "code": c, "entry": round(entry, 2),
                                          "exit": round(px_out, 2), "ret": round(ret, 5), "sealed": sealed})
                    if entry_bar_idx is not None and entry_bar_idx <= 1:  # 10:30/11:30 上午触发
                        res["B6_B4+早盘触发"][key].append(ret)
    if fi % 500 == 0:
        print(f"{fi}/{len(files)}", file=sys.stderr)

def stats(v):
    if not v:
        return {"n": 0}
    return {"n": len(v), "avg%": round(sum(v)/len(v)*100, 2),
            "win%": round(sum(1 for x in v if x > 0)/len(v)*100, 1)}

out = {"trigger_days": trigger_days}
for variant, groups in res.items():
    all_r = groups["sealed"] + groups["failed"]
    seal_rate = len(groups["sealed"]) / len(all_r) * 100 if all_r else 0
    out[variant] = {"全体": stats(all_r), "封板成功": stats(groups["sealed"]),
                    "冲板失败": stats(groups["failed"]), "封板率%": round(seal_rate, 1)}
json.dump(out, open(f"{D}/banlu_backtest_20260913.json", "w"), ensure_ascii=False, indent=1)
with open(f"{D}/banlu_b5_trades.jsonl", "w") as f:
    for t in b5_trades:
        f.write(json.dumps(t, ensure_ascii=False) + "\n")
print(json.dumps(out, ensure_ascii=False, indent=1))
