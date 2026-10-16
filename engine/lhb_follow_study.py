#!/usr/bin/env python3
"""engine/lhb_follow_study.py — 龙虎榜席位跟随 edge 事件研究（2026-10-15 过夜卡 t_d353ecc4）

问题：「抄席位」是否有可交易 edge？
  ① 知名游资席位上榜买入后 T+1/5/20 全 horizon 胜率/均值/赔率 vs 位置匹配对照（同票同MA60侧随机日）
  ② 分组：游资 vs 机构专用 vs 沪深股通——谁的 follow 溢价高、衰减多快
  ③ 连板票首板席位→二板席位接力结构与后续走势
  ④ 反向：哪些席位上榜=出货信号（负溢价）

纪律（对齐任务书）：
- 簇剂量分解：LHB 事件天然抱团，同日多数票上榜——按入场日聚合日历时间组合 + NW t，
  并测「当日上榜剂量」(当日席位买入事件数) 与次日表现的关系。
- 六闸门 + G7 容量：最终候选走 law_pipeline.submit_gate（结构限制：样本仅 2025-09-12..2026-10-15
  约 13 个月，G2 双段时间分段结构性不可能全绿——另报窗内中点分段）。
- 位置匹配对照双口径：C1=同票同MA60侧随机日（任务书口径）；
  C2=同票同MA60侧+当日涨幅同桶随机日（剥离「上榜日本身就是大动日」的动量混淆）。
- 覆盖限制（诚实标注）：big_kcache 仅主板（60/000/001/002/003），300/301/688/920/转债不在宇宙内，
  本研究=主板 LHB 子集；HiThink 龙虎榜无沪深股通席位维度，分组②的北向腿缺席（数据边界）。
- 与涨停族/连板族重叠审计：上榜日涨停占比/首板占比/连板占比，声明嵌套/交叉/独立。

产物：data/lhb_follow_study_20261015.json + docs/lhb-follow-20261015.md + AGENTS.md 落账。
"""
import json, math, random, statistics as st, sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

ROOT = Path("/opt/data/fenjue")
HT = ROOT / "data/hithink"
from costs import FLAT_RT  # TAX-01 唯一真源 engine/costs.py（AGENTS #287）
FEE = FLAT_RT
HORIZONS = [1, 3, 5, 10, 20]
MAXH = max(HORIZONS)
MIN_SEAT_N = 60          # 席位进入逐席位排名的最小买入事件数
WIN_START, WIN_END = "2025-09-12", "2026-10-15"
MID = "2026-04-15"       # 窗内中点分段（时效替代检验）
RNG = random.Random(42)


# ---------- 数据采集 ----------

def collect_events():
    """返回 seat_rows / org_rows / all_rows（主板过滤在 forward 阶段做，这里全量保留计数）"""
    seat_rows, org_rows, all_rows = [], [], []
    days = 0
    for ddir in sorted(HT.iterdir()):
        if not (WIN_START <= ddir.name <= WIN_END):
            continue
        days += 1
        fh = ddir / "lhb_hot.json"
        if fh.exists():
            for s in json.loads(fh.read_text())["data"].get("hot_money_items") or []:
                for r in s.get("rows") or []:
                    seat_rows.append({
                        "date": ddir.name, "seat": s["name"], "code": r["ticker"],
                        "name": r.get("name"), "chg": (r.get("change") or 0) * 100,
                        "net_wan": (r.get("hot_money_item_net_value") or 0) / 1e4,
                        "range_days": r.get("range_days") or 1,
                    })
        fo = ddir / "lhb_org.json"
        if fo.exists():
            for r in json.loads(fo.read_text())["data"].get("stock_items") or []:
                org_rows.append({
                    "date": ddir.name, "code": r["ticker"], "name": r.get("name"),
                    "chg": (r.get("change") or 0) * 100,
                    "org_net_wan": (r.get("org_net_value") or 0) / 1e4,
                    "org_buy_num": r.get("org_buy_num"), "org_sell_num": r.get("org_sell_num"),
                })
        fa = ddir / "lhb_all.json"
        if fa.exists():
            for r in json.loads(fa.read_text())["data"].get("stock_items") or []:
                all_rows.append({"date": ddir.name, "code": r["ticker"],
                                 "chg": (r.get("change") or 0) * 100,
                                 "net_wan": (r.get("net_value") or 0) / 1e4})
    return seat_rows, org_rows, all_rows, days


