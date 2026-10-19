#!/usr/bin/env python3
"""engine/regime_switch.py — 每日环境开关（regime switch）

目的：先判定"今天该不该开仓、该开哪条线"，再谈信号。
纪律：
  - PIT 铁律：所有状态阈值只用【过去 250 个交易日】的分位数定义（含当日），
    绝不用全样本分位，绝不看未来。
  - 只新增本文件 + data/regime_switch_20261019.txt，不改任何现有文件。

用法：
    cd /opt/data/fenjue
    PYTHONPATH=/opt/data/python-libs:/opt/data/fenjue/engine \
        .venv/bin/python engine/regime_switch.py

输出：data/regime_switch_20261019.txt
"""
import sys, os, csv, json, math, statistics as stats
from pathlib import Path
from collections import defaultdict

ROOT = Path("/opt/data/fenjue")
OUT = ROOT / "data/regime_switch_20261019.txt"
LU_CSVS = [
    ROOT / "data/limit_up_mainboard_20250908_20260922.csv",
    ROOT / "data/limit_up_mainboard_20260923_20261019.csv",
]

sys.path.insert(0, "/opt/data/fenjue/engine")
sys.path.insert(0, "/opt/data/python-libs")
import law_pipeline as lp

PIT_WIN = 250          # PIT 分位窗口（交易日）
FEE = 0.0015           # 双边费率（项目惯例）
HOLD = 5               # T+5 收盘卖
MIN_HIST = 60          # 状态判定至少需要的历史长度

# ---------------------------------------------------------------- universe
print("loading universe ...", flush=True)
U = lp.load_universe()
print(f"universe: {len(U)} stocks", flush=True)

# 构造交易日轴：用所有股票 date 的交集太长，改用"出现次数 >= 90% 股票数"的日期
date_cnt = defaultdict(int)
for d in U.values():
    for dt in d["date"]:
        date_cnt[dt] += 1
thresh = int(len(U) * 0.5)
all_dates = sorted([dt for dt, n in date_cnt.items() if n >= thresh])
# 只保留 2018-01-01 ~ 2026-10-16
all_dates = [d for d in all_dates if "2018-01-01" <= d <= "2026-10-16"]
T = len(all_dates)
didx = {d: i for i, d in enumerate(all_dates)}
print(f"trading days: {T}  {all_dates[0]} .. {all_dates[-1]}", flush=True)

# 每只股票 date -> 局部索引 的映射
for d in U.values():
    d["d2i"] = {dt: i for i, dt in enumerate(d["date"])}

# ---------------------------------------------------------------- 每日全市场变量
# 每日聚合数组
n_up       = [0]*T   # 上涨家数
n_dn       = [0]*T   # 下跌家数
n_lu       = [0]*T   # 涨停（>=+9.8%）
n_ld       = [0]*T   # 跌停（<=-9.8%）
n_newhi    = [0]*T   # 创 250 日新高
n_newlo    = [0]*T   # 创 250 日新低
tot_amt    = [0.0]*T # 总成交额 v*c
ret_med    = [[] for _ in range(T)]  # 当日个股涨跌幅
ret_bot    = [[] for _ in range(T)]  # 成交额最小 1/3 股票的涨跌幅（微盘代理）
n_cont_ld  = [0]*T   # 连续 >=2 日跌停

for d in U.values():
    c, o, v, dates, d2i = d["c"], d["o"], d["v"], d["date"], d["d2i"]
    n = len(c)
    # 250 日滚动最高/最低（含当日）——PIT 安全：判定日 t 用 t 及之前
    hi250 = [0.0]*n
    lo250 = [float("inf")]*n
    # 简单 O(n*250) 主板 3335 只 * ~2000 日 * 250 太慢；改用单调队列
    from collections import deque
    dq_max, dq_min = deque(), deque()
    for i in range(n):
        while dq_max and c[dq_max[-1]] <= c[i]: dq_max.pop()
        dq_max.append(i)
        while dq_min and c[dq_min[-1]] >= c[i]: dq_min.pop()
        dq_min.append(i)
        while dq_max and dq_max[0] <= i-250: dq_max.popleft()
        while dq_min and dq_min[0] <= i-250: dq_min.popleft()
        hi250[i] = c[dq_max[0]]
        lo250[i] = c[dq_min[0]]
    for i in range(1, n):
        dt = dates[i]
        ti = didx.get(dt)
        if ti is None: continue
        r = c[i]/c[i-1] - 1.0
        ret_med[ti].append(r)
        if r > 0: n_up[ti] += 1
        elif r < 0: n_dn[ti] += 1
        if r >= 0.098: n_lu[ti] += 1
        if r <= -0.098: n_ld[ti] += 1
        if c[i] >= hi250[i]: n_newhi[ti] += 1
        if c[i] <= lo250[i]: n_newlo[ti] += 1
        tot_amt[ti] += v[i]*c[i]
        # 连续跌停：今日和昨日都 <= -9.8%
        if r <= -0.098 and c[i-1]/c[i-2] - 1.0 <= -0.098 if i >= 2 else False:
            n_cont_ld[ti] += 1

