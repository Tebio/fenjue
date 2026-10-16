#!/usr/bin/env python3
"""engine/calendar_scan.py — 玄学/日历效应普查（2026-10-16 卡 t_44804c74，AGENTS #290）

用户好奇心驱动（点名「天干地支五行八卦」的严肃化版），成本 2 小时级，证伪亦交付。

=========================== 预登记（跑前写死，不许事后改） ===========================
宇宙 = 主板 big_kcache 全量（load_universe，≥300 bar），2019-01-02 → 2026-10-15。
日收益 = 全宇宙等权 close/close-1（|r|>21% 判脏数据剔除；当日覆盖 <500 只的日子剔除）。
交易日历 = 000001（平安银行）bar 日期（活跃参照股锚定，禁 union 全宇宙尾部）。

五个家族 × 窗口（交易日 mask）：
  F1 moon_full : 满月（天文望，BJT 日）±2 自然日内的交易日
  F2 moon_new  : 新月（天文朔，BJT 日）±2 自然日内的交易日
  F3 term5     : 24 节气各自锚定「节气日之后第一个交易日」起连续 5 个交易日（T+1..T+5）
  F4 lunar_1   : 农历初一（=天文朔 BJT 日）当日或之后首个交易日（单日）
  F4 lunar_15  : 农历十五（=初一+14）当日或之后首个交易日（单日）
  F4 lunar_both: 两者合并
  F5 weekday   : 周一~周五 五个桶（每桶 vs 其余）
  F6 tom       : 每月最后 1 个交易日 + 次月前 3 个交易日（McConnell-Xu TOM 口径）
  F6 tom_end   : 仅每月最后 1 个交易日
  F6 tom_start : 仅每月前 3 个交易日

统计量 = 窗口日均收益 − 非窗口日均收益（市场级；日历效应本身就是 beta 层问题）。
推断 = 双侧 NW t（lag=10，两组分别算长程方差）+ 1000 次置换检验（结构保持）：
  moon/lunar/term/tom：按年抽取同数量伪锚日，同规则扩窗；
  weekday：周内（ISO week）打乱星期标签，保持假期结构与自相关。
  p2 = (1 + #{|placebo| >= |real|}) / (1 + 1000)。
三口径（禁裸均值，每口径报 NW t）：FULL 全段 / FRONT 2019-01→2022-12 / RECENT 2024-10-16→2026-10-15。

存活判据（预登记，全过才进六闸门终审）：
  ① FULL |t_NW| ≥ 3.0（Harvey 多重检验门槛，本次普查正式假设数=14）
  ② FRONT 与 RECENT 两口径同号
  ③ 置换 p2 ≤ 0.05
存活 → 检测器注册进 law_pipeline REGISTRY → submit 六闸门（含位置匹配对照 +
  日历时间 DSR trials=7491 保守口径）→ 可执行口径 + 与存活线叠加测试。
全灭 → REJECT 进坟场，「玄学线销案」本身即交付物。
==================================================================================

天文算法（零依赖，日级精度足够 ±2 日窗）：
  节气 = 视太阳黄经过 15° 整数倍（低精度公式误差 ~0.01° ≈ 15 分钟）；
  朔望 = Meeus 低精度（主项+14 修正项，误差 <0.1 日）。BJT 日界。
  校验锚：立春 2024-02-04 / 2026-02-04，清明 2024-04-04，冬至 2024-12-21，
          大寒 2025-01-20，朔 2024-02-10（春节）/2025-01-29（春节）/2026-02-17（春节），
          望 2024-09-18（中秋次夜）。
"""
import json, math, random, statistics as st, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import law_pipeline as lp

ROOT = Path("/opt/data/fenjue")
OUT = ROOT / "data/research"
PERMS = 1000
SEED = 20261016
NW_LAG = 10
CUTS = {"full": ("0000-00-00", "9999-99-99"),
        "front": ("0000-00-00", "2022-12-31"),
        "recent": ("2024-10-16", "9999-99-99")}

# ---------------- 天文：视太阳黄经 → 节气日 ----------------

def _sun_lon(days):  # days since J2000.0 (2000-01-01 12:00 TT)，低精度视黄经
    L = (280.460 + 0.9856474 * days) % 360.0
    g = math.radians((357.528 + 0.9856003 * days) % 360.0)
    return (L + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g)) % 360.0


