#!/usr/bin/env python3
"""dual_cannon_study.py — 「双响炮」形态事件研究（2026-10-15 用户立项「测双响炮形态（我忘了有没有测过了）」）。

查重结论（本脚本头部记录，落 AGENTS.md 时要引）：
- 仓库内 grep「双响炮/两阳夹一阴/多方炮」零命中（pead_events.json / north_holders 里的命中是公司名/票名巧合）。
- 最接近的已测形态 = **N字回踩企稳**（`law_pipeline.py:_nshape_retrace`，台账 #109 / docs/nshape-and-exitmatrix-20260919.md）：
  低位放量**首板** → 缩量回踩 → 第 3 日企稳，三连证伪（二波入场 12 格全负 / 回踩入场过不了闸 / submit REJECT：
  全样本 T+5 43.8%/-0.01%、位置匹配边际≈0、G7 年化 -5%）。
- **双响炮与它的差别**：两根都是**放量大阳**（≥7% 或涨停，非必须首板），中间夹 1-3 日缩量回调不破第一根
  **实体中点**（N字用 o[B]×0.97）。属未测形态，本脚本从零测。

民间定义（用户给定）：第一根放量大阳（涨幅≥7% 或涨停）→ 中间夹 1-3 日缩量回调（不破第一根阳线实体中点）
→ 第二根放量大阳。确认日 = 第二根大阳（收盘可判），入场 T+1 开盘买，净费 0.15%（全仓统一口径）。

口径：零前视（只用 ≤i 信息）；一字跌停买不到剔除并计数；全 horizon T+1/2/3/5/10/20 ×
胜率+均值+赔率+分年+双段(2019-22/2023-26)+近250日+regime分段+位置匹配对照+NW t；n<300 标注样本不足。

工程：**流式逐票扫描**（一次只驻一票，峰值内存 ~50MB）——2026-10-15 首版用 law_pipeline.load_universe()
全宇宙驻留，与四个兄弟 kanban 卡并发加载时被 OOM SIGKILL（exit 137，机器 15GB）。研究脚本复用
load_universe 前先看当前并发。

输出 data/dual_cannon_study_<date>.json + stdout 表格。
"""
import json
import math
import statistics as st
import sys
from array import array
from bisect import bisect_right, insort
from datetime import datetime, timezone
from pathlib import Path
from random import Random

ROOT = Path("/opt/data/fenjue")
KC = ROOT / "data/big_kcache"
CAPH = ROOT / "data/cap_hist"
TIMELINE = ROOT / "data/regime_timeline_hcap.json"
from costs import FLAT_RT  # TAX-01 唯一真源 engine/costs.py（AGENTS #287）
FEE = FLAT_RT
HORIZONS = (1, 2, 3, 5, 10, 20)
HMAX = max(HORIZONS)
SMALL_N = 300
MIN_BIG = 0.07       # 大阳线涨幅阈值
LIMIT_PCT = 0.098    # 涨停
VOL_B1 = 1.5         # 第一根量比（对前 5 日均量）
SHRINK = 1.0         # 中间日量 < 第一根量 × SHRINK


def _volratio(v, i, n=5):
    base = v[max(0, i - n):i]
    if len(base) < n or any(x <= 0 for x in base):
        return 0.0
    m = sum(base) / len(base)
    return v[i] / m if m > 0 else 0.0