# ---------- 前向收益与对照 ----------

def build_index(stocks):
    return {c: {dt: i for i, dt in enumerate(d["date"])} for c, d in stocks.items()}


def fwd_returns(d, i, fee=FEE):
    """入场=i+1 开盘；r_h = c[i+1+h]/o[i+1]-1-fee。越界=None（截尾，不填充）。"""
    if i + 1 >= d["n"] or d["o"][i + 1] <= 0:
        return None
    e = d["o"][i + 1]
    out = {}
    for h in HORIZONS:
        j = i + 1 + h
        out[h] = (d["c"][j] / e - 1 - fee) if (j < d["n"] and d["c"][j] > 0) else None
    return out


def chg_bucket(d, i):
    """当日涨幅桶：涨停≥9.8 / 大涨3~9.8 / 平-3~3 / 跌<-3（主板10cm口径）"""
    if i < 1 or d["c"][i - 1] <= 0:
        return None
    r = d["c"][i] / d["c"][i - 1] - 1
    return 3 if r >= 0.098 else 2 if r >= 0.03 else 1 if r > -0.03 else 0


def ma60_side(d, i):
    ma = d["ma60"][i]
    if ma is None or ma <= 0:
        return None
    return 1 if d["c"][i] > ma else 0


def build_pools(stocks):
    """对照池：code -> side -> [i]，及 code -> (side,bkt) -> [i]。窗口内、边界留 MAXH+2。"""
    pool1, pool2 = {}, {}
    for code, d in stocks.items():
        n = d["n"]
        for i in range(65, n - MAXH - 2):
            dt = d["date"][i]
            if not (WIN_START <= dt <= WIN_END):
                continue
            if d["o"][i + 1] <= 0 or d["c"][i] <= 0:
                continue
            side = ma60_side(d, i)
            if side is None:
                continue
            pool1.setdefault(code, {}).setdefault(side, []).append(i)
            b = chg_bucket(d, i)
            if b is not None:
                pool2.setdefault(code, {}).setdefault((side, b), []).append(i)
    return pool1, pool2


def matched_ctrl(d, i, pool1, pool2, k=3):
    """返回 (C1收益列表, C2收益列表)：每事件抽 k 个对照日的 fwd 收益。C2 池空则回落 C1。"""
    code = d["code"]
    side = ma60_side(d, i)
    b = chg_bucket(d, i)
    if side is None:
        return None, None
    p1 = [j for j in pool1.get(code, {}).get(side, []) if j != i]
    p2 = [j for j in pool2.get(code, {}).get((side, b), []) if j != i] if b is not None else []
    r1, r2 = [], []
    for j in RNG.sample(p1, min(k, len(p1))):
        fr = fwd_returns(d, j)
        if fr:
            r1.append(fr)
    fallback = 0
    src = p2 if p2 else p1
    if not p2:
        fallback = 1
    for j in RNG.sample(src, min(k, len(src))):
        fr = fwd_returns(d, j)
        if fr:
            r2.append(fr)
    return r1, (r2, fallback)


# ---------- 统计 ----------

def stat(rs):
    rs = [x for x in rs if x is not None]
    if len(rs) < 20:
        return {"n": len(rs)}
    n = len(rs)
    m = st.mean(rs)
    wins = [x for x in rs if x > 0]
    losses = [x for x in rs if x <= 0]
    odds = (st.mean(wins) / abs(st.mean(losses))) if wins and losses and st.mean(losses) != 0 else None
    return {"n": n, "win%": round(100 * len(wins) / n, 1), "mean%": round(100 * m, 2),
            "med%": round(100 * st.median(rs), 2),
            "赔率": round(odds, 2) if odds else None,
            "t": round(m / (st.stdev(rs) / math.sqrt(n)), 1) if n > 1 else None}


def day_cluster_t(events_r_by_date, uni_mean_by_date, h):
    """日历时间组合：事件按入场日聚合，日均超额=当日事件均值-全宇宙均值，NW t。"""
    dates = sorted(d for d in events_r_by_date if d in uni_mean_by_date)
    series = [st.mean(events_r_by_date[d]) - uni_mean_by_date[d] for d in dates]
    if len(series) < 20:
        return {"天数": len(series)}
    return {"天数": len(series), "日均超额%": round(100 * st.mean(series), 3),
            "t_NW": lp.nw_t(series, h),
            "年化Sharpe": round(st.mean(series) / st.stdev(series) * math.sqrt(244), 2)
            if st.stdev(series) > 0 else None}


