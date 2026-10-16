#!/usr/bin/env python3
"""engine/portfolio.py — 组合层 v1 统一账本 + 多线联赛模拟器（2026-10-16 卡 t_f705b7b5，#262-C 头号缺口）

回答的问题：「存活线同时开跑，我的钱去年到底赚多少、回撤多深」。

七条参赛线（三条账户，分级仓位——长持有期线独立小账本，不与 T+5 线抢槽，#组合层教训）：
  进攻账户（5 槽共享，槽位竞争按注册优先级）：
    1 DEEP_V2   深档低位v2：簇门=当日全库「pct≤-9.5% 且 c<MA60 且 c≤MA60×0.75」件数≥5，
                出手=深度≤-35% 锐化子集按深度最深 top5（逐字复刻 dashboard_build.deep_low_scan 生产口径）
    2 LD        跌停接_MA60下 剔一字（law_pipeline._limitdown & c≤MA60）
    3 REV_KNN   反转族×knn_vote 排序版（候选层 RES-07）：REV 事件 ∩ OOS 2023+，
                剔 knn_vote 十分档≤1（#279 别碰层 t=-3.15），同日线内按 dec 降序优先吃槽
    4 REV_RES08 反转族×RES-08 四因子过滤版：ivol20/pv_corr_ov10/pv_corr_cv20/volcv20
                低十分档(dec≤1)投票≥2 通过（#279 最佳 ivol20_low×反转族 +1.12pp 的影子扩展）
    5 REV       反转族确认：pct≤-3% 且 额代理(amt 或 v×c)≥8e7（ICU 中，参赛为同场对照）
  红利账户（核心3+卫星2 独立，复刻 dividend_core_satellite 生产口径）：DIV 股息锚买入区——
                宇宙≥3 年度分红+非ST/退+价>2，TTM 息率≥4.5% 次日开盘买（当日息率最高者优先）；
                核心仓卖点 <3.0%、卫星仓 <3.5%（次日开盘卖），核心有空位时卫星中息率≥4.5% 者升级；
                每只名义仓=该账户当前权益/5（复利，capacity_sim 固定槽不同，此线沿用其原生口径）。
  转债账户（3 槽独立）：CB 低价池——收盘 80<价≤105 次日开盘买，T+120 收盘出（cb_daily 946 只含退市宇宙）

统一规则：
  入场=T+1 开盘价（父卡 t_316237a5 裁决：择时无增益版，维持 E0_open，不建回踩子模型）；
  股票线入场日一字跌停开（o≤前收×0.905）作废；CB/DIV 不剔（流动性充足）。
  出场：进攻线 T+5 收盘、CB T+120 收盘；持有窗越界按最后 bar 收盘结算（全命运口径，对齐 #280 P2）。
  成本：统一平口径 FLAT_RT（往返 0.15%，单扣一次，capacity_sim 口径），数值唯一真源 engine/costs.py；
        CB 真实费率更低=本口径偏保守；dividend_core_satellite 原曲线按 2×FLAT_RT（0.3%）计，
        故 DIV 锚点对比为偏紧上界；真实费目（最低佣金 5 元）敏感性在输出 min_comm_drag元 另报。
  盯市：真实逐日 MTM（优于 capacity_sim 的持有期走平口径），停牌/退市按最后已知价。
  槽位：进攻 5 / 红利 核心3+卫星2 / 转债 3；同 code 同日多线命中=高优先级线吃槽。
  名义仓：三线统一=该账户当前权益/槽数（复利、动态——capacity_sim 的固定 cap0/槽 是容量上限测试口径，
        会造「权益跌破单槽永久封仓」假象，PnL 账本必须动态；容量上限问题仍归 capacity_sim）。
  同日线内选择序（槽位竞争教训#279：禁用遍历顺序）：DEEP_V2=深度最深 top5（生产原生）；
        LD=距MA60最深优先（跌停接家族验证过的唯一真排名器 deep）；REV_KNN=knn dec 降序；
        REV / REV_RES08=定种子随机洗牌（反转族「挑最深=负选择」已实证，random.Random(7)）；
        DIV=当日息率最高优先；CB=定种子洗牌。

用法：.venv/bin/python engine/portfolio.py            # 全量实跑（加载宇宙，约 2-4 分钟）
      .venv/bin/python engine/portfolio.py report     # 纯读最新 data/portfolio_sim_*.json 打印摘要
产出：data/portfolio_sim_YYYYMMDD.json（摘要+矩阵+逐年）+ data/portfolio_sim_curves_YYYYMMDD.json（10万档逐日曲线）
"""
import bisect
import glob
import json
import math
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
sys.path.insert(0, str(ROOT / "engine"))
from costs import FLAT_RT  # noqa: E402  税费唯一真源（TAX-01，#287）
FEE = FLAT_RT               # 平口径往返 0.15%，单扣一次
HOLD_T, CB_HOLD = 5, 120
DIV_BUY_Y = 0.045
OOS_KNN = "2023-01-01"
TIERS = (50000, 100000, 200000)
SPLIT = {"atk": 0.60, "div": 0.25, "cb": 0.15}      # v1 默认，待裁决
SLOTS = {"atk": 5, "div": 5, "cb": 3}
PRIORITY = ["DEEP_V2", "LD", "REV_KNN", "REV_RES08", "REV"]   # 进攻账户槽位竞争序（高→低）
ATK_LINES = set(PRIORITY)
RES08_FACTORS = ("dec_ivol20", "dec_pv_corr_ov10", "dec_pv_corr_cv20", "dec_volcv20")