def _date_to_days(y, m, d):  # 简化：用序数日
    import datetime as _dt
    return (_dt.date(y, m, d) - _dt.date(2000, 1, 1)).days - 0.5  # 当日 00:00 TT ≈


def _days_to_date(days):
    import datetime as _dt
    return _dt.date(2000, 1, 1) + _dt.timedelta(days=days + 0.5)


TERM_NAMES = {285: "小寒", 300: "大寒", 315: "立春", 330: "雨水", 345: "惊蛰", 0: "春分",
              15: "清明", 30: "谷雨", 45: "立夏", 60: "小满", 75: "芒种", 90: "夏至",
              105: "小暑", 120: "大暑", 135: "立秋", 150: "处暑", 165: "白露", 180: "秋分",
              195: "寒露", 210: "霜降", 225: "立冬", 240: "小雪", 255: "大雪", 270: "冬至"}


def solar_terms(y0=2018, y1=2027):
    """扫描太阳黄经过 15° 整数倍的 BJT 日期。返回 [(date_str, lon_deg)] 按时间序。"""
    out = []
    step = 0.25
    d0, d1 = _date_to_days(y0, 11, 20), _date_to_days(y1, 1, 10)
    prev_lon, prev_d = _sun_lon(d0), d0
    targets = set(TERM_NAMES)
    d = d0 + step
    while d <= d1:
        lon = _sun_lon(d)
        for t in targets:
            # 过 target 经度（处理 345→0 回绕）
            a, b = (prev_lon - t) % 360.0, (lon - t) % 360.0
            if a > b and (a - b) > 180:  # 黄经递增跨过 target（359.x → 0.x 回绕签名）
                frac = (360.0 - a) / ((360.0 - a) + b)
                cross = prev_d + frac * (d - prev_d)
                # TT→BJT：+8h；ΔT~69s 忽略（日级无影响）
                dt = _days_to_date(cross + 8.0 / 24.0)
                out.append((dt.isoformat(), t))
        prev_lon, prev_d = lon, d
        d += step
    out.sort()
    # 黄经单调，同一 target 一年只跨一次；扫描窗含相邻年末的重复 target，保留全部（按日期唯一定位）
    return out


# ---------------- 天文：朔望（Meeus 低精度） ----------------

def _moon_jd(k):
    """k 整数=朔，k+0.5=望。返回 JDE(TT)。"""
    T = k / 1236.85
    JDE = (2451550.09765 + 29.530588853 * k + 0.0001337 * T * T
           - 0.000000150 * T ** 3 + 0.00000000073 * T ** 4)
    M = math.radians((2.5534 + 29.10535669 * k - 0.0000218 * T * T
                      - 0.000000011 * T ** 3) % 360.0)
    Mm = math.radians((201.5643 + 385.81693528 * k + 0.0107438 * T * T
                       + 0.00001239 * T ** 3 - 0.000000058 * T ** 4) % 360.0)
    F = math.radians((160.7108 + 390.67050284 * k - 0.0016118 * T * T
                      - 0.00000227 * T ** 3 + 0.000000011 * T ** 4) % 360.0)
    Om = math.radians((124.7746 - 1.56375580 * k + 0.0020691 * T * T
                       + 0.00000215 * T ** 3) % 360.0)
    JDE += (-0.40720 * math.sin(Mm) + 0.17241 * math.sin(M) + 0.01608 * math.sin(2 * Mm)
            + 0.01039 * math.sin(2 * F) + 0.00739 * math.sin(Mm - M)
            - 0.00514 * math.sin(Mm + M) + 0.00208 * math.sin(2 * M)
            - 0.00111 * math.sin(Mm - 2 * F) - 0.00057 * math.sin(Mm + 2 * F)
            + 0.00056 * math.sin(2 * Mm + M) - 0.00042 * math.sin(3 * Mm)
            + 0.00042 * math.sin(Mm + 2 * F) + 0.00038 * math.sin(Mm - 2 * F)
            - 0.00024 * math.sin(2 * Mm - M) - 0.00017 * math.sin(Om)
            - 0.00007 * math.sin(Mm + 2 * M) + 0.00004 * math.sin(2 * Mm - 2 * F))
    return JDE


def _jd_to_bjt_date(jd):
    import datetime as _dt
    # J2000.0 = JD 2451545.0 = 2000-01-01 12:00 TT；ΔT≈69s（2019-2026）忽略
    # BJT = TT + 8h；日期 = 2000-01-01 + floor(d + 0.5(正午纪元→午夜) + 1/3(8h))
    days = jd - 2451545.0
    return (_dt.date(2000, 1, 1) + _dt.timedelta(days=math.floor(days + 0.5 + 8.0 / 24.0))).isoformat()