def cannon(d, i, k=1, big=MIN_BIG, require_limit=False, mid_bear=None,
           s_vol_ge_b1=True, s_over_b1_high=False, below_ma60=False,
           mid_vol_free=False, hold_ref="mid"):
    """检测日 i = 第二根大阳线（确认日，收盘可判）。k = 中间交易日数(1-3)，B = i-k-1。

    hold_ref=中间回调的支撑参照：mid=第一根实体中点（用户给定）、close=第一根收盘（更严）、
    open=第一根开盘（更松）。mid_vol_free=True 时中间回调不限量。
    """
    c, o, h, l, v, ma = d["c"], d["o"], d["h"], d["l"], d["v"], d["ma60"]
    B = i - k - 1
    if B < 61 or k < 1 or k > 3:
        return False
    if c[B] <= 0 or c[B - 1] <= 0 or c[i - 1] <= 0:
        return False
    if not (c[B] > o[B]) or not (c[i] > o[i]):      # 两根都是阳线
        return False
    g1, g2 = c[B] / c[B - 1] - 1, c[i] / c[i - 1] - 1
    thr = LIMIT_PCT if require_limit else big
    if g1 < thr or g2 < thr:
        return False
    if v[B] <= 0 or _volratio(v, B) < VOL_B1:       # 第一根放量
        return False
    sup = {"mid": (c[B] + o[B]) / 2, "close": c[B], "open": o[B]}[hold_ref]
    for j in range(B + 1, i):
        if c[j] <= 0 or l[j] <= 0:
            return False
        if not mid_vol_free and v[j] >= v[B] * SHRINK:   # 中间缩量
            return False
        if l[j] < sup:                                   # 不破支撑参照
            return False
        if mid_bear is True and not (c[j] < o[j]):
            return False
        if mid_bear is False and not (c[j] > o[j]):
            return False
    if s_vol_ge_b1 and v[i] < v[B]:                  # 第二根量 ≥ 第一根
        return False
    if s_over_b1_high and not (c[i] > h[B]):         # 过第一根最高
        return False
    if below_ma60 and not (ma[i] is not None and c[i] <= ma[i]):
        return False
    return True


VARIANTS = [
    ("A_纯定义_7pct_k1", lambda d, i: cannon(d, i, k=1)),
    ("A_纯定义_7pct_k2", lambda d, i: cannon(d, i, k=2)),
    ("A_纯定义_7pct_k3", lambda d, i: cannon(d, i, k=3)),
    ("B_涨停版_k1", lambda d, i: cannon(d, i, k=1, require_limit=True)),
    ("B_涨停版_k2", lambda d, i: cannon(d, i, k=2, require_limit=True)),
    ("C_中间阴线_k1", lambda d, i: cannon(d, i, k=1, mid_bear=True)),
    ("D_中间阳线_k1", lambda d, i: cannon(d, i, k=1, mid_bear=False)),
    ("E_第二根量不小于第一根_k1", lambda d, i: cannon(d, i, k=1, s_vol_ge_b1=True)),
    ("F_第二根量不限_k1", lambda d, i: cannon(d, i, k=1, s_vol_ge_b1=False)),
    ("G_过顶确认_k1", lambda d, i: cannon(d, i, k=1, s_over_b1_high=True)),
    ("H_低位MA60下_k1", lambda d, i: cannon(d, i, k=1, below_ma60=True)),
    ("H_低位MA60下_涨停_k1", lambda d, i: cannon(d, i, k=1, require_limit=True, below_ma60=True)),
    ("I_涨停_中间阴线_k1", lambda d, i: cannon(d, i, k=1, require_limit=True, mid_bear=True)),
    ("J_放宽大阳5pct_k1", lambda d, i: cannon(d, i, k=1, big=0.05)),
    # 形态边界补充（2026-10-15 追加：E/G 与 A 完全同事件=第二根量恒 ≥第一根且恒过第一根最高，
    # 条件恒真已如实入档；这里补三个真正改变事件集的边界）
    ("K_放宽_不破第一根收盘_k1", lambda d, i: cannon(d, i, k=1, hold_ref="close")),
    ("L_放松_不破第一根开盘_k1", lambda d, i: cannon(d, i, k=1, hold_ref="open")),
    ("M_中间回调不限量_k1", lambda d, i: cannon(d, i, k=1, mid_vol_free=True)),
    ("N_放宽_中间不限量_实体中点_k1", lambda d, i: cannon(d, i, k=1, mid_vol_free=True,
                                                        s_vol_ge_b1=False)),
    ("O_低位MA60下_放宽5pct_k1", lambda d, i: cannon(d, i, k=1, big=0.05, below_ma60=True)),
    ("P_低位MA60下_不限量_k1", lambda d, i: cannon(d, i, k=1, mid_vol_free=True, below_ma60=True)),
]


def mk_ma60(c):
    pre = [0.0]
    for x in c:
        pre.append(pre[-1] + x)
    n = len(c)
    ma = [None] * min(60, n) + [(pre[i + 1] - pre[i - 59]) / 60 for i in range(59, n - 1)]
    ma = ma[:n]
    while len(ma) < n:
        ma.append(None)
    return ma