REGIME_BY_DATE = {}   # 由 load_regime() 填充；空 dict 时 regime 门为 no-op（向后兼容）


def load_regime():
    """读 data/regime_timeline_hcap.json（权威 regime 轴）填 REGIME_BY_DATE。缺失静默返回空。"""
    fp = ROOT / "data/regime_timeline_hcap.json"
    if not fp.exists():
        return REGIME_BY_DATE
    for row in json.loads(fp.read_text()):
        REGIME_BY_DATE[row["date"]] = row["regime"]
    return REGIME_BY_DATE

sys.path.insert(0, str(ROOT / "engine"))
import law_pipeline as lp  # noqa: E402


# ---------- 信号生成（单次宇宙遍历） ----------
def gen_stock_signals(stocks, names):
    rev, ld, deep = defaultdict(list), defaultdict(list), defaultdict(list)
    for code, d in stocks.items():
        if code[:2] not in ("60", "00"):
            continue
        nm = names.get(code, "")
        if "ST" in nm or "退" in nm:
            continue
        c, o, h, l, v, amt, ma, date, n = (d["c"], d["o"], d["h"], d["l"], d["v"],
                                           d["amt"], d["ma60"], d["date"], d["n"])
        for i in range(61, n - 1):
            if c[i - 1] <= 0 or c[i] <= 0 or ma[i] is None:
                continue
            pct = c[i] / c[i - 1] - 1
            if pct > -0.03:
                continue
            dt = date[i]
            if amt[i] > 0:
                a = amt[i]
            else:
                a = v[i] * c[i]
            if a >= 8e7:
                rev[dt].append((code, i))
            if pct <= -0.095:
                one_way = o[i] / c[i - 1] - 1 <= -0.09 and (h[i] - l[i]) / c[i - 1] < 0.01
                if not one_way and c[i] <= ma[i]:
                    ld[dt].append((code, i, -(c[i] / ma[i] - 1)))   # rank=-depth，深者在前
                if c[i] < ma[i] and c[i] <= ma[i] * 0.75:
                    deep[dt].append((code, i, c[i] / ma[i] - 1))
    return rev, ld, deep


def deep_picks(deep):
    out = {}
    for dt, evs in deep.items():
        if len(evs) < 5:
            continue
        sharp = sorted((e for e in evs if e[2] <= -0.35), key=lambda e: e[2])[:5]
        if sharp:
            out[dt] = [(c, i, -k) for k, (c, i, _dep) in enumerate(sharp)]  # rank 大者先吃槽
    return out