def moon_phases(y0=2018, y1=2027):
    """返回 (new_dates, full_dates)，BJT 日。"""
    import datetime as _dt
    d0 = (_dt.date(y0, 11, 15) - _dt.date(2000, 1, 6)).days
    k0 = int(d0 / 29.530588853) - 2
    news, fulls = [], []
    k = k0
    while True:
        jd_n = _moon_jd(k)
        dn = _jd_to_bjt_date(jd_n)
        if dn > f"{y1}-02-01":
            break
        news.append(dn)
        fulls.append(_jd_to_bjt_date(_moon_jd(k + 0.5)))
        k += 1
    return news, fulls


# ---------------- 宇宙日收益 ----------------

def build_daily(stocks, calendar):
    """返回 (u, cnt)：全宇宙等权 close/close 日收益与覆盖数，按 calendar 对齐。"""
    cidx = {d: t for t, d in enumerate(calendar)}
    N = len(calendar)
    sums, cnt = [0.0] * N, [0] * N
    for code, d in stocks.items():
        lut = {dt: i for i, dt in enumerate(d["date"])}
        c = d["c"]
        for t in range(1, N):
            i1 = lut.get(calendar[t])
            if i1 is None or i1 == 0:
                continue
            if d["date"][i1 - 1] != calendar[t - 1]:
                continue  # 非相邻交易日（停牌/缺口），跳过
            c0, c1 = c[i1 - 1], c[i1]
            if c0 <= 0 or c1 <= 0:
                continue
            r = c1 / c0 - 1.0
            if abs(r) > 0.21:
                continue  # 脏数据守卫
            sums[t] += r
            cnt[t] += 1
    u = [sums[t] / cnt[t] if cnt[t] >= 500 else None for t in range(N)]
    return u, cnt


# ---------------- 统计引擎 ----------------

def _lrv(x, lag=NW_LAG):
    n = len(x)
    m = st.mean(x)
    l = sum((v - m) ** 2 for v in x) / n
    for k in range(1, min(lag, n - 2) + 1):
        gk = sum((x[t] - m) * (x[t - k] - m) for t in range(k, n)) / n
        l += 2 * (1 - k / (lag + 1)) * gk
    return l


def diff_stat(u, mask, idx):
    """窗口 vs 非窗口 日均收益差 + NW t。mask/set 为交易日下标集合。"""
    w = [u[t] for t in idx if t in mask and u[t] is not None]
    o = [u[t] for t in idx if t not in mask and u[t] is not None]
    if len(w) < 30 or len(o) < 30:
        return None
    d = st.mean(w) - st.mean(o)
    v = _lrv(w) / len(w) + _lrv(o) / len(o)
    return {"diff_bp": round(d * 1e4, 2), "t_nw": round(d / math.sqrt(v), 2) if v > 0 else None,
            "n_win": len(w), "win_mean_bp": round(st.mean(w) * 1e4, 2),
            "rest_mean_bp": round(st.mean(o) * 1e4, 2)}


def perm_p(u, idx, make_mask, real_diff):
    """1000 次结构保持置换，返回双侧 p 与安慰剂分布分位。"""
    rnd = random.Random(SEED)
    ge = 0
    placebos = []
    valid = [t for t in idx if u[t] is not None]
    for _ in range(PERMS):
        mk = make_mask(rnd, valid)
        w = [u[t] for t in valid if t in mk]
        o = [u[t] for t in valid if t not in mk]
        if len(w) < 30 or len(o) < 30:
            continue
        pd_ = st.mean(w) - st.mean(o)
        placebos.append(pd_)
        if abs(pd_) >= abs(real_diff):
            ge += 1
    placebos.sort()
    p2 = (1 + ge) / (1 + len(placebos))
    pct = sum(1 for x in placebos if x < real_diff) / len(placebos) if placebos else None
    return {"p2": round(p2, 4), "pct": round(pct, 4) if pct is not None else None,
            "pl_mean_bp": round(st.mean(placebos) * 1e4, 2) if placebos else None,
            "pl_sd_bp": round(st.stdev(placebos) * 1e4, 2) if len(placebos) > 1 else None}


# ---------------- 窗口构建 ----------------