def stat(rs):
    if len(rs) < 30:
        return {"n": len(rs), "note": "样本不足(<30)"}
    n = len(rs)
    m = st.mean(rs)
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    aw = st.mean(wins) if wins else 0.0
    al = abs(st.mean(losses)) if losses else 0.0
    s = {"n": n, "win%": round(100 * len(wins) / n, 1), "mean%": round(100 * m, 2),
         "med%": round(100 * st.median(rs), 2),
         "赔率": round(aw / al, 2) if al > 0 else None,
         "t": round(m / (st.stdev(rs) / math.sqrt(n)), 1) if n > 1 else None}
    if n < SMALL_N:
        s["warn"] = "n<300 样本不足"
    return s


def nw_t(rs, lag):
    n = len(rs)
    if n < 30:
        return None
    m = st.mean(rs)
    dev = [x - m for x in rs]
    g0 = sum(x * x for x in dev) / n
    var = g0
    for L in range(1, lag + 1):
        if L >= n:
            break
        gl = sum(dev[k] * dev[k - L] for k in range(L, n)) / n
        var += 2 * (1 - L / (lag + 1)) * gl
    if var <= 0:
        return None
    return round(m / math.sqrt(var / n), 2)


def capacity_sim(by_date, light, cal, slots=10, hold=5, seed=11):
    """G7 容量检验：固定槽位下的资金曲线（口径对齐 law_pipeline.capacity_sim）。

    信号日收盘确认 → 次日开盘买（一字跌停已在收集时剔除）→ 入场日 +hold 日收盘卖 →
    往返 FEE → 每槽 1/slots 资金，槽满跳过（记溢出）。按信号日遍历，同日候选随机选票。
    cal = 全交易日序列（用来定位槽位释放时点，锚真实日历，禁用稀疏日历）。
    """
    rnd = Random(seed)
    di = {d: k for k, d in enumerate(cal)}
    cash = 1.0
    pos = []          # (release_idx, entry, shares)
    n_tr = n_skip = 0
    for date in cal:
        k = di[date]
        pos = [(rel, e, sh) for rel, e, sh in pos if rel > k]
        cands = by_date.get(date)
        if not cands:
            continue
        sig = [(c, i) for c, i in cands if c in light and i + hold < light[c]["n"]]
        if not sig:
            continue
        free = slots - len(pos)
        if free <= 0:
            n_skip += 1
            continue
        if len(sig) > free:
            sig = rnd.sample(sig, free)
        for code, i in sig:
            d = light[code]
            e = d["o"][i + 1]
            if e <= 0:
                continue
            alloc = 1.0 / slots
            cash += alloc * (d["c"][i + hold] / e - 1 - FEE)
            n_tr += 1
            pos.append((k + 1 + hold, e, alloc))
    yrs = len(cal) / 244
    ann = (cash ** (1 / yrs) - 1) * 100 if cash > 0 and yrs > 0 else -100.0
    return {"年化%": round(ann, 2), "总收益%": round((cash - 1) * 100, 1),
            "笔数": n_tr, "槽满跳过日": n_skip, "年数": round(yrs, 1)}