def knn_variants(rev):
    import numpy as np
    zb = np.load(ROOT / "data/factor_census_base.npz")
    cal = zb["calendar"].tolist()
    cal2i = {d: k for k, d in enumerate(cal)}
    c2j = {int(c): j for j, c in enumerate(zb["codes"].tolist())}
    knn, res08 = defaultdict(list), defaultdict(list)
    dec_k = zb["dec_knn_vote"]
    dec_f = {f: zb[f] for f in RES08_FACTORS}
    for dt, evs in rev.items():
        if dt < OOS_KNN:
            continue
        di = cal2i.get(dt)
        if di is None:
            continue
        for code, i in evs:
            j = c2j.get(int(code))
            if j is None:
                continue
            dk = int(dec_k[di, j])
            if dk != 255 and dk > 1:
                knn[dt].append((code, i, dk))           # rank=dec，高者优先
            votes = sum(1 for f in RES08_FACTORS
                        if int(dec_f[f][di, j]) != 255 and int(dec_f[f][di, j]) <= 1)
            if votes >= 2:
                res08[dt].append((code, i, 0))
    return knn, res08


def gen_div_signals(stocks, names, divh):
    uni = []
    for code, recs in divh.items():
        if code not in stocks:
            continue
        nm = names.get(code, "")
        if "ST" in nm or "退" in nm:
            continue
        if len({r[0][:4] for r in recs}) >= 3:
            uni.append(code)
    sigs, ttm_map = {}, {}
    for code in uni:
        d = stocks[code]
        recs = sorted(divh[code])
        dts = [r[0] for r in recs]
        arr = []
        for dt in d["date"]:
            lo = bisect.bisect_right(dts, dt)
            hi = bisect.bisect_right(dts, str(int(dt[:4]) - 1) + dt[4:])
            arr.append(sum(dp for _, dp in recs[hi:lo]))
        ttm_map[code] = arr
        for i, dt in enumerate(d["date"]):
            if d["c"][i] > 2 and i + 1 < d["n"]:
                y = arr[i] / d["c"][i]
                if y >= DIV_BUY_Y:
                    sigs.setdefault(dt, []).append((code, i, y))   # rank=息率，高者优先
    return sigs, ttm_map, uni


def gen_cb_signals():
    sigs, bars = {}, {}
    for fp in glob.glob(str(ROOT / "data/cb_daily/*.json")):
        code = Path(fp).stem
        rows = [r for r in json.load(open(fp))["rows"] if r["close"] > 0]
        if len(rows) < 2:
            continue
        bars[code] = rows
        for i in range(len(rows) - 1):
            if 80 < rows[i]["close"] <= 105:
                sigs.setdefault(rows[i]["date"], []).append((code, i, 0))
    return sigs, bars


# ---------- 账本 ----------
class Book:
    def __init__(self, capital, slots, name):
        self.name = name
        self.cap0 = float(capital)
        self.slot = float(capital) / slots
        self.nslots = slots
        self.cash = float(capital)
        self.cap_today = slots   # 当日可持仓上限（恐慌半仓门会临时压低，默认=槽数）
        self.pos = []       # {code,line,shares,entry_px,entry_d,exit_d,notional,last_px}
        self.trades = []    # {line,code,entry_d,exit_d,ret,pnl,why}

    def free(self):
        return self.cap_today - len(self.pos)

    def equity(self):
        return self.cash + sum(p["shares"] * p["last_px"] for p in self.pos)


DIV_CORE_MAX, DIV_SAT_MAX = 3, 2
DIV_CORE_SELL_Y, DIV_SAT_SELL_Y = 0.030, 0.035


SHUFFLE_LINES = {"REV", "REV_RES08", "CB"}   # 无原生排名器的线：定种子洗牌，禁遍历顺序（#279）


