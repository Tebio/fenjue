```python
#!/usr/bin/env python3
"""engine/unadj_kcache_pull.py — 不复权日K拉取（任务E1，2026-09-13）

【口径】
- 不复权原始成交价：baostock adjustflag="3"，含除权/除息当日价格跳空，
  绝对价位跨分红期可比，专用于做红利策略的「息率分母」。
- 与 data/big_kcache/（前复权，adjustflag="2"）严格区分：前复权序列把历史
  价格按累计分红/送转整体下调，拿它当分母会系统性偏小 → 历史时点息率被高估。

【数据源】
- 宇宙清单：data/dividend_history.json（≥3 个年度有分红）
            + data/industry_map.json（名称含 ST / 退 剔除）
- 行情：baostock query_history_k_data_plus，frequency="d"，adjustflag="3"，
        字段 date,open,high,low,close,volume,amount，区间 2018-01-01 ~ 今日

【输出】
- data/big_kcache_unadj/<code>.json
  schema 同 big_kcache：[{"date","open","high","low","close","volume","amount"}, ...]
- data/unadj_pull_failed.json  失败清单 [{"code","err"}]

【已知限制】
1) baostock 必须单进程串行（并发会被封号），每股 sleep 0.15s；
2) 断点判据「本地最后一行日期 >= 基准最近交易日」，基准默认取
   data/big_kcache/000001.json 的最后一根，可用 --last=YYYY-MM-DD 覆盖；
   基准取不到则退化为今日，会触发全量重拉；
3) 停牌/退市票的区间可能短于 [2018-01-01, 今日]；
4) 不复权价含除权跳空，本缓存只用于息率分母，收益计算仍走前复权；
5) 北交所代码（4/8 开头）用 bj. 前缀，baostock 若不支持会进失败清单。
"""
import os
import sys
import json
import time
import datetime

import baostock as bs

ROOT = "/opt/data/fenjue"
D = ROOT + "/data"
OUTDIR = D + "/big_kcache_unadj"
FAILD = D + "/unadj_pull_failed.json"
START_DATE = "2018-01-01"
SLEEP = 0.15
FIELDS = "date,open,high,low,close,volume,amount"


def y4(dt):
    return dt[:4]


def argv_get(prefix, default=""):
    for a in sys.argv:
        if a.startswith(prefix):
            return a.split("=", 1)[1]
    return default


def ref_last_trade_date():
    x = argv_get("--last=")
    if x:
        return x
    try:
        ks = json.load(open(f"{D}/big_kcache/000001.json"))
        if ks:
            return ks[-1]["date"]
    except Exception:
        pass
    return datetime.date.today().isoformat()


def bs_code(code):
    h = code[0]
    if h == "6":
        return "sh." + code
    if h in ("4", "8"):
        return "bj." + code
    return "sz." + code


def to_f(s):
    try:
        return float(s)
    except Exception:
        return None


def f0(s):
    v = to_f(s)
    return 0.0 if v is None else v


def pull(code, end_date):
    rs = bs.query_history_k_data_plus(
        bs_code(code), FIELDS,
        start_date=START_DATE, end_date=end_date,
        frequency="d", adjustflag="3")
    if rs.error_code != "0":
        raise RuntimeError("query_err %s %s" % (rs.error_code, rs.error_msg))
    bars = []
    while rs.next():
        r = rs.get_row_data()
        if len(r) < 7 or not r[0]:
            continue
        close = to_f(r[4])
        if close is None:
            continue
        bars.append({
            "date": r[0],
            "open": f0(r[1]),
            "high": f0(r[2]),
            "low": f0(r[3]),
            "close": close,
            "volume": f0(r[5]),
            "amount": f0(r[6]),
        })
    return bars


def build_universe():
    names = {c: v.get("name", "") for c, v in json.load(open(f"{D}/industry_map.json")).items()}
    divh = json.load(open(f"{D}/dividend_history.json"))
    uni = []
    for c, recs in divh.items():
        nm = names.get(c, "")
        if "ST" in nm or "退" in nm:
            continue
        try:
            if len({y4(dt) for dt, _ in recs}) >= 3:
                uni.append(c)
        except Exception:
            continue
    uni.sort()
    return uni


def main():
    os.makedirs(OUTDIR, exist_ok=True)
    uni = build_universe()
    ref = ref_last_trade_date()
    end_date = datetime.date.today().isoformat()
    print("宇宙: %d 只  断点基准=%s  请求区间=%s~%s" % (len(uni), ref, START_DATE, end_date),
          file=sys.stderr)

    lg = bs.login()
    if lg.error_code != "0":
        print("baostock login 失败: %s %s" % (lg.error_code, lg.error_msg), file=sys.stderr)
        sys.exit(1)

    ok = skip = fail = 0
    failed = []
    try:
        for i, code in enumerate(uni, 1):
            path = os.path.join(OUTDIR, code + ".json")
            if os.path.exists(path):
                try:
                    ks = json.load(open(path))
                    if ks and ks[-1].get("date", "") >= ref:
                        skip += 1
                        continue
                except Exception:
                    pass
            try:
                bars = pull(code, end_date)
                if not bars:
                    raise RuntimeError("empty_result")
                with open(path, "w") as f:
                    json.dump(bars, f, ensure_ascii=False, separators=(",", ":"))
                ok += 1
            except Exception as e:
                fail += 1
                failed.append({"code": code, "err": str(e)[:200]})
            time.sleep(SLEEP)
            if i % 200 == 0:
                print("[%d/%d] ok=%d skip=%d fail=%d" % (i, len(uni), ok, skip, fail),
                      file=sys.stderr)
    finally:
        bs.logout()

    with open(FAILD, "w") as f:
        json.dump(failed, f, ensure_ascii=False, indent=1)

    print("成功=%d 跳过=%d 失败=%d 宇宙=%d" % (ok, skip, fail, len(uni)))
    if failed:
        print("失败样例:", [x["code"] for x in failed[:10]], file=sys.stderr)


if __name__ == "__main__":
    main()
```