def _tday_on_or_after(cal, cidx, date_str):
    """date_str 当日或之后首个交易日下标，无则 None。"""
    import bisect
    j = bisect.bisect_left(cal, date_str)
    return j if j < len(cal) else None


def mask_pm2(cal, cidx, dates):
    """相位 BJT 日 ±2 自然日窗内的交易日。"""
    import datetime as _dt
    mk = set()
    for ds in dates:
        dd = _dt.date.fromisoformat(ds)
        for k in range(-2, 3):
            t = cidx.get((dd + _dt.timedelta(days=k)).isoformat())
            if t is not None:
                mk.add(t)
    return mk


def mask_term5(cal, terms):
    """每个节气：锚=节气日或之后首个交易日，窗=锚起 5 个交易日。"""
    mk, anchors = set(), []
    for ds, lon in terms:
        a = _tday_on_or_after(cal, {d: i for i, d in enumerate(cal)}, ds)
        if a is None:
            continue
        anchors.append((ds, TERM_NAMES[lon], a))
        for k in range(a, min(a + 5, len(cal))):
            mk.add(k)
    return mk, anchors


def mask_single_days(cal, cidx, dates):
    mk = set()
    for ds in dates:
        t = _tday_on_or_after(cal, cidx, ds)
        if t is not None:
            mk.add(t)
    return mk


def mask_tom(cal, mode="both"):
    import collections
    by_month = collections.defaultdict(list)
    for t, ds in enumerate(cal):
        by_month[ds[:7]].append(t)
    months = sorted(by_month)
    mk = set()
    for j, m in enumerate(months):
        if mode in ("both", "end"):
            mk.add(by_month[m][-1])
        if mode == "start":
            mk.update(by_month[m][:3])
        elif mode == "both" and j + 1 < len(months):
            mk.update(by_month[months[j + 1]][:3])
    return mk


# ---------------- 置换 mask 生成器 ----------------

def _natural_days_by_year(cal):
    """日历跨度内全部自然日按年分组（伪锚抽样池——真实相位/节气落在任意自然日）。"""
    import datetime as _dt
    g = {}
    d = _dt.date.fromisoformat(cal[0])
    d1 = _dt.date.fromisoformat(cal[-1])
    while d <= d1:
        g.setdefault(str(d.year), []).append(d.isoformat())
        d += _dt.timedelta(days=1)
    return g


def perm_mask_dates(rnd, nat, n_by_year, expand_dates):
    """按年抽同数量伪锚自然日，走与真实锚完全相同的「日期→交易日窗」映射。"""
    fake = []
    for yr, n in n_by_year.items():
        pool = nat.get(yr, [])
        if pool:
            fake += rnd.sample(pool, min(n, len(pool)))
    return expand_dates(fake)


def make_perm_weekday(rnd, valid, cal, bucket):
    """周内打乱星期标签：把每个 ISO 周的交易日随机指派到周一~周五，统计目标桶。"""
    import collections, datetime as _dt
    weeks = collections.defaultdict(list)
    for t in valid:
        weeks[_dt.date.fromisoformat(cal[t]).isocalendar()[:2]].append(t)
    mk = set()
    for wk, days in weeks.items():
        labels = rnd.sample(range(5), min(5, len(days)))
        for t, lb in zip(sorted(days), labels):
            if lb == bucket:
                mk.add(t)
    return mk


# ---------------- 主流程 ----------------