def build_entries(sigs_by_line, didx, stocks, cb_bars):
    """sigs_by_line: {line: {sig_date: [(code, i, rank)]}} → entries[entry_date] = [(prio, -rank, line, code, exit_d, account)]
    约定：rank 越大越优先吃槽；SHUFFLE_LINES 每日定种子洗牌后按洗牌序赋 rank。"""
    entries = defaultdict(list)
    for line, sigs in sigs_by_line.items():
        prio = PRIORITY.index(line) if line in ATK_LINES else 0
        account = "atk" if line in ATK_LINES else ("div" if line == "DIV" else "cb")
        for dt, evs in sigs.items():
            if line in SHUFFLE_LINES:
                evs = list(evs)
                random.Random(f"7|{line}|{dt}").shuffle(evs)
                evs = [(c, i, -k) for k, (c, i, *_) in enumerate(evs)]
            for ev in evs:
                code, i, rank = ev[0], ev[1], (ev[2] if len(ev) > 2 else 0)
                if account == "cb":
                    rows = cb_bars.get(code)
                    if not rows or i + 1 >= len(rows):
                        continue
                    ei, xi = i + 1, min(i + 1 + CB_HOLD, len(rows) - 1)
                    if rows[ei]["open"] <= 0:
                        continue
                    entries[rows[ei]["date"]].append((prio, -rank, line, code, rows[xi]["date"], account))
                else:
                    d = stocks.get(code)
                    if d is None or i + 1 >= d["n"]:
                        continue
                    ei = i + 1
                    if d["o"][ei] <= 0:          # 次日停牌=无法成交，跳过
                        continue
                    if line == "DIV":
                        entries[d["date"][ei]].append((0, -rank, line, code, None, "div"))
                        continue
                    if d["o"][ei] <= d["c"][i] * 0.905:     # 一字跌停开=作废
                        continue
                    xi = min(ei + HOLD_T, d["n"] - 1)
                    entries[d["date"][ei]].append((prio, -rank, line, code, d["date"][xi], "atk"))
    return entries