def universe_daily_mean(stocks):
    """全宇宙每日（入场日口径）同窗口收益均值：date[i+1] -> [r_h]"""
    uni = {h: defaultdict(list) for h in HORIZONS}
    for code, d in stocks.items():
        n = d["n"]
        for i in range(65, n - MAXH - 2):
            fr = fwd_returns(d, i)
            if not fr:
                continue
            ed = d["date"][i + 1]
            for h in HORIZONS:
                if fr[h] is not None:
                    uni[h][ed].append(fr[h])
    return {h: {dt: st.mean(v) for dt, v in uni[h].items()} for h in HORIZONS}


# ---------- 主分析 ----------

def eval_group(name, keys, stocks, idx, pool1, pool2, uni_mean):
    """keys=[(code,date)] 事件集合。返回全 horizon 统计+对照边际+日历时间+中点分段。"""
    ev_r = {h: [] for h in HORIZONS}
    c1_r = {h: [] for h in HORIZONS}
    c2_r = {h: [] for h in HORIZONS}
    by_date = {h: defaultdict(list) for h in HORIZONS}
    segA, segB = {h: [] for h in HORIZONS}, {h: [] for h in HORIZONS}
    fb_cnt, n_ev, n_mapped = 0, 0, 0
    for code, dt in keys:
        d = stocks.get(code)
        if not d:
            continue
        n_ev += 1
        i = idx[code].get(dt)
        if i is None:
            continue
        fr = fwd_returns(d, i)
        if not fr:
            continue
        n_mapped += 1
        r1, r2pack = matched_ctrl(d, i, pool1, pool2)
        r2, fb = r2pack if r2pack else ([], 0)
        fb_cnt += fb
        ed = d["date"][i + 1]
        seg = segA if dt < MID else segB
        for h in HORIZONS:
            if fr[h] is None:
                continue
            ev_r[h].append(fr[h])
            seg[h].append(fr[h])
            by_date[h][ed].append(fr[h])
            if r1:
                c1_r[h].extend(x[h] for x in r1 if x[h] is not None)
            if r2:
                c2_r[h].extend(x[h] for x in r2 if x[h] is not None)
    out = {"事件数_主板映射": n_mapped, "事件数_原始": n_ev, "C2池空回落C1数": fb_cnt,
           "horizons": {}, "calendar": {}, "midpoint_split": {}}
    for h in HORIZONS:
        e, a, b = stat(ev_r[h]), stat(c1_r[h]), stat(c2_r[h])
        marg1 = round(e["mean%"] - a["mean%"], 2) if e.get("mean%") is not None and a.get("mean%") is not None else None
        marg2 = round(e["mean%"] - b["mean%"], 2) if e.get("mean%") is not None and b.get("mean%") is not None else None
        out["horizons"][f"T+{h}"] = {"event": e, "C1_位置匹配": a, "C2_位置涨幅匹配": b,
                                      "marg_C1_pp": marg1, "marg_C2_pp": marg2}
        out["calendar"][f"T+{h}"] = day_cluster_t(by_date[h], uni_mean[h], h)
        sA, sB = stat(segA[h]), stat(segB[h])
        out["midpoint_split"][f"T+{h}"] = {"H1_前半": sA, "H2_后半": sB}
    return out