```python
#!/usr/bin/env python3
"""engine/dividend_sim_unadj.py — 红利模拟器「不复权息率分母」重测（任务E2，2026-09-13）

【两套口径的已知差异方向】
- 前复权口径（对照组，等价于 engine/dividend_sim.py）：
      息率 = TTM分红 / big_kcache 前复权收盘价
  前复权把历史价格按累计分红/送转整体下调 → 历史分母偏小 → 历史时点息率被
  系统性【高估】 → 早年（2019~2021）的 4.5% 买入信号偏多，结论偏乐观。
- 不复权口径（本轮主测）：
      息率 = TTM分红 / big_kcache_unadj 不复权真实收盘价
  绝对价位跨分红期可比，历史时点息率还原真实 → 预期买入信号减少、
  交易笔数下降、早年入场变少；return%/maxDD% 随之变化。
- 两套口径的【收益】都仍用前复权价计算（big_kcache，近似含分红总回报），
  保证差异只来自「信号分母」这一个变量，不做双重改动。

【规则】4.5% 买 / 3.5% 卖 / 1/5 仓 × 最多 5 仓 / 1 天最多开 1 仓 / 费 0.0015 每边
       窗口 2019-01-03 起（沿用 --start=）
【宇宙】dividend_history.json 中 ≥3 个年度有分红 + 非 ST/退 + 存在于 big_kcache
       不复权模式下，缺 big_kcache_unadj 缓存的票算不出息率 → 自动跳过并计数

【数据源】
- data/big_kcache/<code>.json          前复权日K（收益口径 + 对照分母）
- data/big_kcache_unadj/<code>.json    不复权日K（主测息率分母）
- data/dividend_history.json           分红明细 [date, amount]
- data/industry_map.json               名称（ST/退 过滤）
- data/big_kcache/000001.json          交易日历基准

【输出】
- data/dividend_sim_unadj_20260913.json   主结果 + 对照表 + 信号触发差异
- data/dividend_curve_unadj_20260913.json 不复权口径净值曲线
- data/红利优化_不复权口径交易明细.csv      不复权口径交易明细

【硬断言】每笔交易 卖出日 > 买入日（T+1 物理合规）。
【已知限制】
1) 不复权价含除权跳空；若在除权日触发卖出，跳空损失已体现在前复权收益里，口径自洽；
2) 价>2 的流动性门槛沿用前复权价判定，刻意保持与对照组单变量可比，
   会漏掉「前复权价<2 但不复权真实价>2」的老票；
3) TTM 分红窗口按自然年同日近似（沿用原脚本），非严格 365 天；
4) 尾部未平仓仓位按最后一日收盘估值，未扣卖出费。
"""
import json
import glob
import sys
import csv
import bisect
from collections import defaultdict

ROOT = "/opt/data/fenjue"
D = ROOT + "/data"
START = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--start=")), "2019-01-03")
OUTSUF = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--out=")), "20260913")
FEE = 0.0015
CAPITAL = 100000.0
BUY_Y, SELL_Y = 0.045, 0.035
MAXPOS = 5


def y4(dt):
    return dt[:4]


def jload(p):
    with open(p) as f:
        return json.load(f)


# ---------- 载入 ----------
stocks = {}
for f in sorted(glob.glob(f"{D}/big_kcache/*.json")):
    stocks[f.split("/")[-1][:6]] = jload(f)

unadj = {}
for f in sorted(glob.glob(f"{D}/big_kcache_unadj/*.json")):
    unadj[f.split("/")[-1][:6]] = jload(f)

if "000001" not in stocks:
    sys.exit("缺少 data/big_kcache/000001.json（交易日历基准）")
if not unadj:
    print("警告: data/big_kcache_unadj 为空或不存在，请先跑 engine/unadj_kcache_pull.py",
          file=sys.stderr)

names = {c: v.get("name", "") for c, v in jload(f"{D}/industry_map.json").items()}
divh = jload(f"{D}/dividend_history.json")

cal = [k["date"] for k in stocks["000001"]]
dates = [d for d in cal if d >= START]
dnum = {d: i for i, d in enumerate(dates)}
idx = {c: {k["date"]: j for j, k in enumerate(ks)} for c, ks in stocks.items()}

# 不复权收盘，按 stocks[c] 的 bar 顺序对齐成 list（省内存，j 索引通用）
uclose = {}
for c, ks in stocks.items():
    src = unadj.get(c)
    if not src:
        continue
    m = {k["date"]: k["close"] for k in src}
    uclose[c] = [m.get(k["date"]) for k in ks]

# ---------- 宇宙 ----------
universe = []
unadj_missing = []
for c, recs in divh.items():
    if c not in stocks:
        continue
    nm = names.get(c, "")
    if "ST" in nm or "退" in nm:
        continue
    if len({y4(dt) for dt, _ in recs}) < 3:
        continue
    universe.append(c)
    if c not in uclose:
        unadj_missing.append(c)
universe.sort()
print("宇宙: %d 只（≥3年度分红，其中 %d 只缺不复权缓存）"
      % (len(universe), len(unadj_missing)), file=sys.stderr)

# ---------- TTM 分红（两套口径共用） ----------
ttm = {}
for c in universe:
    recs = sorted(divh[c])
    dts = [d for d, _ in recs]
    cum = [0.0]
    for _, dp in recs:
        cum.append(cum[-1] + dp)
    arr = []
    for k in stocks[c]:
        d = k["date"]
        lo = bisect.bisect_right(dts, d)
        prev_same = str(int(d[:4]) - 1) + d[4:]
        hi = bisect.bisect_right(dts, prev_same)
        arr.append(cum[lo] - cum[hi])
    ttm[c] = arr


# ---------- 模拟 ----------
def simulate(use_unadj):
    """use_unadj=True: 息率分母用不复权价；False: 用前复权价（对照组）。"""
    eq = CAPITAL
    pos = []
    trades = []
    curve = []
    buys = 0
    for d in dates:
        di = dnum[d]
        # ---- 卖出检查 ----
        for p in list(pos):
            c = p["code"]
            ks = stocks[c]
            j = idx[c].get(d)
            if j is None:
                continue
            if use_unadj:
                ua = uclose.get(c)
                den = ua[j] if (ua is not None and j < len(ua)) else None
            else:
                den = ks[j]["close"]
            if den is None:
                continue
            y = ttm[c][j] / den if den > 0 else 0.0
            if y < SELL_Y and di + 1 < len(dates):
                nd = dates[di + 1]
                nj = idx[c].get(nd)
                if nj is not None and ks[nj]["open"] > 0:
                    assert nd > p["entry_date"], "T+1 违规: %s %s->%s" % (c, p["entry_date"], nd)
                    ret = ks[nj]["open"] / p["entry"] - 1 - FEE
                    eq += p["cash"] * (1 + ret)
                    trades.append({"code": c, "in": p["entry_date"], "out": nd,
                                   "ret": ret, "reason": "息率跌破3.5%"})
                    pos.remove(p)
        # ---- 买入检查 ----
        if len(pos) < MAXPOS and di + 1 < len(dates):
            held = {p["code"] for p in pos}
            best = None
            for c in universe:
                if c in held:
                    continue
                j = idx[c].get(d)
                if j is None or j < 1 or stocks[c][j]["close"] <= 2:
                    continue
                if use_unadj:
                    ua = uclose.get(c)
                    den = ua[j] if (ua is not None and j < len(ua)) else None
                else:
                    den = stocks[c][j]["close"]
                if den is None or den <= 0:
                    continue
                y = ttm[c][j] / den
                if y >= BUY_Y and (best is None or y > best[0]):
                    best = (y, c)
            if best is not None:
                nd = dates[di + 1]
                nj = idx[best[1]].get(nd)
                if nj is not None and stocks[best[1]][nj]["open"] > 0:
                    cash = eq / 5
                    eq -= cash
                    pos.append({"code": best[1], "entry": stocks[best[1]][nj]["open"],
                                "cash": cash, "entry_date": nd})
                    buys += 1
        # ---- 记账 ----
        mv = 0.0
        for p in pos:
            j = idx[p["code"]].get(d)
            mv += p["cash"] * (stocks[p["code"]][j]["close"] / p["entry"] if j else 1)
        curve.append((d, eq + mv))

    for t in trades:
        assert t["out"] > t["in"], "T+1 违规: %s %s->%s" % (t["code"], t["in"], t["out"])
    return curve, trades, buys


def summarize(curve, trades, buys):
    final = curve[-1][1]
    peak, mdd = CAPITAL, 0.0
    for _, v in curve:
        if v > peak:
            peak = v
        if v / peak - 1 < mdd:
            mdd = v / peak - 1
    by_year = defaultdict(float)
    for d, v in curve:
        by_year[d[:4]] = v
    years = {}
    prev = CAPITAL
    for y in sorted(by_year):
        years[y] = round((by_year[y] / prev - 1) * 100, 1)
        prev = by_year[y]
    wins = [t for t in trades if t["ret"] > 0]
    return {
        "window": [curve[0][0], curve[-1][0]],
        "equity": round(final),
        "return%": round((final / CAPITAL - 1) * 100, 1),
        "maxDD%": round(mdd * 100, 1),
        "trades": len(trades),
        "win%": round(len(wins) / len(trades) * 100, 1) if trades else 0,
        "by_year": years,
        "universe": len(universe),
        "buy_signals": buys,
    }


cu_a, tr_a, bu_a = simulate(False)   # 前复权口径（对照）
cu_u, tr_u, bu_u = simulate(True)    # 不复权口径（主测）
sa = summarize(cu_a, tr_a, bu_a)
su = summarize(cu_u, tr_u, bu_u)

out = {
    "note": "不复权息率分母重测；两套口径收益均用前复权价（含分红近似总回报），差异只来自信号分母",
    "window": sa["window"],
    "fee_one_side": FEE,
    "buy_thresh": BUY_Y,
    "sell_thresh": SELL_Y,
    "unadj": su,
    "adj": sa,
    "signal_diff": {
        "unadj_buys": bu_u,
        "adj_buys": bu_a,
        "delta": bu_u - bu_a,
        "unadj_trades": su["trades"],
        "adj_trades": sa["trades"],
    },
    "unadj_missing": len(unadj_missing),
    "unadj_missing_sample": unadj_missing[:30],
}
with open(f"{D}/dividend_sim_unadj_{OUTSUF}.json", "w") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
with open(f"{D}/dividend_curve_unadj_{OUTSUF}.json", "w") as f:
    json.dump(cu_u, f)
with open(f"{D}/红利优化_不复权口径交易明细.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["代码", "名称", "买入日", "卖出日", "收益%", "卖出原因"])
    for t in tr_u:
        w.writerow([t["code"], names.get(t["code"], t["code"]), t["in"], t["out"],
                    round(t["ret"] * 100, 2), t["reason"]])

print("对照: 前复权 return%%=%s trades=%d buys=%d | 不复权 return%%=%s trades=%d buys=%d"
      % (sa["return%"], sa["trades"], bu_a, su["return%"], su["trades"], bu_u), file=sys.stderr)
print(json.dumps(out, ensure_ascii=False, indent=1))
```