def simulate(entries, capital, calendar, stocks, didx, cb_didx, cb_bars, ttm_map,
             lines_active, slots=None, split=None, panic_half=False, solo=None):
    slots = dict(SLOTS) if slots is None else dict(slots)
    split = dict(SPLIT) if split is None else dict(split)
    if solo is None:
        solo = len(lines_active) == 1
    books = {}
    caps = {"atk": capital * split["atk"], "div": capital * split["div"], "cb": capital * split["cb"]}
    if solo:                     # solo：单线独占全部本金与天然槽位
        ln = lines_active[0]
        acct = "atk" if ln in ATK_LINES else ("div" if ln == "DIV" else "cb")
        books = {acct: Book(capital, slots[acct], acct)}
        caps = {acct: float(capital)}
    else:
        for a in ("atk", "div", "cb"):
            books[a] = Book(caps[a], slots[a], a)
    curve = []
    invested_series = []
    for day in calendar:
        if panic_half and "atk" in books:
            # regime 门增强版：恐慌期进攻账户仓位上限减半（#289 基础门之上的反事实）
            books["atk"].cap_today = max(1, int(math.ceil(slots["atk"] / 2))) \
                if REGIME_BY_DATE.get(day) == "恐慌期" else slots["atk"]
        todays = sorted(entries.get(day, []), key=lambda x: (x[0], x[1]))
        # OPEN：DIV 规则卖（昨日收盘触发的队列在 pos['sell_open']）
        for bk in books.values():
            for p in list(bk.pos):
                if p.get("sell_open"):
                    px = None
                    j = didx.get(p["code"], {}).get(day)
                    if j is not None:
                        px = stocks[p["code"]]["o"][j]
                    if px and px > 0:
                        bk.cash += p["shares"] * px - p["notional"] * FEE
                        bk.trades.append({"line": p["line"], "code": p["code"], "entry_d": p["entry_d"],
                                          "exit_d": day, "ret": px / p["entry_px"] - 1 - FEE,
                                          "pnl": p["shares"] * px - p["notional"] * (1 + FEE),
                                          "notional": p["notional"], "why": "div_yield"})
                        bk.pos.remove(p)
                    else:
                        p["sell_open"] = True   # 停牌顺延
        # OPEN：买
        bought = defaultdict(set)
        for _prio, _rank, line, code, exit_d, account in todays:
            bk = books.get(account)
            if bk is None or bk.free() <= 0:
                continue
            if code in bought[account] or any(p["code"] == code for p in bk.pos):
                continue
            if account == "cb":
                j = cb_didx.get(code, {}).get(day)
                px = cb_bars[code][j]["open"] if j is not None else None
            else:
                j = didx.get(code, {}).get(day)
                px = stocks[code]["o"][j] if j is not None else None
            if not px or px <= 0:
                continue
            tier = None
            slot = bk.equity() / bk.nslots   # 动态名义仓=当前权益/槽数（复利，防固定槽封仓假象）
            if account == "div":
                n_core = sum(1 for p in bk.pos if p.get("tier") == "core")
                n_sat = sum(1 for p in bk.pos if p.get("tier") == "sat")
                if n_core < DIV_CORE_MAX:
                    tier = "core"
                elif n_sat < DIV_SAT_MAX:
                    tier = "sat"
                else:
                    continue
            if bk.cash < slot:
                continue
            shares = slot / px
            bk.cash -= slot
            bk.pos.append({"code": code, "line": line, "shares": shares, "entry_px": px,
                           "entry_d": day, "exit_d": exit_d, "notional": slot, "last_px": px,
                           "tier": tier})
            bought[account].add(code)
        # CLOSE：固定到期出场 + DIV 卖出规则评估 + MTM
        for bk in books.values():
            for p in list(bk.pos):
                if p["exit_d"] == day:
                    if p["line"] == "CB":
                        j = cb_didx.get(p["code"], {}).get(day)
                        px = cb_bars[p["code"]][j]["close"] if j is not None else p["last_px"]
                    else:
                        j = didx.get(p["code"], {}).get(day)
                        px = stocks[p["code"]]["c"][j] if j is not None else p["last_px"]
                    if px and px > 0:
                        bk.cash += p["shares"] * px - p["notional"] * FEE
                        bk.trades.append({"line": p["line"], "code": p["code"], "entry_d": p["entry_d"],
                                          "exit_d": day, "ret": px / p["entry_px"] - 1 - FEE,
                                          "pnl": p["shares"] * px - p["notional"] * (1 + FEE),
                                          "notional": p["notional"], "why": "horizon"})
                        bk.pos.remove(p)
                        continue
                # 更新盯市价
                if p["line"] == "CB":
                    j = cb_didx.get(p["code"], {}).get(day)
                    if j is not None:
                        p["last_px"] = cb_bars[p["code"]][j]["close"]
                else:
                    j = didx.get(p["code"], {}).get(day)
                    if j is not None:
                        p["last_px"] = stocks[p["code"]]["c"][j]
                # DIV 卖出规则（收盘息率跌破线 → 次日开盘卖；核心 3.0% / 卫星 3.5%）
                if p["line"] == "DIV" and j is not None:
                    ttm = ttm_map.get(p["code"])
                    if ttm is not None:
                        y = ttm[j] / stocks[p["code"]]["c"][j] if stocks[p["code"]]["c"][j] > 0 else 0
                        thr = DIV_CORE_SELL_Y if p.get("tier") == "core" else DIV_SAT_SELL_Y
                        if y < thr:
                            p["sell_open"] = True
            # DIV 卫星→核心升级（核心有空位且卫星票息率仍≥4.5%，不产生买卖、不计费）
            if bk.name == "div":
                n_core = sum(1 for p in bk.pos if p.get("tier") == "core")
                if n_core < DIV_CORE_MAX:
                    for p in bk.pos:
                        if p.get("tier") == "sat" and n_core < DIV_CORE_MAX:
                            j = didx.get(p["code"], {}).get(day)
                            if j is not None:
                                ttm = ttm_map.get(p["code"])
                                cc = stocks[p["code"]]["c"][j]
                                if ttm is not None and cc > 0 and ttm[j] / cc >= DIV_BUY_Y:
                                    p["tier"] = "core"
                                    n_core += 1
        eq = sum(bk.cash + sum(p["shares"] * p["last_px"] for p in bk.pos) for bk in books.values())
        inv = sum(sum(p["shares"] * p["last_px"] for p in bk.pos) for bk in books.values())
        curve.append((day, round(eq, 0)))
        invested_series.append(inv / eq if eq > 0 else 0)
    trades = [t for bk in books.values() for t in bk.trades]
    return curve, trades, invested_series, books