def main():
    seat_rows, org_rows, all_rows, days = collect_events()
    print(f"LHB天数={days} seat_rows={len(seat_rows)} org_rows={len(org_rows)} all_rows={len(all_rows)}", flush=True)
    stocks = lp.load_universe()
    print("stocks:", len(stocks), flush=True)
    idx = build_index(stocks)
    pool1, pool2 = build_pools(stocks)
    uni_mean = universe_daily_mean(stocks)
    print("pools & universe means ready", flush=True)

    # 覆盖审计
    all_codes = {r["code"] for r in seat_rows} | {r["code"] for r in org_rows}
    missing = sorted(c for c in all_codes if c not in stocks)
    from collections import Counter
    miss_pref = Counter(c[:3] for c in missing)

    out = {"meta": {"window": f"{WIN_START}..{WIN_END}", "lhb_days": days,
                    "built": "2026-10-15", "fee": FEE, "entry": "T+1开盘",
                    "horizons": HORIZONS, "controls": "C1=同票同MA60侧随机日×3; C2=同票同MA60侧同涨幅桶×3(池空回落C1)",
                    "universe": "big_kcache主板", "seed": 42},
           "coverage": {"lhb_codes": len(all_codes), "mapped": len(all_codes) - len(missing),
                        "missing": len(missing), "missing_prefix": miss_pref.most_common(8),
                        "note": "300/301/688/920/转债不在宇宙=创业板/科创板/北交所上榜票全部缺席，本研究=主板子集"}}

    # ---------- 分组事件集 ----------
    seat_buy = [(r["code"], r["date"]) for r in seat_rows if r["net_wan"] > 0]
    seat_sell = [(r["code"], r["date"]) for r in seat_rows if r["net_wan"] < 0]
    org_buy = [(r["code"], r["date"]) for r in org_rows if (r["org_net_wan"] or 0) > 0]
    org_sell = [(r["code"], r["date"]) for r in org_rows if (r["org_net_wan"] or 0) < 0]
    lhb_any = [(r["code"], r["date"]) for r in all_rows]

    groups = {"游资买入_全席位": seat_buy, "游资卖出_全席位": seat_sell,
              "机构净买入": org_buy, "机构净卖出": org_sell, "上榜全样本": lhb_any}
    out["groups"] = {}
    for name, keys in groups.items():
        print(f"=== {name} n={len(keys)} ===", flush=True)
        out["groups"][name] = eval_group(name, keys, stocks, idx, pool1, pool2, uni_mean)
        t5 = out["groups"][name]["horizons"]["T+5"]
        print("  T+5 event:", t5["event"], "margC2:", t5["marg_C2_pp"], flush=True)
    out["groups_note"] = "沪深股通席位：HiThink龙虎榜三榜(lhb_all/hot/org)均无此维度，北向腿数据缺席=功效限制，不编造。"

    # ---------- ① 逐席位排名（买入方向） ----------
    by_seat = defaultdict(list)
    for r in seat_rows:
        if r["net_wan"] > 0 and r["code"] in stocks:
            by_seat[r["seat"]].append(r)
    seats_out = {}
    for seat, rows in sorted(by_seat.items(), key=lambda x: -len(x[1])):
        if len(rows) < MIN_SEAT_N:
            continue
        keys = [(r["code"], r["date"]) for r in rows]
        res = eval_group(seat, keys, stocks, idx, pool1, pool2, uni_mean)
        h = res["horizons"]
        seats_out[seat] = {
            "n_buy": res["事件数_主板映射"],
            "T1": {"mean%": h["T+1"]["event"].get("mean%"), "win%": h["T+1"]["event"].get("win%"),
                   "margC2": h["T+1"]["marg_C2_pp"]},
            "T5": {"mean%": h["T+5"]["event"].get("mean%"), "win%": h["T+5"]["event"].get("win%"),
                   "margC2": h["T+5"]["marg_C2_pp"], "赔率": h["T+5"]["event"].get("赔率")},
            "T20": {"mean%": h["T+20"]["event"].get("mean%"), "win%": h["T+20"]["event"].get("win%"),
                    "margC2": h["T+20"]["marg_C2_pp"]},
            "calT5_tNW": res["calendar"]["T+5"].get("t_NW"),
            "midT5": {"H1": res["midpoint_split"]["T+5"]["H1_前半"].get("mean%"),
                      "H2": res["midpoint_split"]["T+5"]["H2_后半"].get("mean%")},
        }
        print(f"  seat {seat}: n={seats_out[seat]['n_buy']} T5margC2={seats_out[seat]['T5']['margC2']}", flush=True)
    # 数据驱动分类（不抄网上名单）：T20 marg ≥ 0 且 ≥ T1 marg → 格局型；T1>0 但 T20 显著更差 → 收割型
    for seat, s in seats_out.items():
        m1, m20 = s["T1"]["margC2"], s["T20"]["margC2"]
        if m1 is None or m20 is None:
            s["生态分类"] = "样本不足"
        elif m20 >= 0 and m20 >= m1 - 0.5:
            s["生态分类"] = "格局型"
        elif m1 is not None and m1 > 0 and m20 < m1 - 1.5:
            s["生态分类"] = "收割型"
        else:
            s["生态分类"] = "平庸型"
    out["seats_top"] = seats_out

    # ---------- ④ 反向：卖出方向逐席位（出货信号筛查） ----------
    by_seat_sell = defaultdict(list)
    for r in seat_rows:
        if r["net_wan"] < 0 and r["code"] in stocks:
            by_seat_sell[r["seat"]].append(r)
    sell_out = {}
    for seat, rows in sorted(by_seat_sell.items(), key=lambda x: -len(x[1])):
        if len(rows) < MIN_SEAT_N:
            continue
        keys = [(r["code"], r["date"]) for r in rows]
        res = eval_group(seat + "_卖", keys, stocks, idx, pool1, pool2, uni_mean)
        h = res["horizons"]
        sell_out[seat] = {"n_sell": res["事件数_主板映射"],
                          "T5": {"mean%": h["T+5"]["event"].get("mean%"), "margC2": h["T+5"]["marg_C2_pp"]},
                          "T20": {"mean%": h["T+20"]["event"].get("mean%"), "margC2": h["T+20"]["marg_C2_pp"]}}
    out["seats_sell_side"] = sell_out

    # ---------- ③ 连板接力结构 ----------
    out["relay"] = relay_analysis(seat_rows, org_rows, stocks, idx, pool1, pool2, uni_mean)

    # ---------- 簇剂量 ----------
    out["dose"] = dose_analysis(seat_buy, stocks, idx, uni_mean)

    # ---------- 重叠审计 ----------
    out["overlap_audit"] = overlap_audit(seat_buy, stocks, idx)

    dst = ROOT / "data/lhb_follow_study_20261015.json"
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    print("SAVED", dst, flush=True)