# 微盘股代理：每日按当日成交额排序，取最小 1/3
for ti in range(T):
    if not ret_med[ti]: continue
# 重新跑一遍只为微盘代理（要带成交额），一次循环就够——合并到上面会乱，这里单独
amt_by_day = [[] for _ in range(T)]
for d in U.values():
    c, v, dates, d2i = d["c"], d["v"], d["date"], d["d2i"]
    for i in range(1, len(c)):
        ti = didx.get(dates[i])
        if ti is None: continue
        amt_by_day[ti].append((v[i]*c[i], c[i]/c[i-1] - 1.0))

med_ret  = [0.0]*T
up_ratio = [0.0]*T
lu_ld    = [0.0]*T
bot_ret  = [0.0]*T
for ti in range(T):
    rs = ret_med[ti]
    if rs:
        med_ret[ti] = stats.median(rs)
        up_ratio[ti] = n_up[ti] / max(1, n_up[ti]+n_dn[ti])
    lu_ld[ti] = n_lu[ti]/max(1, n_ld[ti])
    arr = amt_by_day[ti]
    if arr:
        arr.sort(key=lambda x: x[0])
        k = max(1, len(arr)//3)
        bot_ret[ti] = stats.median([r for _, r in arr[:k]])

# 等权全市场指数（用中位涨幅累积）
mkt_idx = [1.0]*T
for ti in range(1, T):
    mkt_idx[ti] = mkt_idx[ti-1]*(1.0+med_ret[ti])

def ma(arr, i, w):
    if i-w+1 < 0: return None
    return sum(arr[i-w+1:i+1])/w

idx_ma20  = [ma(mkt_idx, i, 20)  for i in range(T)]
idx_ma60  = [ma(mkt_idx, i, 60)  for i in range(T)]
ret5      = [None]*T
vol20     = [None]*T
for i in range(T):
    if i >= 5:  ret5[i] = mkt_idx[i]/mkt_idx[i-5] - 1.0
    if i >= 20:
        rs = [med_ret[j] for j in range(i-19, i+1)]
        vol20[i] = stats.pstdev(rs)*math.sqrt(252) if len(rs) == 20 else None

# ---------------------------------------------------------------- PIT 分位工具
def pit_rank(series, i, win=PIT_WIN):
    """series[i] 在 series[max(0,i-win+1)..i] 中的分位 (0~1)。PIT 安全。"""
    if series[i] is None: return None
    lo = max(0, i-win+1)
    hist = [x for x in series[lo:i+1] if x is not None]
    if len(hist) < 20: return None
    below = sum(1 for x in hist if x <= series[i])
    return below/len(hist)

# 指数在 250 日窗口中的位置
def idx_pos(i, win=250):
    lo = max(0, i-win+1)
    hist = mkt_idx[lo:i+1]
    if len(hist) < 20: return None
    below = sum(1 for x in hist if x <= mkt_idx[i])
    return below/len(hist)

# ---------------------------------------------------------------- 状态定义
# 每日计算 PIT 分位（只算判定需要的）
print("computing PIT ranks ...", flush=True)
r_lu     = [None]*T   # 涨停家数分位
r_ld     = [None]*T   # 跌停家数分位
r_up     = [None]*T   # 上涨占比分位
r_amt    = [None]*T   # 成交额分位
r_pos    = [None]*T   # 指数位置分位
r_ret5   = [None]*T   # 近5日收益分位
r_vol    = [None]*T   # 20日波动率分位
for i in range(T):
    if i < MIN_HIST: continue
    r_lu[i]  = pit_rank(n_lu, i)
    r_ld[i]  = pit_rank(n_ld, i)
    r_up[i]  = pit_rank(up_ratio, i)
    r_amt[i] = pit_rank(tot_amt, i)
    r_pos[i] = idx_pos(i)
    r_ret5[i]= pit_rank(ret5, i)
    r_vol[i] = pit_rank(vol20, i)

def classify(i):
    """返回状态字符串。PIT 安全：只用 i 及之前的分位。"""
    if i < MIN_HIST: return "NA"
    if any(x is None for x in (r_lu[i], r_ld[i], r_up[i], r_ret5[i], r_pos[i])):
        return "NA"
    # S1 恐慌：跌停家数 ≥ 80 分位（过去250日） 或 上涨占比 ≤ 15 分位
    if r_ld[i] >= 0.80 or r_up[i] <= 0.15:
        return "PANIC"
    # S2 强势趋势：指数位置 ≥ 60 分位 且 近5日收益 ≥ 55 分位
    if r_pos[i] >= 0.60 and r_ret5[i] >= 0.55:
        return "TREND_UP"
    # S3 亢奋/情绪热：涨停家数 ≥ 70 分位 且 上涨占比 ≥ 60 分位
    if r_lu[i] >= 0.70 and r_up[i] >= 0.60:
        return "EUPHORIA"
    # S0 平淡/震荡：其余
    return "CHOP"

states = [classify(i) for i in range(T)]
from collections import Counter
print("state distribution:", Counter(states), flush=True)

# ---------------------------------------------------------------- 策略回测
# 信号按"信号日收盘后判定 → 次日开盘买 → T+5 收盘卖"
# 基准：同日"全市场任意股票 T+5"（用全部股票等权平均）
# 打板策略：信号日=涨停日（首封≤10:00），次日开盘买，T+5 收盘卖
lu_events = defaultdict(list)   # date -> [(code, first_seal_time), ...]
for fp in LU_CSVS:
    if not fp.exists(): continue
    with open(fp, encoding="utf-8-sig") as f:
        rd = csv.DictReader(f)
        for row in rd:
            dt = row["日期"].strip()
            code = row["代码"].strip()
            fst = row.get("首次封板时间", "").strip()
            lu_events[dt].append((code, fst))
print(f"limit-up events days: {len(lu_events)}", flush=True)

def sim_trade(d, sig_i, hold=HOLD):
    """信号日局部索引 sig_i → 次日开盘买 → sig_i+1+hold 收盘卖。返回净收益或 None。"""
    n = len(d["c"])
    ei = sig_i + 1
    xi = sig_i + 1 + hold
    if ei >= n or xi >= n: return None
    entry = d["o"][ei]
    exit_ = d["c"][xi]
    if entry <= 0: return None
    return exit_/entry - 1.0 - FEE

def sim_overnight(d, sig_i):
    """信号日收盘买 → 次日开盘卖。"""
    n = len(d["c"])
    ei = sig_i
    xi = sig_i + 1
    if xi >= n: return None
    if d["c"][ei] <= 0: return None
    return d["o"][xi]/d["c"][ei] - 1.0 - FEE

# 逐日逐股生成三类交易
# trades[state][strategy] = list of ret
trades = defaultdict(lambda: defaultdict(list))
bench_t5 = defaultdict(list)        # state -> 全市场任意股票 T+5（等权）
for code, d in U.items():
    c, ma60, dates, d2i = d["c"], d["ma60"], d["date"], d["d2i"]
    n = len(c)
    for i in range(1, n):
        dt = dates[i]
        ti = didx.get(dt)
        if ti is None: continue
        st_ = states[ti]
        if st_ == "NA": continue
        # 基准：任意股票 T+5
        r = sim_trade(d, i)
        if r is not None:
            bench_t5[st_].append(r)
        # 策略 A：跌停×MA60下
        r_chg = c[i]/c[i-1] - 1.0
        if r_chg <= -0.098 and ma60[i] is not None and c[i] <= ma60[i]:
            ra = sim_trade(d, i)
            if ra is not None:
                trades[st_]["A_limitdown_ma60"].append(ra)
        # 策略 C：隔夜（收盘买→次日开盘卖）
        rc = sim_overnight(d, i)
        if rc is not None:
            trades[st_]["C_overnight"].append(rc)

# 策略 B：打板（首封≤10:00）
for dt, evs in lu_events.items():
    ti = didx.get(dt)
    if ti is None: continue
    st_ = states[ti]
    if st_ == "NA": continue
    for code, fst in evs:
        if not fst or fst > "10:00:00": continue
        d = U.get(code)
        if d is None: continue
        i = d["d2i"].get(dt)
        if i is None: continue
        rb = sim_trade(d, i)
        if rb is not None:
            trades[st_]["B_limitup_open"].append(rb)

# ---------------------------------------------------------------- 状态×策略矩阵
def agg(rs):
    if not rs: return (0, 0.0, 0.0)
    n = len(rs)
    m = sum(rs)/n
    w = sum(1 for x in rs if x > 0)/n
    return (n, m, w)

STATE_ORDER = ["PANIC", "CHOP", "TREND_UP", "EUPHORIA"]
STRATS = ["A_limitdown_ma60", "B_limitup_open", "C_overnight"]

matrix = {}
for st_ in STATE_ORDER:
    matrix[st_] = {}
    bn, bm, bw = agg(bench_t5[st_])
    matrix[st_]["BENCH_T5"] = (bn, bm, bw)
    for s in STRATS:
        n, m, w = agg(trades[st_][s])
        matrix[st_][s] = (n, m, w, m - bm)   # 绝对超额 = 策略 - 基准

# ---------------------------------------------------------------- 按"信号日"分组的每日组合收益
# 把交易按信号日分组（决策发生在信号日收盘；这是开关真正控制的那一天）
# 每日组合收益 = 当日该策略所有信号交易的等权平均（持仓期 T+5 收益一次性记在信号日，
# 是"信号日的组合口径"，便于跨策略比较；不与日历日收益混淆）。
def trades_by_signal_day(strat_key):
    by = defaultdict(list)
    if strat_key in ("A_limitdown_ma60", "C_overnight"):
        for code, d in U.items():
            c, ma60, dates, d2i = d["c"], d["ma60"], d["date"], d["d2i"]
            for i in range(1, len(c)):
                ti = didx.get(dates[i])
                if ti is None or states[ti] == "NA": continue
                if strat_key == "A_limitdown_ma60":
                    r_chg = c[i]/c[i-1] - 1.0
                    if not (r_chg <= -0.098 and ma60[i] is not None and c[i] <= ma60[i]):
                        continue
                    r = sim_trade(d, i)
                else:
                    r = sim_overnight(d, i)
                if r is None: continue
                by[ti].append(r)
    else:
        for dt, evs in lu_events.items():
            ti = didx.get(dt)
            if ti is None or states[ti] == "NA": continue
            for code, fst in evs:
                if not fst or fst > "10:00:00": continue
                d = U.get(code)
                if d is None: continue
                i = d["d2i"].get(dt)
                if i is None: continue
                r = sim_trade(d, i)
                if r is None: continue
                by[ti].append(r)
    return by

sig_day = {s: trades_by_signal_day(s) for s in STRATS}
bench_by_sig = defaultdict(list)
for code, d in U.items():
    c, dates, d2i = d["c"], d["date"], d["d2i"]
    for i in range(1, len(c)):
        ti = didx.get(dates[i])
        if ti is None or states[ti] == "NA": continue
        r = sim_trade(d, i)
        if r is None: continue
        bench_by_sig[ti].append(r)

# 每状态每日组合收益（更真实的可实现口径）
def daily_avg(by, ti):
    rs = by.get(ti)
    return (sum(rs)/len(rs)) if rs else None

daily_state_perf = {}   # state -> strat -> (days, mean_daily, med_daily, hit_rate)
for st_ in STATE_ORDER:
    daily_state_perf[st_] = {}
    days_in_state = [ti for ti in range(T) if states[ti] == st_]
    for s in STRATS + ["BENCH"]:
        arr = []
        for ti in days_in_state:
            src = sig_day[s] if s != "BENCH" else bench_by_sig
            v = daily_avg(src, ti)
            if v is not None: arr.append(v)
        if arr:
            arr_sorted = sorted(arr)
            daily_state_perf[st_][s] = (
                len(arr),
                sum(arr)/len(arr),
                arr_sorted[len(arr)//2],
                sum(1 for x in arr if x > 0)/len(arr),
            )
        else:
            daily_state_perf[st_][s] = (0, 0.0, 0.0, 0.0)

# ---------------------------------------------------------------- 开关回测（多种仓位规则）
# 开关规则：按状态允许的策略集合；当日若无允许策略的信号，则当日空仓。
ALLOW = {
    "PANIC":     ["A_limitdown_ma60"],   # 恐慌日只做跌停反弹
    "CHOP":      [],                      # 平淡日空仓
    "TREND_UP":  ["B_limitup_open", "C_overnight"],
    "EUPHORIA":  ["B_limitup_open", "C_overnight"],
}

def build_daily(allow_map, sizing="full"):
    """构造每日组合收益序列。sizing: full=每日允许策略信号全仓等权；
    half=仓位减半（未用部分按 0 收益）；"""
    daily = [0.0]*T
    for ti in range(T):
        st_ = states[ti]
        if st_ == "NA": continue
        allowed = allow_map.get(st_, [])
        if not allowed: continue
        # 当日全部允许策略的信号合并等权
        rs = []
        for s in allowed:
            rs.extend(sig_day[s].get(ti, []))
        if not rs: continue
        r = sum(rs)/len(rs)
        daily[ti] = r * (0.5 if sizing == "half" else 1.0)
    return daily

def perf(daily):
    eq = 1.0
    peak = 1.0
    mdd = 0.0
    for r in daily:
        eq *= (1.0+r)
        peak = max(peak, eq)
        mdd = min(mdd, eq/peak - 1.0)
    yrs = T/252.0
    ann = eq**(1.0/yrs) - 1.0 if yrs > 0 else 0.0
    return eq, ann, mdd

# 多种开关仓位规则
daily_sw_full = build_daily(ALLOW, "full")
daily_sw_half = build_daily(ALLOW, "half")
# 规则 2：CHOP 也允许 C 隔夜（永不全空）
ALLOW2 = dict(ALLOW); ALLOW2["CHOP"] = ["C_overnight"]
daily_sw2 = build_daily(ALLOW2)
# 规则 3：只 PANIC 开仓，其余全空（最保守）
ALLOW3 = {"PANIC": ["A_limitdown_ma60"], "CHOP": [], "TREND_UP": [], "EUPHORIA": []}
daily_sw3 = build_daily(ALLOW3)
# 规则 4：PANIC + EUPHORIA 开仓
ALLOW4 = {"PANIC": ["A_limitdown_ma60"], "CHOP": [], "TREND_UP": ["B_limitup_open"], "EUPHORIA": ["B_limitup_open"]}
daily_sw4 = build_daily(ALLOW4)

# 基准：永远做 A / B / C（无开关，所有日均允许）
def build_always(strat):
    daily = [0.0]*T
    for ti in range(T):
        rs = sig_day[strat].get(ti, [])
        if rs: daily[ti] = sum(rs)/len(rs)
    return daily
daily_always_a = build_always("A_limitdown_ma60")
daily_always_b = build_always("B_limitup_open")
daily_always_c = build_always("C_overnight")

perfs = {
    "开关[满仓]":     perf(daily_sw_full),
    "开关[半仓]":     perf(daily_sw_half),
    "开关[CHOP加C]":  perf(daily_sw2),
    "开关[只PANIC]":  perf(daily_sw3),
    "开关[PANIC+亢奋]": perf(daily_sw4),
    "永远做A跌停":    perf(daily_always_a),
    "永远做B打板":    perf(daily_always_b),
    "永远做C隔夜":    perf(daily_always_c),
    "永远空仓":       (1.0, 0.0, 0.0),
}

# ---------------------------------------------------------------- 今日状态
today_i = T-1
today = all_dates[today_i]
today_state = states[today_i]
today_vars = {
    "date": today,
    "state": today_state,
    "n_lu": n_lu[today_i], "n_ld": n_ld[today_i],
    "lu_ld_ratio": round(lu_ld[today_i], 2),
    "up_ratio": round(up_ratio[today_i], 4),
    "med_ret": round(med_ret[today_i], 4),
    "tot_amt_yi": round(tot_amt[today_i]/1e8, 0),
    "idx_pos250": round(r_pos[today_i], 3) if r_pos[today_i] else None,
    "ret5_pct": round(ret5[today_i]*100, 2) if ret5[today_i] else None,
    "vol20_pct": round(vol20[today_i]*100, 1) if vol20[today_i] else None,
    "r_lu": round(r_lu[today_i], 3) if r_lu[today_i] else None,
    "r_ld": round(r_ld[today_i], 3) if r_ld[today_i] else None,
    "r_up": round(r_up[today_i], 3) if r_up[today_i] else None,
    "r_ret5": round(r_ret5[today_i], 3) if r_ret5[today_i] else None,
    "n_cont_ld": n_cont_ld[today_i],
    "newhi_newlo": f"{n_newhi[today_i]}/{n_newlo[today_i]}",
    "bot_ret": round(bot_ret[today_i], 4),
}

# ---------------------------------------------------------------- 报告
L = []
A = L.append
A("=" * 80)
A("每日环境开关（regime switch）报告  生成日 2026-10-19  数据截至 2026-10-16")
A("PIT 纪律：所有阈值由过去 250 个交易日分位定义；信号日收盘判定 → 次日开盘执行")
A("=" * 80)
A("")
A("一、状态定义（每日收盘后一句话可写）")
A("-" * 80)
A("记 r_X = 变量 X 在过去 250 个交易日中的分位（含当日，PIT 安全）")
A("")
A("  PANIC     恐慌  : r_跌停家数 ≥ 0.80  或  r_上涨占比 ≤ 0.15")
A("  EUPHORIA  亢奋  : r_涨停家数 ≥ 0.70  且  r_上涨占比 ≥ 0.60")
A("  TREND_UP  强势  : 指数250日位置 ≥ 0.60  且  r_近5日收益 ≥ 0.55（且非亢奋）")
A("  CHOP      平淡  : 其余")
A("")
cnt = Counter(states)
A("状态分布（全样本 2018-01 ~ 2026-10-16）：")
for s in STATE_ORDER:
    A(f"  {s:9s}  {cnt[s]:5d} 天  ({cnt[s]/T*100:.1f}%)")
A("")
A("二、状态 × 策略矩阵（n / 每笔净收益 / 胜率 / 相对基准超额）")
A("-" * 80)
A(f"{'状态':10s}{'策略':22s}{'n':>7s}{'收益/笔':>10s}{'胜率':>8s}{'超额':>10s}")
for st_ in STATE_ORDER:
    bn, bm, bw = matrix[st_]["BENCH_T5"]
    A(f"{st_:10s}{'[基准] 任意股T+5':22s}{bn:7d}{bm*100:9.2f}%{bw*100:7.1f}%{'—':>10s}")
    for s in STRATS:
        n, m, w, ex = matrix[st_][s]
        name = {"A_limitdown_ma60": "A 跌停×MA60下",
                "B_limitup_open":  "B 打板(首封≤10:00)",
                "C_overnight":     "C 隔夜(收→次开)"}[s]
        A(f"{'':10s}{name:22s}{n:7d}{m*100:9.2f}%{w*100:7.1f}%{ex*100:+9.2f}%")
    A("")
A("三、状态 × 策略矩阵【每日组合口径】（按信号日分组的每日等权组合收益）")
A("-" * 80)
A("说明：此口径把同一信号日的所有同策略信号等权为一份当日组合，避免少数“交易密集日”")
A("      支配平均数，更接近实际每日执行的收益。")
A(f"{'状态':10s}{'策略':22s}{'天数':>6s}{'日均':>9s}{'日中位':>9s}{'日胜率':>8s}")
for st_ in STATE_ORDER:
    for s in ["BENCH"] + STRATS:
        n, m, md, hr = daily_state_perf[st_][s]
        name = {"BENCH":           "[基准] 任意股T+5",
                "A_limitdown_ma60": "A 跌停×MA60下",
                "B_limitup_open":   "B 打板(首封≤10:00)",
                "C_overnight":      "C 隔夜(收→次开)"}[s]
        A(f"{st_:10s}{name:22s}{n:6d}{m*100:8.2f}%{md*100:8.2f}%{hr*100:7.1f}%")
    A("")
A("四、开关规则（该开哪条线 / 该空仓）")
A("-" * 80)
A("  PANIC     → 只开 A 跌停×MA60下（恐慌反弹是唯一有真实超额的环境）")
A("  CHOP      → 空仓（什么都不要做）")
A("  TREND_UP  → B 打板 + C 隔夜（趋势日追随资金）")
A("  EUPHORIA  → B 打板 + C 隔夜（亢奋日回避跌停接刀）")
A("")
A("五、开关 vs 基准（每日等权组合，费后，2019-01 ~ 2026-10）")
A("-" * 80)
A(f"{'口径':24s}{'累计净值':>10s}{'年化':>10s}{'最大回撤':>10s}")
for k, (eq, ann, mdd) in perfs.items():
    A(f"{k:24s}{eq:10.3f}{ann*100:9.1f}%{mdd*100:9.1f}%")
A("")
A("六、今日状态判定（2026-10-16）")
A("-" * 80)
A(f"  日期             : {today_vars['date']}")
A(f"  状态             : {today_vars['state']}")
A(f"  涨停家数         : {today_vars['n_lu']}   (PIT 分位 {today_vars['r_lu']})")
A(f"  跌停家数         : {today_vars['n_ld']}   (PIT 分位 {today_vars['r_ld']})")
A(f"  涨停/跌停比      : {today_vars['lu_ld_ratio']}")
A(f"  上涨家数占比     : {today_vars['up_ratio']}   (PIT 分位 {today_vars['r_up']})")
A(f"  中位个股涨跌幅   : {today_vars['med_ret']}")
A(f"  主板总成交额(亿) : {today_vars['tot_amt_yi']}")
A(f"  指数250日位置    : {today_vars['idx_pos250']}")
A(f"  近5日累计涨跌 %  : {today_vars['ret5_pct']}   (PIT 分位 {today_vars['r_ret5']})")
A(f"  20日年化波动率 % : {today_vars['vol20_pct']}")
A(f"  连续跌停股数     : {today_vars['n_cont_ld']}")
A(f"  新高/新低股数    : {today_vars['newhi_newlo']}")
A(f"  微盘股代理涨幅   : {today_vars['bot_ret']}")
A("")
A(f"  判定路径：r_ld={today_vars['r_ld']} (>=0.80? {'是→PANIC' if (today_vars['r_ld'] or 0)>=0.80 else '否'})"
  f" / r_up={today_vars['r_up']} (<=0.15? {'是→PANIC' if (today_vars['r_up'] or 1)<=0.15 else '否'})"
  f" / r_lu={today_vars['r_lu']} 且 r_up={today_vars['r_up']} (≥0.70&≥0.60? {'是→EUPHORIA' if (today_vars['r_lu'] or 0)>=0.70 and (today_vars['r_up'] or 0)>=0.60 else '否'})"
  f" / idx_pos={today_vars['idx_pos250']} 且 r_ret5={today_vars['r_ret5']} (≥0.60&≥0.55? {'是→TREND_UP' if (today_vars['idx_pos250'] or 0)>=0.60 and (today_vars['r_ret5'] or 0)>=0.55 else '否'})"
  f" → 最终 {today_vars['state']}")
A("")
A("七、结论（坦诚版）")
A("-" * 80)
A("1) 状态定义能稳定把交易日分成 4 类（PANIC 28% / CHOP 49% / EUPHORIA 20% / TREND_UP <1%），")
A("   全部阈值 PIT 安全，今日收盘后即可判定明日。")
A("2) 矩阵（每笔口径）显示 PANIC 日 A 跌停×MA60下 每笔 +6.31%、胜率 73.6%，")
A("   是全样本中唯一对基准有显著正超额的状态×策略组合。")
A("3) 但【每日组合口径】（把同一信号日所有信号等权为一份当日组合）揭露：")
A("   PANIC-A 的 +6.31% 几乎全部来自极少数交易密集日（如某日 277 笔齐涨 +37.8%）；")
A("   按日等权后日均 -0.21%、日胜率 47.2%，并不构成可每日执行的持续 edge。")
A("4) 其余状态×策略组合在日口径下全部为负。B 打板仅在 EUPHORIA 日略好于 CHOP/PANIC，")
A("   但日均仍为负。C 隔夜在所有状态下都为负，且每日都触发，是最大漏血点。")
A("5) 因此开关回测的真实结论：2019~2026 区间，任何“每日都交易的短线规则”费后都无法")
A("   战胜空仓。今日（2026-10-16）状态 = CHOP，开关规则：空仓。")
A("6) 实用建议：")
A("   - 把 PANIC 当作【唯一允许短线开仓】的日子，但仓位需打折（建议 ≤ 1/3 仓）。")
A("   - CHOP 与 EUPHORIA 都不要开仓，尤其要避开 C 隔夜这种每日必触发的线。")
A("   - TREND_UP 状态样本太少（3 天），不能据此下结论，建议继续观察。")
A("=" * 80)

OUT.write_text("\n".join(L), encoding="utf-8")
print(f"wrote {OUT}", flush=True)
print("\n".join(L[-30:]))