# ---------- 指标 ----------
def metrics(curve, trades, invested_series):
    if not curve:
        return {}
    yrs = len(curve) / 244.0
    final = curve[-1][1] / curve[0][1]
    peak, mdd = -1e18, 0.0
    for _, e in curve:
        peak = max(peak, e)
        mdd = min(mdd, e / peak - 1)
    rets = [t["ret"] for t in trades]
    yearly = {}
    for d, e in curve:
        yearly.setdefault(d[:4], []).append(e)
    return {"final_x": round(final, 3),
            "ann%": round(((final) ** (1 / yrs) - 1) * 100, 2) if yrs > 0 else None,
            "mdd%": round(mdd * 100, 1),
            "util%": round(100 * sum(invested_series) / len(invested_series), 1) if invested_series else None,
            "trades": len(trades),
            "win%": round(100 * sum(1 for r in rets if r > 0) / len(rets), 1) if rets else None,
            "mean%": round(100 * sum(rets) / len(rets), 2) if rets else None,
            "yearly%": {y: round((v[-1] / v[0] - 1) * 100, 1) for y, v in yearly.items()}}


def corr_matrix(solo_pnl):
    lines = sorted(solo_pnl)
    out = {}
    for a in lines:
        for b in lines:
            xa, xb = solo_pnl[a], solo_pnl[b]
            n = min(len(xa), len(xb))
            if n < 30:
                out[f"{a}|{b}"] = None
                continue
            xa, xb = xa[-n:], xb[-n:]
            ma_, mb_ = sum(xa) / n, sum(xb) / n
            cov = sum((x - ma_) * (y - mb_) for x, y in zip(xa, xb)) / n
            va = sum((x - ma_) ** 2 for x in xa) / n
            vb = sum((y - mb_) ** 2 for y in xb) / n
            out[f"{a}|{b}"] = round(cov / math.sqrt(va * vb), 3) if va > 0 and vb > 0 else None
    return out


def event_anchor(sigs, stocks, hold):
    """事件级锚点自检：entry=T+1 open, exit=T+hold close, 全命运。"""
    rets = []
    for dt, evs in sigs.items():
        for ev in evs:
            code, i = ev[0], ev[1]
            d = stocks.get(code)
            if d is None or i + 1 >= d["n"] or d["o"][i + 1] <= 0:
                continue
            if d["o"][i + 1] <= d["c"][i] * 0.905:
                continue
            xi = min(i + 1 + hold, d["n"] - 1)
            rets.append(d["c"][xi] / d["o"][i + 1] - 1 - FEE)
    if not rets:
        return None
    return {"n": len(rets), "win%": round(100 * sum(1 for r in rets if r > 0) / len(rets), 1),
            "mean%": round(100 * sum(rets) / len(rets), 3)}


def cb_event_anchor(sigs, cb_bars):
    rets = []
    for dt, evs in sigs.items():
        for ev in evs:
            code, i = ev[0], ev[1]
            rows = cb_bars.get(code)
            if not rows or i + 1 >= len(rows) or rows[i + 1]["open"] <= 0:
                continue
            xi = min(i + 1 + CB_HOLD, len(rows) - 1)
            rets.append(rows[xi]["close"] / rows[i + 1]["open"] - 1 - FEE)
    if not rets:
        return None
    return {"n": len(rets), "win%": round(100 * sum(1 for r in rets if r > 0) / len(rets), 1),
            "mean%": round(100 * sum(rets) / len(rets), 3)}