def main():
    print("[1/5] load universe ...", flush=True)
    stocks = lp.load_universe()
    n_uni = len(stocks)
    ref = stocks.get("000001")
    calendar = ref["date"]
    cidx = {d: i for i, d in enumerate(calendar)}
    N = len(calendar)
    print(f"  universe={len(stocks)} stocks, calendar={calendar[0]}..{calendar[-1]} ({N} days)")

    print("[2/5] astronomy ...", flush=True)
    terms = solar_terms()
    news, fulls = moon_phases()
    # 校验锚（容差 ±1 日，打印实际值）
    def _near(lst, expect, label):
        hit = min(lst, key=lambda x: abs(_days_between(x, expect)))
        off = abs(_days_between(hit, expect))
        flag = "OK" if off <= 1 else "!!MISMATCH"
        print(f"  astro-check {label}: expect~{expect} got {hit} ({flag})")
        return off <= 1
    term_map = {}
    for ds, lon in terms:
        term_map.setdefault(TERM_NAMES[lon], []).append(ds)
    ok = True
    ok &= _near(term_map["立春"], "2024-02-04", "立春2024")
    ok &= _near(term_map["立春"], "2026-02-04", "立春2026")
    ok &= _near(term_map["清明"], "2024-04-04", "清明2024")
    ok &= _near(term_map["冬至"], "2024-12-21", "冬至2024")
    ok &= _near(term_map["大寒"], "2025-01-20", "大寒2025")
    ok &= _near(news, "2024-02-10", "朔2024春节")
    ok &= _near(news, "2025-01-29", "朔2025春节")
    ok &= _near(news, "2026-02-17", "朔2026春节")
    ok &= _near(fulls, "2024-09-18", "望2024中秋")
    if not ok:
        print("FATAL: astronomy validation failed"); sys.exit(1)

    # 农历十五 = 初一+14
    import datetime as _dt
    lunar15 = [(_dt.date.fromisoformat(x) + _dt.timedelta(days=14)).isoformat() for x in news]

    print("[3/5] daily universe returns ...", flush=True)
    u, cnt = build_daily(stocks, calendar)
    del stocks  # 日收益序列已成型，宇宙字典立即释放（15GB 机 OOM 纪律）
    import gc; gc.collect()
    valid_all = [t for t in range(N) if u[t] is not None]
    print(f"  valid days={len(valid_all)}, median coverage={sorted(cnt)[N//2]}")

    # 家族 mask
    fam_masks = {
        "moon_full_pm2": mask_pm2(calendar, cidx, fulls),
        "moon_new_pm2": mask_pm2(calendar, cidx, news),
        "lunar_1": mask_single_days(calendar, cidx, news),
        "lunar_15": mask_single_days(calendar, cidx, lunar15),
        "term5": None,  # 下面填
        "tom": mask_tom(calendar, "both"),
        "tom_end": mask_tom(calendar, "end"),
        "tom_start": mask_tom(calendar, "start"),
    }
    mk_t5, anchors_t5 = mask_term5(calendar, terms)
    fam_masks["term5"] = mk_t5
    fam_masks["lunar_both"] = fam_masks["lunar_1"] | fam_masks["lunar_15"]
    # weekday 桶
    wd_masks = {f"weekday_{b}": {t for t in range(N)
                if _dt.date.fromisoformat(calendar[t]).weekday() == b} for b in range(5)}

    # 按年锚数量（置换用；伪锚=自然日抽样，走同一映射）
    nat = _natural_days_by_year(calendar)

    def _count_by_year(dates):
        g = {}
        for ds in dates:
            g[ds[:4]] = g.get(ds[:4], 0) + 1
        return g

    ex_pm2 = lambda ds: mask_pm2(calendar, cidx, ds)
    ex_single = lambda ds: mask_single_days(calendar, cidx, ds)

    def _ex_k(k):
        def ex(ds):
            mk = set()
            for x in ds:
                a = _tday_on_or_after(calendar, cidx, x)
                if a is not None:
                    for j in range(a, min(a + k, N)):
                        mk.add(j)
            return mk
        return ex

    n_months_by_year = _count_by_year([m + "-01" for m in
                                       sorted({calendar[t][:7] for t in range(N)})])
    perm_gens = {
        "moon_full_pm2": (lambda rnd: perm_mask_dates(rnd, nat, _count_by_year(fulls), ex_pm2)),
        "moon_new_pm2": (lambda rnd: perm_mask_dates(rnd, nat, _count_by_year(news), ex_pm2)),
        "lunar_1": (lambda rnd: perm_mask_dates(rnd, nat, _count_by_year(news), ex_single)),
        "lunar_15": (lambda rnd: perm_mask_dates(rnd, nat, _count_by_year(lunar15), ex_single)),
        "lunar_both": (lambda rnd: perm_mask_dates(rnd, nat,
                       {y: _count_by_year(news).get(y, 0) + _count_by_year(lunar15).get(y, 0)
                        for y in nat}, ex_single)),
        "term5": (lambda rnd: perm_mask_dates(rnd, nat,
                  _count_by_year([ds for ds, _ in terms]), _ex_k(5))),
        "tom": (lambda rnd: perm_mask_dates(rnd, nat, n_months_by_year, _ex_k(4))),
        "tom_end": (lambda rnd: perm_mask_dates(rnd, nat, n_months_by_year, _ex_k(1))),
        "tom_start": (lambda rnd: perm_mask_dates(rnd, nat, n_months_by_year, _ex_k(3))),
    }

    print("[4/5] census + permutation (1000x) ...", flush=True)
    results = {}
    all_fams = list(fam_masks.items()) + list(wd_masks.items())
    cut_idx = {name: [t for t in valid_all if lo <= calendar[t] <= hi]
               for name, (lo, hi) in CUTS.items()}
    years = sorted({calendar[t][:4] for t in valid_all})
    for fname, mk in all_fams:
        row = {"window_days": len(mk)}
        for cname, idx in cut_idx.items():
            s = diff_stat(u, mk, idx)
            if s:
                row[cname] = s
        # 分年验尸（金格必须过分年验尸——聚合均值可以掩盖「edge 全来自某一年」）
        row["by_year"] = {}
        for yr in years:
            s = diff_stat(u, mk, [t for t in valid_all if calendar[t].startswith(yr)])
            row["by_year"][yr] = round(s["diff_bp"], 1) if s else None
        if "full" in row:
            if fname.startswith("weekday_"):
                b = int(fname[-1])
                gen = lambda rnd, valid, b=b: make_perm_weekday(rnd, valid, calendar, b)
            else:
                g0 = perm_gens[fname]
                gen = lambda rnd, valid, g0=g0: g0(rnd)
            row["perm"] = perm_p(u, cut_idx["full"], gen, row["full"]["diff_bp"] / 1e4)
        results[fname] = row
        f = row.get("full", {})
        print(f"  {fname:16s} days={row['window_days']:4d} full={f.get('diff_bp')}bp "
              f"t={f.get('t_nw')} front_t={(row.get('front') or {}).get('t_nw')} "
              f"recent_t={(row.get('recent') or {}).get('t_nw')} p2={(row.get('perm') or {}).get('p2')}")

    print("[5/5] detail: per-term & per-weekday distribution ...", flush=True)
    # 节气逐名：锚后 5 日窗口日均 − 全样本日均（描述性，n=8/名）
    term_detail = {}
    overall_mean = st.mean([u[t] for t in valid_all])
    for name in TERM_NAMES.values():
        vals = []
        for ds, nm, a in anchors_t5:
            if nm != name:
                continue
            w = [u[k] for k in range(a, min(a + 5, N)) if u[k] is not None]
            if len(w) == 5:
                vals.append(st.mean(w) - overall_mean)
        if vals:
            term_detail[name] = {"n": len(vals), "mean_bp": round(st.mean(vals) * 1e4, 1),
                                 "med_bp": round(st.median(vals) * 1e4, 1),
                                 "win%": round(100 * sum(v > 0 for v in vals) / len(vals), 0)}
    wd_names = ["Mon", "Tue", "Wed", "Thu", "Fri"]
    wd_detail = {wd_names[b]: {"mean_bp": round(st.mean([u[t] for t in wd_masks[f"weekday_{b}"]
                                 if u[t] is not None]) * 1e4, 2)}
                 for b in range(5)}

    # 存活判定（预登记三判据）
    survivors = []
    for fname, row in results.items():
        f, fr, rc = row.get("full"), row.get("front"), row.get("recent")
        if not (f and fr and rc and row.get("perm")):
            continue
        if (abs(f["t_nw"] or 0) >= 3.0
                and (f["diff_bp"] > 0) == (fr["diff_bp"] > 0) == (rc["diff_bp"] > 0)
                and row["perm"]["p2"] <= 0.05):
            survivors.append(fname)
    print(f"  SURVIVORS: {survivors or 'NONE — REJECT 全灭'}")

    out = {"_meta": {"generated_at": _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=8))).isoformat(),
                     "owner": "engine.calendar_scan", "data_snapshot": calendar[-1],
                     "inputs": ["data/big_kcache", "engine/law_pipeline.load_universe"],
                     "params_hash": f"perms{PERMS}_seed{SEED}_nw{NW_LAG}",
                     "hypotheses": 14, "preregistered": True},
           "calendar": [calendar[0], calendar[-1]], "universe_n": n_uni,
           "results": results, "term_detail": term_detail, "weekday_detail": wd_detail,
           "survivors": survivors}
    OUT.mkdir(parents=True, exist_ok=True)
    fp = OUT / f"calendar_scan_{calendar[-1].replace('-', '')}.json"
    tmp = fp.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    tmp.replace(fp)  # 原子写（I0）
    print(f"DONE -> {fp}", flush=True)


def _days_between(a, b):
    import datetime as _dt
    return (_dt.date.fromisoformat(a) - _dt.date.fromisoformat(b)).days


if __name__ == "__main__":
    main()