def main():
    t0 = datetime.now()
    # 全交易日历（用于近 250 日切点；从 regime 时间轴取，避免再遍历宇宙）
    cal = sorted({r["date"] for r in json.loads(TIMELINE.read_text())})
    thr250 = cal[-250] if len(cal) >= 250 else cal[0]
    regime = {r["date"]: r["regime"] for r in json.loads(TIMELINE.read_text())}
    print(f"日历 {len(cal)} 日，近250日切点={thr250}", flush=True)

    names = [v[0] for v in VARIANTS]
    acc = {v: {"all": {h: array("f") for h in HORIZONS},
               "y5": {}, "y20": {}, "seg5": {"2019-2022": array("f"), "2023-2026": array("f")},
               "reg5": {}, "q5": {}, "l250_5": array("f"), "l250_20": array("f"),
               "sig30": [], "ctl30": [], "ev5": [],
               "n_event": 0, "dropped": 0,
               "reg_trig": {},             # month -> n 触发（每票每年触发数）
               "mloss": 0, "mwin": 0} for v in names}

    # ---- G4 市值五分位（PIT：边界=上月横截面，个股取不晚于当日最近日值）----
    per_month, cap_daily = {}, {}
    for fp in sorted(CAPH.glob("*.json")):
        try:
            rows = sorted(json.loads(fp.read_text()), key=lambda r: r[0])
        except Exception:
            continue
        cap_daily[fp.stem] = ([r[0] for r in rows], [r[2] for r in rows])
        for date, _px, cap in rows:
            per_month.setdefault(date[:7], []).append(cap)
    qbounds = {}
    months = sorted(per_month)
    for kk, mm in enumerate(months):
        if kk == 0:
            qbounds[mm] = None
            continue
        caps = sorted(per_month[months[kk - 1]])
        qbounds[mm] = [caps[int(len(caps) * p)] for p in (0.2, 0.4, 0.6, 0.8)] if len(caps) >= 50 else None

    def capq(code, date):
        packed = cap_daily.get(code)
        b = qbounds.get(date[:7])
        if not packed or not b:
            return None
        dates, caps = packed
        j = bisect_right(dates, date) - 1
        if j < 0:
            return None
        return sum(caps[j] > x for x in b)

    files = sorted(KC.glob("*.json"))
    done = 0
    near250_codes = set()
    for fp in files:
        try:
            ks = json.loads(fp.read_text())
        except Exception:
            continue
        if len(ks) < 300:
            continue
        code = fp.stem
        n = len(ks)
        c = [k["close"] for k in ks]
        o = [k["open"] for k in ks]
        h = [k["high"] for k in ks]
        l = [k["low"] for k in ks]
        v = [k.get("volume", 0) for k in ks]
        dt = [k["date"] for k in ks]
        ma = mk_ma60(c)
        d = {"code": code, "c": c, "o": o, "h": h, "l": l, "v": v, "ma60": ma,
             "date": dt, "n": n}
        hi = n - HMAX - 1
        if hi <= 61:
            continue
        if dt[-1] >= thr250:
            near250_codes.add(code)
        # 位置匹配对照池（同票、按信号日所处 MA60 侧分组）
        pools = {True: [], False: []}          # True=MA60上方(高位) False=下方(低位)
        for i in range(61, hi):
            if ma[i] is None or o[i + 1] <= 0 or c[i] <= 0:
                continue
            pools[c[i] > ma[i]].append(i)
        rnd = Random(abs(hash(code)) % (2 ** 31))
        for name in names:
            a = acc[name]
            detect = dict(VARIANTS)[name]
            days = []
            for i in range(61, hi):
                if o[i + 1] <= 0 or c[i] <= 0 or c[i - 1] <= 0:
                    continue
                try:
                    hit = detect(d, i)
                except Exception:
                    hit = False
                if not hit:
                    continue
                if o[i + 1] <= c[i] * 0.905:      # 次日开盘一字跌停＝买不到
                    a["dropped"] += 1
                    continue
                days.append(i)
                a["n_event"] += 1
                a["ev5"].append((code, i, c[i + 5] / o[i + 1] - 1 - FEE if i + 5 < n else None))
                e = o[i + 1]
                for hh in HORIZONS:
                    if i + hh < n:
                        a["all"][hh].append(c[i + hh] / e - 1 - FEE)
                if i + 30 < n:
                    a["sig30"].append(c[i + 30] / e - 1 - FEE)
                    r30 = c[i + 30] / e - 1 - FEE
                    if r30 < -0.11111:
                        a["mloss"] += 1
                    else:
                        a["mwin"] += 1
                if i + 5 < n:
                    r5 = c[i + 5] / e - 1 - FEE
                    y = dt[i][:4]
                    a["y5"].setdefault(y, array("f")).append(r5)
                    a["seg5"]["2019-2022" if dt[i] < "2023" else "2023-2026"].append(r5)
                    a["reg5"].setdefault(regime.get(dt[i], "?"), array("f")).append(r5)
                    q = capq(code, dt[i])
                    if q is not None:
                        a["q5"].setdefault(q, array("f")).append(r5)
                    if dt[i] >= thr250:
                        a["l250_5"].append(r5)
                if i + 20 < n:
                    r20 = c[i + 20] / e - 1 - FEE
                    a["y20"].setdefault(dt[i][:4], array("f")).append(r20)
                    if dt[i] >= thr250:
                        a["l250_20"].append(r20)
            # 位置匹配对照（同票同 MA60 侧，抽等量随机日）
            if days:
                lo = [i for i in days if not (c[i] > ma[i])]
                hi_ = [i for i in days if c[i] > ma[i]]
                for pool, k_ in ((pools[False], len(lo)), (pools[True], len(hi_))):
                    if pool and k_:
                        for i in rnd.sample(pool, min(k_, len(pool))):
                            e = o[i + 1]
                            if e <= 0:
                                continue
                            if i + 30 < n:
                                a["ctl30"].append(c[i + 30] / e - 1 - FEE)
        done += 1
        if done % 1000 == 0:
            print(f"  {done}/{len(files)} 票  {datetime.now()-t0}", flush=True)

    # 近 250 日窗口（触发频率分母 + 窗口切片）
    recent = {d for d in cal if d >= thr250}
    n_codes_recent = len(near250_codes)
    print(f"  近250日有 bar 的票数={n_codes_recent}，窗口交易日={len(recent)}", flush=True)
    out = {"generated_at": datetime.now(timezone.utc).isoformat(), "universe_files": len(files),
           "scanned": done, "entry": "next_open", "fee": FEE, "near250_from": thr250,
           "definition": "两根放量大阳(>=7%或涨停)夹1-3日缩量回调不破第一根实体中点",
           "note": "容量口径=每日候选随机选票、无限资金参照（研究用，非 law_pipeline 的槽位模拟）",
           "variants": {}}
    cap_cache = {}
    for name in names:
        a = acc[name]
        r = {"事件数": a["n_event"], "买不到剔除": a["dropped"]}
        if not a["n_event"]:
            r["结论"] = "零事件"
            out["variants"][name] = r
            continue
        # 触发频率：全样本事件数 / 扫描票数 / 全样本年数（每票每年）
        yrs_all = len(cal) / 244
        r["每票每年触发"] = round(a["n_event"] / max(1, done) / max(0.01, yrs_all), 3) \
            if a["n_event"] else 0
        r["全市场每年触发"] = round(a["n_event"] / max(0.01, yrs_all)) if a["n_event"] else 0
        r["近250日触发"] = sum(1 for mm in a["reg_trig"] if mm >= thr250[:7]) if a["n_event"] else 0
        tab = {}
        for hh in HORIZONS:
            s = stat(a["all"][hh])
            s["t_NW"] = nw_t(a["all"][hh], hh)
            tab[f"T+{hh}"] = s
        r["horizon"] = tab
        r["双段T+5"] = {k2: stat(v2) for k2, v2 in a["seg5"].items()}
        r["分年T+5"] = {y: stat(v2) for y, v2 in sorted(a["y5"].items())}
        r["分年T+20"] = {y: stat(v2) for y, v2 in sorted(a["y20"].items())}
        r["regimeT+5"] = {k2: stat(v2) for k2, v2 in sorted(a["reg5"].items())}
        r["市值五分位T+5"] = {f"Q{q}": stat(v2) for q, v2 in sorted(a["q5"].items())}
        r["近250日T+5"] = stat(a["l250_5"])
        r["近250日T+20"] = stat(a["l250_20"])
        # 成本压力
        e5 = [x[2] for x in a["ev5"] if x[2] is not None]
        r["成本压力"] = {f"{f*100:.2f}%": stat([x + FEE - f for x in e5])
                       for f in (FLAT_RT, 0.003, 0.005)}
        # 位置匹配（T+30，与对照口径一致）
        if len(a["sig30"]) >= 30 and len(a["ctl30"]) >= 30:
            r["位置匹配边际pp_T30"] = round(100 * (st.mean(a["sig30"]) - st.mean(a["ctl30"])), 2)
        # 多倍损失：T+30 跌幅超 -10% 的比例（-0.11111 ≈ 跌到 0.88889，与 G7 口径对齐）
        tot = a["mloss"] + a["mwin"]
        r["多倍损失占比%"] = round(100 * a["mloss"] / tot, 1) if tot else None
        r["T30样本"] = tot

        # ---- 闸门（对齐 law_pipeline.submit_gate）----
        sh = tab["T+5"]                      # tag T+5 统计（含 t_NW）
        seg5 = r["双段T+5"]
        reg5 = r["regimeT+5"]
        q5s = r["市值五分位T+5"]
        gates = {
            "G1_tNW≥3": abs(sh.get("t_NW") or 0) >= 3.0,
            "G2_时间分段两段同正": all(v2 and v2.get("mean%", -9) > 0 for v2 in seg5.values()),
            "G3_regime≥3/4": (sum(1 for v2 in reg5.values() if v2.get("mean%", -9) > 0) >= max(3, len(reg5) - 1))
                              if len(reg5) >= 3 else (bool(reg5) and all(v2.get("mean%", -9) > 0 for v2 in reg5.values())),
            "G4_市值≥4/5": (sum(1 for v2 in q5s.values() if v2.get("mean%", -9) > 0) >= len(q5s) - 1) if q5s else False,
            "G5_位置匹配边际>0": bool(a["sig30"]) and bool(a["ctl30"]) and st.mean(a["sig30"]) - st.mean(a["ctl30"]) > 0,
            "G6_0.30%成本仍正": (r["成本压力"].get("0.30%") or {}).get("mean%", -9) > 0,
            "G7_槽位10年化>0": None,   # 推后由槽位模拟填（对齐 law_pipeline: cap1["年化%"] > 0）
        }
        r["闸门"] = {k2: ("✅" if v2 else "❌") if v2 is not None else "…" for k2, v2 in gates.items()}
        r["判决"] = "REJECT" if any(v2 is False for v2 in gates.values()) else "待G7"
        out["variants"][name] = r
        print(f"[{name}] n={a['n_event']} 剔{a['dropped']} T+5={tab['T+5'].get('mean%')}% "
              f"胜{tab['T+5'].get('win%')}% 位置匹配T30={r.get('位置匹配边际pp_T30')} "
              f"闸门={r['闸门']} → {r['判决']}", flush=True)

    # ---- G7 容量（槽位约束资金曲线）：对事件数 ≥300 的变体逐个跑（共用一次轻量重载）----
    # 槽位 10 / hold=5 / 次日开盘买，锚近 250 日真实日历（内存可控）。
    big = [nm for nm in names if len(acc[nm]["all"][5]) >= SMALL_N]
    if big:
        light = {}
        for code in near250_codes:
            fp = KC / f"{code}.json"
            if not fp.exists():
                continue
            try:
                ks = json.loads(fp.read_text())
            except Exception:
                continue
            cs = [k["close"] for k in ks]
            light[code] = {"code": code, "c": cs, "o": [k["open"] for k in ks],
                           "v": [k.get("volume", 0) for k in ks],
                           "h": [k["high"] for k in ks], "l": [k["low"] for k in ks],
                           "ma60": mk_ma60(cs), "date": [k["date"] for k in ks], "n": len(ks)}
        print(f"  G7 轻量宇宙: {len(light)} 票（近250日）", flush=True)
        recent_sorted = sorted(recent)
        for nm in big:
            detect = dict(VARIANTS)[nm]
            by_date = {}
            for code, d in light.items():
                n2 = d["n"]
                for i in range(61, n2 - HMAX - 1):
                    if d["o"][i + 1] <= 0 or d["c"][i] <= 0 or d["c"][i - 1] <= 0:
                        continue
                    try:
                        if not detect(d, i):
                            continue
                    except Exception:
                        continue
                    if d["o"][i + 1] <= d["c"][i] * 0.905:
                        continue
                    by_date.setdefault(d["date"][i], []).append((code, i))
            cap = capacity_sim(by_date, light, recent_sorted, slots=10, hold=5, seed=11)
            out["variants"][nm]["G7_槽10_K1"] = cap
            g = out["variants"][nm]["闸门"]
            ok = bool(cap["年化%"] > 0)
            g["G7_槽位10年化>0"] = "✅" if ok else "❌"
            out["variants"][nm]["判决"] = "PASS" if all(x == "✅" for x in g.values()) else "REJECT"
            print(f"    G7[{nm}] {cap} → {out['variants'][nm]['判决']}", flush=True)
        del light

    dst = ROOT / f"data/dual_cannon_study_{datetime.now().strftime('%Y%m%d')}.json"
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("saved", dst, f"elapsed={int((datetime.now()-t0).total_seconds())}s", flush=True)


if __name__ == "__main__":
    main()