def relay_analysis(seat_rows, org_rows, stocks, idx, pool1, pool2, uni_mean):
    """连板票席位接力：LHB上榜日=板日（chg≥9.8）。首板日上榜买入席位 → 二板日（i+1也涨停且再上LHB）席位结构：
    A=同席位连买 B=换席位 C=机构加入 D=首板无二板有席位。测二板收盘后 T+1/5/20（入场=二板次日开盘）。"""
    hot_by_date_code = {}
    for r in seat_rows:
        if r["net_wan"] > 0:
            hot_by_date_code.setdefault((r["date"], r["code"]), set()).add(r["seat"])
    org_by_date_code = {}
    for r in org_rows:
        if (r["org_net_wan"] or 0) > 0:
            org_by_date_code.setdefault((r["date"], r["code"]), 0)
            org_by_date_code[(r["date"], r["code"])] += 1
    lhb_dates_by_code = defaultdict(set)
    for (dt, code) in list(hot_by_date_code) + list(org_by_date_code):
        lhb_dates_by_code[code].add(dt)

    cases = []
    for code, d in stocks.items():
        dates = lhb_dates_by_code.get(code)
        if not dates:
            continue
        for i in range(65, d["n"] - MAXH - 2):
            dt = d["date"][i]
            if dt not in dates or not (WIN_START <= dt <= WIN_END):
                continue
            c = d["c"]
            if c[i - 1] <= 0 or c[i] / c[i - 1] - 1 < 0.098:
                continue  # 上榜日非涨停 → 非连板链
            if i + 1 >= d["n"] or c[i] <= 0 or c[i + 1] / c[i] - 1 < 0.098:
                continue  # 次日未连板
            dt2 = d["date"][i + 1]
            seats1 = hot_by_date_code.get((dt, code), set())
            seats2 = hot_by_date_code.get((dt2, code), set())
            org2 = (dt2, code) in org_by_date_code
            if seats1 & seats2:
                kind = "A_同席位连买"
            elif org2 and not seats2:
                kind = "C_机构接棒"
            elif seats2:
                kind = "B_换席位"
            else:
                kind = "D_二板无席位买入记录"
            fr = fwd_returns(d, i + 1)  # 入场=二板次日开盘
            if fr:
                _r1, _r2pack = matched_ctrl(d, i + 1, pool1, pool2)
                _c2 = _r2pack[0] if _r2pack else []
                cases.append({"kind": kind, "fr": fr, "c2": _c2, "seats1": len(seats1), "seats2": len(seats2)})
    by_kind = defaultdict(lambda: {h: [] for h in HORIZONS})
    ctrl_kind = defaultdict(lambda: {h: [] for h in HORIZONS})
    for cs in cases:
        for h in HORIZONS:
            if cs["fr"][h] is not None:
                by_kind[cs["kind"]][h].append(cs["fr"][h])
            for x in cs["c2"]:
                if x[h] is not None:
                    ctrl_kind[cs["kind"]][h].append(x[h])
    def _with_marg(ev_map, ct_map):
        out_h = {}
        for h in HORIZONS:
            e, c = stat(ev_map[h]), stat(ct_map[h])
            marg = round(e["mean%"] - c["mean%"], 2) if e.get("mean%") is not None and c.get("mean%") is not None else None
            out_h[f"T+{h}"] = {**e, "C2均值%": c.get("mean%"), "marg_C2_pp": marg}
        return out_h
    return {"总连板接力案例": len(cases),
            "结构分布": {k: sum(1 for c in cases if c["kind"] == k) for k in
                     ["A_同席位连买", "B_换席位", "C_机构接棒", "D_二板无席位买入记录"]},
            "by_kind": {k: _with_marg(v, ctrl_kind[k]) for k, v in by_kind.items()},
            "note": "入场=二板次日开盘（二板LHB盘后才可见），T+1=入场次日收盘。样本=1年窗内主板连板且两日均有LHB记录的票。"}