def main():
    t0 = time.time()
    print("[portfolio] 加载宇宙…", flush=True)
    load_regime()
    stocks = lp.load_universe()
    names = {str(s["code"]).zfill(6): s.get("name", "")
             for s in json.loads((ROOT / "data/main_board_codes.json").read_text())["stocks"]}
    calendar = [k["date"] for k in json.loads((ROOT / "data/index_sh000001.json").read_text())]
    didx = {c: {x: j for j, x in enumerate(s["date"])} for c, s in stocks.items()}
    print(f"[portfolio] 宇宙 {len(stocks)} 只, 日历 {len(calendar)} 天 ({time.time()-t0:.0f}s)", flush=True)

    rev, ld, deep = gen_stock_signals(stocks, names)
    deep5 = deep_picks(deep)
    print(f"[portfolio] 事件: REV={sum(len(v) for v in rev.values())} LD={sum(len(v) for v in ld.values())} "
          f"DEEP簇日={len(deep5)} 出手={sum(len(v) for v in deep5.values())} ({time.time()-t0:.0f}s)", flush=True)
    knn, res08 = knn_variants(rev)
    divh = json.loads((ROOT / "data/dividend_history.json").read_text())
    div_sigs, ttm_map, div_uni = gen_div_signals(stocks, names, divh)
    cb_sigs, cb_bars = gen_cb_signals()
    cb_didx = {c: {r["date"]: j for j, r in enumerate(rows)} for c, rows in cb_bars.items()}
    print(f"[portfolio] KNN变体={sum(len(v) for v in knn.values())} RES08变体={sum(len(v) for v in res08.values())} "
          f"DIV宇宙={len(div_uni)} 信号={sum(len(v) for v in div_sigs.values())} "
          f"CB={len(cb_bars)}只 信号={sum(len(v) for v in cb_sigs.values())} ({time.time()-t0:.0f}s)", flush=True)

    sigs_all = {"DEEP_V2": deep5, "LD": ld, "REV": rev, "REV_KNN": knn, "REV_RES08": res08,
                "DIV": div_sigs, "CB": cb_sigs}
    entries_all = build_entries(sigs_all, didx, stocks, cb_bars)
    entries_by_line = {ln: build_entries({ln: sigs_all[ln]}, didx, stocks, cb_bars)
                       for ln in sigs_all}

    # 锚点自检（事件级，独立于账本）
    anchors = {
        "LD_T+5": event_anchor(ld, stocks, HOLD_T),
        "DEEP_V2_top5_T+5": event_anchor({d: v for d, v in deep5.items()}, stocks, HOLD_T),
        "CB_T+120": cb_event_anchor(cb_sigs, cb_bars),
        "deep_batches": len(deep5),
        "_expect": "LD≈68%+5.09%(#280锚), deep簇日≈65(#282重建64/65), CB≈72.9%/+7.79%(旧312活跃口径,含退市946口径应略低), "
                   "DIV 8y≈+196.8%(0913口径按2×FLAT_RT计费,本账本0.15%往返为偏松对照)",
    }
    print("[portfolio] 锚点:", json.dumps(anchors, ensure_ascii=False), flush=True)

    results = {"_meta": {"produced_by": "engine/portfolio.py", "version": "v1",
                         "produced_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                         "calendar": [calendar[0], calendar[-1]],
                         "fee_roundtrip": FEE, "entry": "T+1 open (E0_open, 父卡t_316237a5裁决)",
                         "split_default": SPLIT, "slots": SLOTS, "priority_atk": PRIORITY,
                         "notes": "CB真实费率低于0.15%=偏保守; 三档资金等比缩放%相同(固定槽位比例), "
                                  "元绝对值按比例, 最低佣金5元/笔对5万档拖约每笔≤7.5元(见min_comm_drag元)"},
               "anchors": anchors, "tiers": {}}

    for cap in TIERS:
        tier = {"lines": {}, "contrib": {}}
        solo_pnl = {}
        for ln in ["DEEP_V2", "LD", "REV", "REV_KNN", "REV_RES08", "DIV", "CB"]:
            curve, trades, inv, _books = simulate(entries_by_line[ln], cap, calendar, stocks,
                                                  didx, cb_didx, cb_bars, ttm_map, [ln])
            tier["lines"][ln] = metrics(curve, trades, inv)
            solo_pnl[ln] = [curve[k][1] - (curve[k - 1][1] if k else curve[0][1])
                            for k in range(len(curve))]
            if cap == 100000:
                tier.setdefault("_curves", {})[ln] = curve
        # 合并
        curve, trades, inv, books = simulate(entries_all, cap, calendar, stocks, didx, cb_didx,
                                             cb_bars, ttm_map, list(sigs_all))
        tier["merged"] = metrics(curve, trades, inv)
        # 现金守恒对账（账本纪律：headline 与逐笔 PnL 必须 reconcilable）
        closed_pnl = sum(t["pnl"] for t in trades)
        open_mtm = sum(p["shares"] * p["last_px"] - p["notional"]
                       for bk in books.values() for p in bk.pos)
        resid = curve[-1][1] - cap - closed_pnl - open_mtm
        tier["audit"] = {"closed_pnl": round(closed_pnl, 0), "open_mtm": round(open_mtm, 0),
                         "recon_resid": round(resid, 4), "open_pos": sum(len(b.pos) for b in books.values())}
        assert abs(resid) < 1.0, f"现金不守恒 resid={resid}"
        for t in trades:
            y = t["exit_d"][:4]
            if y not in tier["contrib"]:
                tier["contrib"][y] = defaultdict(float)
            tier["contrib"][y][t["line"]] += t["pnl"]
        tier["contrib"] = {y: {k: round(v, 0) for k, v in sorted(d.items())}
                           for y, d in sorted(tier["contrib"].items())}
        tier["corr"] = corr_matrix(solo_pnl)
        # 最低佣金敏感性：真实费目双边保底10元 vs 平口径已含佣金(~0.1%双边按0.05%估)
        drag = sum(max(0.0, 10.0 - 0.0005 * t["notional"]) for t in trades)
        tier["min_comm_drag元"] = round(drag, 0)
        if cap == 100000:
            tier["_curves"]["MERGED"] = curve
        results["tiers"][str(cap)] = tier
        print(f"[portfolio] 档位 {cap}: merged final={tier['merged']['final_x']}x "
              f"ann={tier['merged']['ann%']}% mdd={tier['merged']['mdd%']}% "
              f"trades={tier['merged']['trades']} ({time.time()-t0:.0f}s)", flush=True)

    out_day = time.strftime("%Y%m%d")
    curves = results["tiers"]["100000"].pop("_curves", None)
    p1 = ROOT / f"data/portfolio_sim_{out_day}.json"
    p1.write_text(json.dumps(results, ensure_ascii=False))
    if curves:
        (ROOT / f"data/portfolio_sim_curves_{out_day}.json").write_text(
            json.dumps({k: v for k, v in curves.items()}, ensure_ascii=False))
    print(f"[portfolio] 落盘 {p1.name} + curves ({time.time()-t0:.0f}s)", flush=True)
    print_report(results)


def print_report(res):
    t = res["tiers"]["100000"]
    print("\n===== 组合层 v1 · 10万档 =====")
    m = t["merged"]
    print(f"合并: {m['final_x']}x 年化{m['ann%']}% 回撤{m['mdd%']}% 占用{m['util%']}% "
          f"交易{m['trades']}笔 胜率{m['win%']}% 均笔{m['mean%']}%")
    print("逐年%:", json.dumps(m["yearly%"], ensure_ascii=False))
    print("单线:")
    for ln, mm in t["lines"].items():
        print(f"  {ln:9s} {mm.get('final_x')}x 年化{mm.get('ann%')}% 回撤{mm.get('mdd%')}% "
              f"占用{mm.get('util%')}% n={mm.get('trades')} 胜率{mm.get('win%')}%")
    print("逐年贡献(元):")
    for y, d in t["contrib"].items():
        print(f"  {y}: {json.dumps(d, ensure_ascii=False)}")


def report():
    files = sorted(glob.glob(str(ROOT / "data/portfolio_sim_2*.json")))
    files = [f for f in files if "curves" not in f]
    if not files:
        print("无产物，先跑主模式")
        return
    res = json.loads(open(files[-1]).read())
    print_report(res)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "report":
        report()
    else:
        main()