def dose_analysis(seat_buy, stocks, idx, uni_mean):
    """簇剂量：按上榜日统计当日全市场席位买入事件数（剂量），事件按剂量分桶测 T+5。"""
    cnt_by_date = Counter(dt for _, dt in seat_buy)
    buckets = {"低剂量(<=25)": [], "中剂量(26-40)": [], "高剂量(>=41)": []}
    for code, dt in seat_buy:
        d = stocks.get(code)
        if not d:
            continue
        i = idx[code].get(dt)
        if i is None:
            continue
        fr = fwd_returns(d, i)
        if not fr or fr[5] is None:
            continue
        n = cnt_by_date[dt]
        b = "低剂量(<=25)" if n <= 25 else "中剂量(26-40)" if n <= 40 else "高剂量(>=41)"
        buckets[b].append(fr[5])
    dose_counts = sorted(cnt_by_date.values())
    return {"剂量分桶_T+5": {k: stat(v) for k, v in buckets.items()},
            "当日事件数分布": {"min": dose_counts[0], "med": dose_counts[len(dose_counts) // 2],
                             "max": dose_counts[-1], "days": len(dose_counts)},
            "note": "剂量=当日全市场游资席位买入事件总数（含非主板计数，保持横截面口径一致）"}


def overlap_audit(seat_buy, stocks, idx):
    """与涨停族/连板族重叠审计。"""
    n, n_lu, n_first, n_2nd, n_down = 0, 0, 0, 0, 0
    for code, dt in seat_buy:
        d = stocks.get(code)
        if not d:
            continue
        i = idx[code].get(dt)
        if i is None or i < 61 or d["c"][i - 1] <= 0:
            continue
        n += 1
        chg = d["c"][i] / d["c"][i - 1] - 1
        if chg >= 0.098:
            n_lu += 1
            prev_board = any(d["c"][k - 1] > 0 and d["c"][k] / d["c"][k - 1] - 1 >= 0.098
                             for k in range(max(1, i - 60), i))
            if not prev_board:
                n_first += 1
            else:
                n_2nd += 1
        elif chg <= -0.05:
            n_down += 1
    return {"游资买入事件_主板": n,
            "上榜日涨停占比%": round(100 * n_lu / n, 1) if n else None,
            "其中60日首板%": round(100 * n_first / n, 1) if n else None,
            "其中60日内非首板%": round(100 * n_2nd / n, 1) if n else None,
            "上榜日跌≥5%占比%": round(100 * n_down / n, 1) if n else None,
            "声明": "游资买入事件与涨停族高度嵌套（见占比）——其收益里含涨停族成分，marg_C2（同涨幅桶匹配）才是席位归属的净edge；"
                  "与妖股摇篮(首板缩量深跌小市值)仅交叉（首板占比≠缩量深跌条件）。"}


if __name__ == "__main__":
    main()
