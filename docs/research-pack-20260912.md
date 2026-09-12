# A股短线算法框架深度调研任务书（Research Charter）

> **版本**：2026-09-12 ｜ **发起方**：焚诀定律工程（自家 8 年全市场回测体系）
> **用途**：交给外部 AI（Deep Research / 深度调研类模型）做学术级框架调研。
> **目标**：不是再找一些"战法"，而是对下列开放问题给出**文献级、可证伪、带统计量的答案**，最终服务于一个问题的回答——
>
> **在 T+1、涨跌停、散户主导的 A 股市场，是否存在可公开论证的、衰减可监控的短线统计规律体系？它的正确架构是什么？**

---

## 0. 给执行 AI 的总规则（先读这个）

1. **禁止编造引用**。每条文献必须给出：作者/机构、发表年份、载体（期刊/工作论文/券商金工）、样本区间、关键统计量。找不到就写"未找到"，不许编。
2. **每个结论必须附证伪条件**：什么证据出现时这个结论应该被推翻。
3. **区分三个证据等级**：A=经过大样本样本外复验的学术/全量统计；B=券商金工回测（有选择性披露风险）；C=逻辑推演/个案。禁止把 C 级说成 A 级。
4. **我们已有自家 8 年全市场数据**（3333 只含退市股，2019-2026，前复权日K+60分钟线）。你提出的任何可检验假设，请写成**可执行的实验设计**（信号定义、入场/出场、对照组、样本外切分方式），我们会拿真数据复跑。空谈不要。
5. **已知陷阱清单必须绕开**：未来函数、幸存者偏差、重叠窗口 t 值虚高（需 Newey-West）、多重检验（Harvey 门槛 t≥3）、日历时间组合口径（同日全市场为基准）、交易成本（双边 0.15% 起）。
6. 如果你认为我们 §3 的某个"存活主张"是错的，**欢迎推翻**——给出机制和证据，比附和更有价值。

---

## 1. 项目现状快照（你的研究起点）

**市场微观结构前提**：A 股主板 T+1、±10% 涨跌停、无做空（散户）、2019-2026 年样本期覆盖完整牛熊。

**我们的数据底座**：沪深主板 3333 只（含 186 只已退市股，幸存者偏差已修正）、2019-01~2026-09 前复权日 K、流通市值时点序列、分红史、业绩预告事件库（39,451 条）、60 分钟线（2 年）、涨跌停/炸板官方池（向前积累中）。

**我们的验证管线**（每条结论必须过）：
- 随机对照 + 位置匹配对照（同票同 MA60 侧随机日）
- 时间双段（2019-2022 / 2023-2026）+ regime 分段（主线/妖股/恐慌/平淡四态，自研分类器）+ 市值五分位
- 成本压力（0.15%/0.30%/0.50%）+ 多期衰减曲线（T+1/3/5/10/20）
- Newey-West 修正 t 值 + Harvey t≥3 多重检验门槛 + 日历时间组合 + Deflated Sharpe
- 滚动 250 交易日存活审计（周更，edge 跌破 kill 线自动降级）

---

## 2. 已证伪清单（这些路不要再走）

以下均在 8 年全市场、净口径、含退市股下被我们自己的数据杀死：

| 已死 | 死因 |
|---|---|
| 追高打板族（尾盘挤进/首板次日追/二连板追） | 全周期负期望，n=12.8 万 |
| 海龟 20/55 日突破、MA20 上穿、三连阴、缩量横盘放量突破 | ≈随机或负 |
| 伪缠论 B1（底分型+MACD背驰+缩量三重确认） | n=24145，跑输随机 |
| K 线形态族（神奇九转/低位大长腿/低位避雷针） | 8 年全样本曾有 edge，**滚动 250 日审计 2026-09-12 判 DEAD**——近一年边际贡献转负 |
| 高窄旗形/涨停洗盘/上升趋势跌停反包（Sequoia-X 移植） | 净亏损或≈随机，t=-6 级 |
| 跟游资席位 | 28.7 万样本，知名游资上榜后 5 日超额 -1.2%（反向指标） |
| 分红抢权/填权短线 | 除权前后超额≈0 |

---

## 3. 存活主张（当前证据等级与精确数字）

| 主张 | 数字（净口径） | 等级 |
|---|---|---|
| **恐慌深度剂量反应**：信号日跌幅越深，次日开盘买入的反弹越强且单调（-3~-5%:+0.03% → -5~-7%:+0.17% → -7~-9.5%:+0.42% → 跌停:+1.10%；同日全市场超额口径同样单调 0.067→0.411；T+5 跌停接 +2.65%/57.6%，n=30684，双段一致，一字剔除+含退市股） | 候选 L2+（最高级） |
| **反转族**（昨跌≥3% 次日开盘买→次日尾盘） | +0.139%/49.8%，n=48.9 万 | 候选 L2+ |
| **regime 调制**：反转 edge 在妖股期同日超额最高（+0.205），恐慌期反而低（+0.049）——"恐慌期才做反转"直觉被证伪 | 候选 L2 |
| **周一效应**：周一全市场日均 +0.169%/60.8%（含退市股口径） | 候选 L2+ |
| **绞肉机黑名单**：近 20 日换手最高 20% 组与彩票型（MAX）组，91 个月累计跑输全市场 -54.0%/-56.1% | 候选 L2+ |
| **位置因子对反转族反向**：MA60 上方信号 T+1 反转 +0.20% vs 下方 +0.13%（与形态族结论相反，不可泛化） | 候选 L2 |
| 可转债双低轮动年化 15-19%（外部：华福回测+集思录 7 年实盘） | B 级外部 |

**没有任何主张达到 LAW 级**（LAW 需五条件：机制解释/跨regime/跨宇宙/成本容量/20交易日前向影子——影子盘 2026-09-14 起攒）。

---

## 4. 开放问题（按优先级，这就是你要调研的）

### Q1. 恐慌深度单调性的机制解释（最高优先级）
我们的数据：反弹幅度随信号日跌幅严格单调，且同日超额口径成立（非大盘 beta）。
**要回答**：A 股是否存在制度性原因（涨跌停板导致的 price discovery 延迟/T+1 强制的隔夜风险折价/散户恐慌出清的结构）？海外文献（如 limit-hit 后的 order flow 研究、中国涨跌停制度实证）怎么解释？这个 edge 的**付钱方**是谁（谁在跌停次日开盘贱卖）？为什么 2023-2026 段依然成立（量化收割下为何没死）？

### Q2. edge 的衰减结构与半衰期
形态族近一年死亡 vs 恐慌深度存活——**什么特征的因子死得快**？（公开度/拥挤度/参数简单度？）文献上 factor decay（McLean & Pontiff 之后）有没有适用于中国散户市+涨跌停制度的版本？如何提前预判一个因子将死（crowding proxy）？

### Q3. regime 条件化
妖股期反转超额最高的机制？国内外 regime-switching 因子模型的正确做法（Markov 切换 vs 我们的规则四态）？周期判定本身的前视风险如何规避？

### Q4. 组合层的正确数学形式
多个弱信号（每个 edge 0.1-0.4%）组合成系统的正确方法：投票/闸门/加权/贝叶斯更新各自的统计性质？信号相关时的组合方差怎么处理？参考：Grinold & Kahn 的 Fundamental Law（IR=IC×√BR）在低 IC 高宽度场景的适用性。

### Q5. T+1 约束下的最优执行
T+1 锁仓如何改变最优持有期？我们的数据显示 T+5 显著优于 T+1（跌停接 +1.10%→+2.65%）——这是 A 股特有现象还是全球普遍？文献里 T+1 对价格发现/波动率的影响（中国市场研究）有哪些硬结论？

### Q6. 周一效应的可交易性
周一 +0.169%/60.8% 但幅度小——扣除成本和资金占用后是否可交易？calendar effect 在全球市场死后（被套利消灭）在 A 股存活的原因？与其他日历效应（节前/月末/季末）的交互？

### Q7. PEAD 在中国 2021 量化扩容后的现状
SUE 因子 RankIC 4.6%（2019 前文献）→ 2021 后被收割衰减。业绩预告（而非正式财报）事件的 PEAD 强度、衰减曲线、与涨跌停的交互（预告超预期但一字涨停买不进=edge 不可得）。我们已有 39,451 条预告事件库可验证你的任何假设。

### Q8. 我们没想到的
如果你认为上述清单漏了更根本的问题（比如整个问法就错了），请直接指出并给出理由。

---

## 5. 输出格式要求

1. 每个问题：结论（一句话）→ 证据（分级标注 A/B/C + 文献表）→ 机制解释 → **可执行实验设计**（信号定义/对照组/样本外切分）→ 证伪条件
2. 结尾：一张"如果只能做三件事"的优先级表
3. 总长不限，但**每一个数字都要有出处或标注"推演"**
4. 我们会把你的实验设计逐条用自家 8 年数据复跑，复跑结果会反馈给你做第二轮——写设计时请按这个前提写得足够具体。

---

## 6. 交叉质询预告

你的输出会被拿去和其他 AI 的回答对撞（同一份任务书会发给多家）。明显区别于共识的点会被优先验证——所以**不要讨好共识，写你真信的东西**。


---

# 以下为代码与数据附件（供审查实现细节，非纯提示词）


# 附件：验证管线 law_pipeline.py

`law_pipeline.py` 完整内容：

```python
#!/usr/bin/env python3
"""engine/law_pipeline.py — 定律证伪管线（law-program-20260911.md S1 冲刺产物）

一键五件套：随机对照 / 时间分段(2019-22,2023-26) / regime分段(主线/妖股/恐慌/平淡)
           / 市值五分位 / 成本压力(0.15/0.30/0.50%) + L4容量账 + 自动判决。

用法：
    python3 engine/law_pipeline.py              # 跑 REGISTRY 全部信号
    python3 engine/law_pipeline.py 避雷针_低位   # 只跑指定信号

信号契约：detect(d, i) -> bool。d 是预计算字典：
    d["c"],d["o"],d["h"],d["l"] = 收盘/开盘/最高/最低数组
    d["ma60"][i] = 60 日均线（i<60 时为 None）
    d["date"][i] = 日期字符串
入场=i+1 开盘，离场=i+1+horizon 收盘，horizon=5，净口径 fee=0.0015。
判决只覆盖 L2/L3/L4（L1机制靠人，L5影子前向靠时间）。
"""
import json, glob, math, random, statistics as st, sys
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
KC, CAP = ROOT / "data/big_kcache", ROOT / "data/cap_hist"
TIMELINE = ROOT / "data/regime_timeline_hcap.json"
FEES = [0.0015, 0.003, 0.005]
HORIZON = 5
HORIZONS = [1, 3, 5, 10, 20]  # IC 衰减曲线（alphalens/qlib 惯例）
NW_MIN_T = 3.0                # Harvey & Liu 2015 多重检验门槛（本项目累计已测>20个信号）
START = 65


def load_universe():
    stocks = {}
    for fp in glob.glob(str(KC / "*.json")):
        ks = json.loads(open(fp).read())
        if len(ks) < 300:
            continue
        c = [k["close"] for k in ks]
        pre = [0.0]
        for x in c:
            pre.append(pre[-1] + x)
        ma60 = [None] * 60 + [(pre[i + 1] - pre[i - 59]) / 60 for i in range(59, len(c) - 1)]
        ma60.append((pre[len(c)] - pre[len(c) - 60]) / 60)
        ma60 = ma60[:len(c)]  # 自查修正：原构造多出一个尾部元素（无害但脏）
        stocks[Path(fp).stem] = {
            "c": c, "o": [k["open"] for k in ks], "h": [k["high"] for k in ks],
            "l": [k["low"] for k in ks], "v": [k.get("volume", 0) for k in ks], "ma60": ma60,
            "date": [k["date"] for k in ks], "n": len(ks),
        }
    return stocks


def load_regime():
    return {r["date"]: r["regime"] for r in json.loads(TIMELINE.read_text())}


def load_cap_quintiles():
    per_month, stock_cap = {}, {}
    for fp in glob.glob(str(CAP / "*.json")):
        code = Path(fp).stem
        d = {}
        for date, _px, cap in json.loads(open(fp).read()):
            m = date[:7]
            d[m] = cap
            per_month.setdefault(m, []).append(cap)
        stock_cap[code] = d
    qs = {}
    for m, caps in per_month.items():
        caps.sort()
        n = len(caps)
        qs[m] = [caps[int(n * p)] for p in (0.2, 0.4, 0.6, 0.8)] if n >= 50 else None
    return stock_cap, qs


def cap_quintile(stock_cap, qs, code, date):
    m = date[:7]
    cap = stock_cap.get(code, {}).get(m)
    b = qs.get(m)
    if cap is None or b is None:
        return None
    return sum(cap > x for x in b)


def S(rs):
    if len(rs) < 30:
        return None
    n = len(rs)
    m = st.mean(rs)
    return {"n": n, "win%": round(100 * sum(r > 0 for r in rs) / n, 1),
            "mean%": round(100 * m, 2), "med%": round(100 * st.median(rs), 2),
            "t": round(m / (st.stdev(rs) / math.sqrt(n)), 1)}


def nw_t(rs, lag):
    """Newey-West HAC t 值（重叠窗口收益的标准误修正，lag=持有期）。
    重叠 h 日的收益自相关到 h-1 阶，朴素 t 值虚高 ~sqrt(h) 倍。"""
    n = len(rs)
    if n < lag + 30:
        return None
    m = st.mean(rs)
    g0 = sum((r - m) ** 2 for r in rs) / n
    lrv = g0
    for k in range(1, lag + 1):
        gk = sum((rs[t_] - m) * (rs[t_ - k] - m) for t_ in range(k, n)) / n
        lrv += 2 * (1 - k / (lag + 1)) * gk
    return round(m / math.sqrt(lrv / n), 1) if lrv > 0 else None


def calendar_time(events, stocks, horizon, fee):
    """日历时间组合法（Fama-French 标准）：事件按入场日聚合成日度组合，
    每日收益 - 当日全宇宙均值 = 日度超额序列，对序列做 NW t。
    治的是事件在恐慌日扎堆导致的横截面相关——朴素 t 把同一天 100 只票当 100 个独立样本。"""
    from collections import defaultdict
    by_date = defaultdict(list)
    for code, i in events:
        d = stocks[code]
        by_date[d["date"][min(i + 1, d["n"] - 1)]].append(d["c"][i + horizon] / d["o"][i + 1] - 1 - fee)
    # 全宇宙日度均值（同窗口口径）
    uni = defaultdict(list)
    for code, d in stocks.items():
        c, o, n = d["c"], d["o"], d["n"]
        for i in range(START, n - horizon - 1):
            if o[i + 1] > 0:
                uni[d["date"][i + 1]].append(c[i + horizon] / o[i + 1] - 1 - fee)
    uni_m = {dt: st.mean(v) for dt, v in uni.items()}
    dates = sorted(by_date)
    series = [st.mean(by_date[dt]) - uni_m[dt] for dt in dates if dt in uni_m]
    if len(series) < 30:
        return None
    m, sd = st.mean(series), st.stdev(series)
    sr = m / sd * math.sqrt(244) if sd > 0 else 0
    return {"天数": len(series), "日均超额%": round(100 * m, 3),
            "年化Sharpe": round(sr, 2), "t_NW": nw_t(series, horizon),
            "skew": round(_skew(series), 2), "kurt": round(_kurt(series), 2)}


def _skew(x):
    m = st.mean(x)
    s = st.stdev(x)
    return sum((v - m) ** 3 for v in x) / len(x) / s ** 3 if s > 0 else 0


def _kurt(x):
    m = st.mean(x)
    s = st.stdev(x)
    return sum((v - m) ** 4 for v in x) / len(x) / s ** 4 if s > 0 else 3


def deflated_sharpe(sr_daily, T, skew, kurt, trials=25):
    """Deflated Sharpe Ratio（Bailey & López de Prado 2014）：
    在试过 trials 个策略的选择偏差下，观测 Sharpe 仍显著为正的概率。
    sr_daily 必须是日频 Sharpe（年化值/√244），T=日度观测数。
    返回 P(SR>0 | 选择偏差修正后)，>0.95 才算硬。"""
    from math import erf, sqrt
    if T < 10:
        return None
    em = 0.5772156649
    Phi = lambda z: 0.5 * (1 + erf(z / sqrt(2)))
    V = max(1e-12, (1 - skew * sr_daily + (kurt - 1) / 4 * sr_daily ** 2) / (T - 1))
    sd = sqrt(V)
    sr_star = sd * ((1 - em) * _norm_ppf(1 - 1 / trials) + em * _norm_ppf(1 - 1 / (trials * 2.718281828)))
    return round(Phi((sr_daily - sr_star) / sd), 3)


def _norm_ppf(p):
    """Acklam 近似逆正态"""
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)


def run_pipeline(name, detect, stocks, regime, stock_cap, qs, horizon=HORIZON, fee=0.0015):
    full, ctrl = [], []
    events = []  # (code, i) 供多期衰减曲线复用
    seg_t, seg_r, seg_c = {"2019-2022": [], "2023-2026": []}, {}, {i: [] for i in range(5)}
    random.seed(42)
    for code, d in stocks.items():
        c, o, n = d["c"], d["o"], d["n"]
        hi = n - max(HORIZONS) - 1
        sc = stock_cap.get(code, {})
        for i in range(START, hi):
            if o[i + 1] <= 0 or not detect(d, i):
                continue
            events.append((code, i))
            r = c[i + horizon] / o[i + 1] - 1 - fee
            full.append(r)
            dt = d["date"][i]
            seg_t["2019-2022" if dt < "2023" else "2023-2026"].append(r)
            seg_r.setdefault(regime.get(dt, "?"), []).append(r)
            b = qs.get(dt[:7])
            cap = sc.get(dt[:7])
            if cap is not None and b:
                seg_c[sum(cap > x for x in b)].append(r)
        for _ in range(3):
            i = random.randint(START + 1, n - max(HORIZONS) - 2)
            ctrl.append(c[i + horizon] / o[i + 1] - 1 - fee)

    # IC 衰减曲线：同一批事件在 T+1/3/5/10/20 的表现 + NW 修正 t
    decay = {}
    for h in HORIZONS:
        rs = [stocks[code]["c"][i + h] / stocks[code]["o"][i + 1] - 1 - fee for code, i in events]
        s = S(rs)
        if s:
            s["t_NW"] = nw_t(rs, h)
            s["过Harvey门槛"] = "✅" if (s["t_NW"] is not None and abs(s["t_NW"]) >= NW_MIN_T) else "❌"
            decay[f"T+{h}"] = s

    cost = {f"{f*100:.2f}%": S([r + fee - f for r in full]) for f in FEES}
    ct = calendar_time(events, stocks, horizon, fee)
    dsr = deflated_sharpe(ct["年化Sharpe"] / math.sqrt(244), ct["天数"], ct["skew"], ct["kurt"]) if ct else None
    years = 1862 / 244
    trig_yr = len(full) / len(stocks) / years
    edge_pp = (st.mean(full) - st.mean(ctrl)) * 100 if full and ctrl else 0

    seg_r_stats = {k: S(v) for k, v in sorted(seg_r.items()) if S(v)}
    seg_c_stats = {f"Q{q}": S(v) for q, v in sorted(seg_c.items()) if S(v)}
    seg_t_stats = {k: S(v) for k, v in seg_t.items()}

    def pos(x): return x and x["mean%"] > 0
    verdict = {"L2_时间分段": "✅" if all(pos(v) for v in seg_t_stats.values()) else "❌",
               "L2_regime分段": "✅" if sum(1 for v in seg_r_stats.values() if pos(v)) >= max(3, len(seg_r_stats) - 1) else "❌",
               "L3_市值五分位": "✅" if sum(1 for v in seg_c_stats.values() if pos(v)) >= len(seg_c_stats) - 1 else "❌",
               "L4_成本容量": "✅" if (full and st.mean(full) > 3 * fee and trig_yr * edge_pp / 100 > 0.02) else "❌",
               "L1_机制": "人工", "L5_影子前向": "待20交易日"}
    return {"信号": name, "全样本": S(full), "随机对照": S(ctrl),
            "衰减曲线": decay, "日历时间组合": ct, "DSR概率": dsr,
            "时间分段": seg_t_stats, "regime分段": seg_r_stats, "市值五分位": seg_c_stats,
            "成本压力": cost, "每票每年触发": round(trig_yr, 2),
            "超额pp/笔": round(edge_pp, 2), "判决": verdict}


def matched_marginal(detect, stocks, horizons, fee=0.0015, seed=7):
    """位置匹配对照的边际贡献（剥离 MA60 位置因子）：
    对照组 = 同一只票、**同位置**（信号日在MA60上→对照也取MA60上的随机日）的随机日。
    返回 {h: 边际pp}。2026-09-12 修正：旧版对照组只取 MA60 下方日，
    对高位信号（如涨停洗盘）构成错配对照，边际值虚高。"""
    import random as _rnd
    rnd = _rnd.Random(seed)
    out = {}
    for h in horizons:
        sig, ctl = [], []
        for code, d in stocks.items():
            c, o, n, ma = d["c"], d["o"], d["n"], d["ma60"]
            days, lows, highs = [], [], []
            for i in range(START, n - h - 1):
                if o[i + 1] <= 0 or ma[i] is None:
                    continue
                (lows if c[i] <= ma[i] else highs).append(i)
                if detect(d, i):
                    days.append(i)
            for i in days:
                sig.append(c[i + h] / o[i + 1] - 1 - fee)
            # 按信号日自身位置分组匹配
            lo_n = sum(1 for i in days if c[i] <= ma[i])
            hi_n = len(days) - lo_n
            for pool, k in ((lows, lo_n), (highs, hi_n)):
                if pool and k:
                    for i in rnd.sample(pool, min(k, len(pool))):
                        ctl.append(c[i + h] / o[i + 1] - 1 - fee)
        if len(sig) >= 30 and len(ctl) >= 30:
            out[h] = round(100 * (st.mean(sig) - st.mean(ctl)), 2)
    return out


def submit_gate(name, detect, stocks, regime, stock_cap, qs):
    """WorldQuant BRAIN 式提交闸门：新信号入库前的确定性全检。
    硬闸门（任一不过即拒收，exit 1）：
      G1 衰减曲线 T+5 的 t_NW ≥ 3.0（Harvey 多重检验门槛）
      G2 时间分段两段同号为正
      G3 regime 分段 ≥3/4 为正
      G4 市值五分位 ≥4/5 为正
      G5 位置匹配对照 T+5 与 T+20 边际贡献均为正
      G6 成本压力 0.30% 下全样本仍为正
    参考项（不卡但报告）：日历时间组合 DSR、L4 容量账。
    """
    r = run_pipeline(name, detect, stocks, regime, stock_cap, qs)
    marg = matched_marginal(detect, stocks, [5, 20])
    d5 = r["衰减曲线"].get("T+5", {})
    gates = {
        "G1_tNW≥3": abs(d5.get("t_NW") or 0) >= NW_MIN_T,
        "G2_时间分段": all(v and v["mean%"] > 0 for v in r["时间分段"].values()),
        "G3_regime≥3/4": sum(1 for v in r["regime分段"].values() if v and v["mean%"] > 0) >= max(3, len(r["regime分段"]) - 1),
        "G4_市值≥4/5": sum(1 for v in r["市值五分位"].values() if v and v["mean%"] > 0) >= len(r["市值五分位"]) - 1,
        "G5_位置匹配边际>0": bool(marg) and all(v > 0 for v in marg.values()),
        "G6_0.30%成本仍正": (r["成本压力"].get("0.30%") or {}).get("mean%", -9) > 0,
    }
    passed = all(gates.values())
    verdict = {"信号": name, "闸门": {k: "✅" if v else "❌" for k, v in gates.items()},
               "判决": "PASS 可入注册表" if passed else "REJECT",
               "位置匹配边际pp": marg, "日历时间DSR": r["DSR概率"],
               "每票每年触发": r["每票每年触发"], "全样本": r["全样本"], "随机对照": r["随机对照"]}
    return passed, verdict


# ---------- 信号注册表（新增信号往这里加，不许再写一次性脚本） ----------

def _td9buy(d, i):
    c = d["c"]
    return all(c[i - k] < c[i - k - 4] for k in range(9))

def _td9sell(d, i):
    c = d["c"]
    return all(c[i - k] > c[i - k - 4] for k in range(9))

def _shadows(d, i):
    body = abs(d["c"][i] - d["o"][i])
    return body, min(d["c"][i], d["o"][i]) - d["l"][i], d["h"][i] - max(d["c"][i], d["o"][i])

def _biglower(d, i):
    b, lo, _up = _shadows(d, i)
    return lo >= max(2 * b, 0.03 * d["c"][i])

def _bigupper(d, i):
    b, _lo, up = _shadows(d, i)
    return up >= max(2 * b, 0.03 * d["c"][i])


# ---- Sequoia-X 移植（逐行对齐 sngyai/Sequoia-X 源码，泛化到任意信号日 i） ----

def _htf(d, i):
    """高窄旗形：40日高低比>1.6 且 近10日振幅<15% 且 近10日低点≥40日高点80% 且 量<前20日均量0.6"""
    if i < 41:
        return False
    h, l, v = d["h"], d["l"], d["v"]
    h40, l40 = max(h[i - 39:i + 1]), min(l[i - 39:i + 1])
    if l40 <= 0 or h40 / l40 <= 1.6:
        return False
    h10, l10 = max(h[i - 9:i + 1]), min(l[i - 9:i + 1])
    if l10 <= 0 or h10 / l10 >= 1.15 or l10 < h40 * 0.8:
        return False
    return v[i] < (sum(v[i - 20:i]) / 20) * 0.6


def _shakeout(d, i):
    """涨停洗盘：昨日涨停(≥+9.5%) 且 今日收阴 且 今日量>昨日2倍 且 今日低点≥昨收"""
    if i < 2:
        return False
    c, o, l, v = d["c"], d["o"], d["l"], d["v"]
    return (c[i - 2] > 0 and c[i - 1] >= c[i - 2] * 1.095 and c[i] < o[i]
            and v[i - 1] > 0 and v[i] > v[i - 1] * 2.0 and l[i] >= c[i - 1])


def _uptrend_ld(d, i):
    """上升趋势跌停：昨日 MA20>MA60 且 今日收盘≤昨收×0.905 且 量>20日均量2倍"""
    if i < 61:
        return False
    c, v = d["c"], d["v"]
    ma20 = sum(c[i - 20:i]) / 20
    ma60v = sum(c[i - 60:i]) / 60
    if ma20 <= ma60v or c[i - 1] <= 0 or c[i] > c[i - 1] * 0.905:
        return False
    vma = sum(v[i - 19:i + 1]) / 20
    return vma > 0 and v[i] > vma * 2.0

REGISTRY = {
    "TD9买入": _td9buy,
    "TD9卖出": _td9sell,
    "大长腿_低位": lambda d, i: d["c"][i] <= d["ma60"][i] and _biglower(d, i),
    "大长腿_高位": lambda d, i: d["c"][i] > d["ma60"][i] and _biglower(d, i),
    "避雷针_低位": lambda d, i: d["c"][i] <= d["ma60"][i] and _bigupper(d, i),
    "避雷针_高位": lambda d, i: d["c"][i] > d["ma60"][i] and _bigupper(d, i),
    # ---- Sequoia-X 移植候选（2026-09-12，定义逐行对齐原项目源码） ----
    "高窄旗形HTF": _htf,
    "涨停洗盘Shakeout": _shakeout,
    "上升趋势跌停ULD": _uptrend_ld,
}


def main():
    only = sys.argv[1:] or None
    submit_mode = only and only[0] == "submit"
    if submit_mode:
        only = only[1:] or None
    stocks = load_universe()
    print("stocks:", len(stocks), flush=True)
    regime = load_regime()
    stock_cap, qs = load_cap_quintiles()
    out = {}
    rc = 0
    for name, fn in REGISTRY.items():
        if only and name not in only:
            continue
        if submit_mode:
            passed, v = submit_gate(name, fn, stocks, regime, stock_cap, qs)
            out[name] = v
            print(json.dumps(v, ensure_ascii=False), flush=True)
            rc |= 0 if passed else 1
        else:
            out[name] = run_pipeline(name, fn, stocks, regime, stock_cap, qs)
            print(f"{name}: 全样本{out[name]['全样本']} 判决{out[name]['判决']}", flush=True)
    tag = "submit" if submit_mode else "candle"
    dst = ROOT / f"data/law_pipeline_{tag}_20260911.json"
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("saved", dst)
    sys.exit(rc)


if __name__ == "__main__":
    main()

```

# 附件：主张审计引擎 claims_audit.py

`claims_audit.py` 完整内容：

```python
#!/usr/bin/env python3
"""engine/claims_audit.py — 主张审计引擎（定律工程自我修正回路）

每条注册主张按 kill_line 复验：
- law_pipeline 背书的主张：全量重跑 + 滚动 250 交易日窗口边际贡献
- 位置匹配对照（position_matched）：同票同 MA60 下方随机日，剥离位置因子
- 随机入场对照（random_entry）：任意随机日
状态机：CANDIDATE/LAW → DECAYING（跌破 kill 线）→ DEAD（连续 2 次未恢复）→ 恢复需回到基线 70%。
看门狗纪律：只有状态变更才输出报告；无变更输出一行心跳。
用法：python3 engine/claims_audit.py [--report]   # --report 强制全量输出
"""
import json, math, random, statistics as st, sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from law_pipeline import load_universe, REGISTRY, START

ROOT = Path("/opt/data/fenjue")
REG_YAML = ROOT / "data/claims_registry.yaml"
STATE = ROOT / "data/claims_state.json"
FEE = 0.0015
ROLL_N = 250  # 滚动窗口（交易日）
RECOVER_RATIO = 0.7


def marginals(det, stocks, control, horizons):
    """返回 {h: (全量边际pp, 滚动边际pp, 滚动事件数)}"""
    rnd = random.Random(7)
    sig = {h: ([], []) for h in horizons}  # h -> ([日期], [收益])
    ctl = {h: [] for h in horizons}
    for code, d in stocks.items():
        c, o, n, ma = d["c"], d["o"], d["n"], d["ma60"]
        days, lows = [], []
        for i in range(START, n - max(horizons) - 1):
            if o[i + 1] <= 0:
                continue
            if control == "position_matched":
                if ma[i] is None:
                    continue
                low = c[i] <= ma[i]
                if low:
                    lows.append(i)
                if low and det(d, i):
                    days.append(i)
            else:
                if det(d, i):
                    days.append(i)
        for i in days:
            for h in horizons:
                sig[h][0].append(d["date"][i])
                sig[h][1].append(c[i + h] / o[i + 1] - 1 - FEE)
        if control == "position_matched":
            pool = lows
        else:
            pool = list(range(START, n - max(horizons) - 1))
        for i in rnd.sample(pool, min(len(days), len(pool))):
            for h in horizons:
                ctl[h].append(c[i + h] / o[i + 1] - 1 - FEE)
    out = {}
    # 修正（2026-09-12 自查）：滚动窗口必须按交易日历切，不是按信号日切——
    # 稀疏信号（年触发30次）按信号日切会把窗口拉到数年，丧失"近期存活"语义。
    all_days = sorted({dt for d in stocks.values() for dt in d["date"]})
    cutoff = all_days[-ROLL_N] if len(all_days) > ROLL_N else None
    for h in horizons:
        ds, rs = sig[h]
        if len(rs) < 30 or len(ctl[h]) < 30:
            continue
        full_pp = 100 * (st.mean(rs) - st.mean(ctl[h]))
        if cutoff:
            idx = [j for j, dt in enumerate(ds) if dt >= cutoff]
            roll_pp = 100 * (st.mean([rs[j] for j in idx]) - st.mean([ctl[h][j] for j in idx])) if len(idx) >= 30 else None
        else:
            roll_pp, idx = full_pp, list(range(len(rs)))
        out[h] = (round(full_pp, 2), None if roll_pp is None else round(roll_pp, 2), len(idx))
    return out


def transit(state, verdict):
    """状态机。verdict: True=过kill线 False=跌破"""
    prev = state.get("status", "CANDIDATE")
    fails = state.get("consecutive_fails", 0)
    if verdict:
        return ("CANDIDATE" if prev == "DEAD" else prev if prev != "DECAYING" else "CANDIDATE", 0, prev)
    fails += 1
    new = "DEAD" if fails >= 2 else "DECAYING"
    return new, fails, prev


def main():
    claims = yaml.safe_load(REG_YAML.read_text())["claims"]
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    stocks = None
    changes, rows = [], []
    for c in claims:
        cid = c["id"]
        det_key = c.get("detector", "")
        s = state.get(cid, {"status": "CANDIDATE", "consecutive_fails": 0, "history": []})
        if det_key not in REGISTRY:
            rows.append(f"[{cid}] external 背书，本轮只登记不复跑（{c.get('note','')}）")
            state.setdefault(cid, s)
            continue
        if stocks is None:
            stocks = load_universe()
        res = marginals(REGISTRY[det_key], stocks, c.get("control", "random_entry"), c["horizon"])
        # 填基线
        for h, (full_pp, _r, _n) in res.items():
            if c["baseline_pp"].get(h) is None:
                c["baseline_pp"][h] = full_pp
        verdicts = {}
        for h in c["horizon"]:
            if h not in res:
                continue
            _f, roll_pp, nroll = res[h]
            kill = c["kill_line_pp"][h]
            if c.get("direction") == "negative":
                ok = roll_pp is not None and roll_pp < kill  # 负向主张：滚动值须保持在kill线下
            else:
                ok = roll_pp is not None and roll_pp >= kill
            verdicts[h] = (roll_pp, kill, ok, nroll)
        ok_all = all(v[2] for v in verdicts.values()) if verdicts else True
        new, fails, prev = transit(s, ok_all)
        s.update(status=new, consecutive_fails=fails)
        s["history"].append({"date": "2026-09-11", "verdicts": {str(h): v[:3] for h, v in verdicts.items()}})
        s["history"] = s["history"][-52:]
        state[cid] = s
        line = f"[{cid}] {prev}→{new} | " + " ".join(
            f"T+{h}: 滚动{v[0]}pp vs kill {v[1]}pp {'✅' if v[2] else '❌'}(n={v[3]})" for h, v in verdicts.items())
        rows.append(line)
        if new != prev:
            changes.append(line)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1))
    REG_YAML.write_text(yaml.safe_dump({"claims": claims}, allow_unicode=True, sort_keys=False))
    if "--report" in sys.argv or changes:
        print("\n".join(rows))
        print("状态变更:", len(changes))
    else:
        print(f"claims audit ok: {len(claims)} 条主张，无状态变更。")


if __name__ == "__main__":
    main()

```

# 附件：影子盘 claims_shadow.py

`claims_shadow.py` 完整内容：

```python
#!/usr/bin/env python3
"""engine/claims_shadow.py — 存活主张的影子前向记录（L5 毕业条件的数据源）

每日收盘后（kcache 刷新后）跑：
1. 扫描今日信号：REVERSAL（跌≥3%）/ LIMITDOWN（跌≤-9.5%，剔一字）/ PANIC_DEPTH 四档
2. 登记 shadow 单：{signal_date, claim, code, tier}
3. 回填历史单：次日开盘价（entry）、T+1/T+5/T+20 收盘收益
4. 汇总各主张的滚动影子表现 → data/claims_shadow_summary.json 供 claims_audit 读 L5

设计约束：只用 big_kcache（前复权日K），无新增数据依赖；净口径 -0.15%。
"""
import json
from datetime import date
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
KC = ROOT / "data/big_kcache"
SHADOW = ROOT / "data/claims_shadow.jsonl"
SUMMARY = ROOT / "data/claims_shadow_summary.json"
FEE = 0.0015


def load_stocks():
    out = {}
    for fp in sorted(KC.glob("*.json")):
        ks = json.loads(fp.read_text())
        if len(ks) >= 65:
            out[fp.stem] = ks
    return out


def detect(code, ks, i):
    """返回第 i 根（信号日）触发的 (claim, tier) 列表。
    自查修正（2026-09-12）：①不再假设信号日=最后一根（SHADOW_DATE 回填历史时错位）；
    ②LIMITDOWN 不在信号日剔一字——可成交性只能在入场日（i+1）判，注册时全量登记。"""
    if i < 65:
        return []
    c, pc = ks[i]["close"], ks[i - 1]["close"]
    if pc <= 0:
        return []
    chg = c / pc - 1
    hits = []
    if chg <= -0.03:
        hits.append(("REVERSAL_OPEN_T1", None))
        tier = ("-3~-5%" if chg > -0.05 else "-5~-7%" if chg > -0.07
                else "-7~-9.5%" if chg > -0.095 else "≤-9.5%")
        hits.append(("PANIC_DEPTH_DOSE", tier))
    if chg <= -0.095:
        hits.append(("LIMITDOWN_NEXT_DAY", None))
    return hits


def main():
    stocks = load_stocks()
    import os
    today = os.environ.get("SHADOW_DATE") or date.today().isoformat()  # SHADOW_DATE 供测试回填历史日
    last_dates = {ks[-1]["date"] for ks in stocks.values()}
    if today not in last_dates:
        print(f"[SILENT] kcache 最新 {max(last_dates)}，今日 {today} 无数据（非交易日或未刷新）")
        return

    # 1. 登记今日信号
    existing = set()
    if SHADOW.exists():
        for line in SHADOW.read_text().splitlines():
            r = json.loads(line)
            existing.add((r["signal_date"], r["claim"], r["code"]))
    new = 0
    with SHADOW.open("a") as f:
        for code, ks in stocks.items():
            idx = next((j for j in range(len(ks) - 1, -1, -1) if ks[j]["date"] == today), None)
            if idx is None:
                continue
            for claim, tier in detect(code, ks, idx):
                key = (today, claim, code)
                if key not in existing:
                    f.write(json.dumps({"signal_date": today, "claim": claim, "code": code,
                                        "tier": tier, "entry": None, "r1": None, "r5": None, "r20": None},
                                       ensure_ascii=False) + "\n")
                    new += 1

    # 2. 回填（重写整个 jsonl——单文件量级可控：每日几百条×数月）
    lines = [json.loads(x) for x in SHADOW.read_text().splitlines()]
    filled = 0
    for r in lines:
        ks = stocks.get(r["code"])
        if not ks:
            continue
        idx = {k["date"]: j for j, k in enumerate(ks)}
        si = idx.get(r["signal_date"])
        if si is None or si + 1 >= len(ks):
            continue
        if r["entry"] is None:
            e = ks[si + 1]["open"]
            if e <= 0:
                continue
            # 入场日可成交性（自查修正：一字剔除在入场日判，与 s10_retest 口径一致）
            pc0 = ks[si]["close"]
            gap = e / pc0 - 1 if pc0 > 0 else 0
            amp = (ks[si + 1]["high"] - ks[si + 1]["low"]) / pc0 if pc0 > 0 else 1
            if gap >= 0.095:
                r["untradeable"] = "一字涨停买不进"
                continue
            if gap <= -0.095 and amp < 0.01:
                r["untradeable"] = "一字跌停锁死"
                continue
            r["entry"] = e
            filled += 1
        if r["entry"]:
            e = r["entry"]
            for tag, off in [("r1", 1), ("r5", 5), ("r20", 20)]:
                if r[tag] is None and si + off < len(ks):
                    r[tag] = round(ks[si + off]["close"] / e - 1 - FEE, 5)
                    filled += 1
    SHADOW.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in lines) + "\n")

    # 3. 汇总（只统计 entry 已填的单）
    import statistics as st
    summ = {}
    for r in lines:
        if r["entry"] is None:
            continue
        for tag in ("r1", "r5", "r20"):
            v = r[tag]
            if v is None:
                continue
            key = (r["claim"], r["tier"] or "-", tag)
            summ.setdefault(key, []).append(v)
    out = {}
    for (claim, tier, tag), vs in sorted(summ.items()):
        out.setdefault(claim, {}).setdefault(tier, {})[tag] = {
            "n": len(vs), "win%": round(100 * sum(x > 0 for x in vs) / len(vs), 1),
            "mean%": round(100 * st.mean(vs), 2)}
    SUMMARY.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"shadow: 新登记 {new}，回填 {filled}，累计 {len(lines)} 单")


if __name__ == "__main__":
    main()

```

# 附件：主张注册表 claims_registry.yaml

`claims_registry.yaml` 完整内容：

```yaml
claims:
- id: CANDLE_UPPER_LOW
  statement: 低位避雷针(MA60下+长上影)相对位置匹配对照有正边际贡献
  detector: 避雷针_低位
  control: position_matched
  horizon:
  - 5
  - 20
  baseline_pp:
    5: 0.67
    20: 1.55
  kill_line_pp:
    5: 0.0
    20: 0.5
  grade: 候选L2L3（日历时间口径已证伪为独立策略，仅作确认指标）
  created: 2026-09-11
  audit_every_days: 7
- id: CANDLE_LOWER_LOW
  statement: 低位大长腿(MA60下+长下影)相对位置匹配对照有正边际贡献
  detector: 大长腿_低位
  control: position_matched
  horizon:
  - 5
  - 20
  baseline_pp:
    5: 0.35
    20: 1.07
  kill_line_pp:
    5: 0.0
    20: 0.5
  grade: 候选L2L3（平淡期regime闸门必须挂）
  created: 2026-09-11
  audit_every_days: 7
- id: TD9_BUY
  statement: TD9买入结构后T+3起有正edge（T+1为负）
  detector: TD9买入
  control: random_entry
  horizon:
  - 5
  - 20
  baseline_pp:
    5: 0.23
    20: 0.7
  kill_line_pp:
    5: 0.0
    20: 0.0
  grade: 降级观察（2023-26段edge≈0.05，疑似已死）
  created: 2026-09-11
  audit_every_days: 7
- id: HIGH_UPPER_DISTRIBUTION
  statement: 高位避雷针=出货形态（T+1正→T+20负的递减签名）
  detector: 避雷针_高位
  control: random_entry
  horizon:
  - 20
  baseline_pp:
    20: -0.48
  kill_line_pp:
    20: 0.2
  grade: 黑名单候选（作否决信号用）
  direction: negative
  created: 2026-09-11
  audit_every_days: 7
- id: REVERSAL_OPEN_T1
  statement: 反转族：T-1大跌后次日开盘买→次日尾盘，净+0.139%/49.8%（n=48.9万，含退市股+数据至9/11复审通过）
  detector: external:engine/entryexit_matrix.py
  grade: 候选L2（2026-09-12 含退市股复审通过，edge从+0.16%微降至+0.139%仍为正，唯一为正的反转腿）
  created: 2026-09-06
  audit_every_days: 30
  note: edge微降方向与幸存者偏差一致；下周审计起纳入滚动监控
- id: LIMITDOWN_NEXT_DAY
  statement: 跌停次日接 T+5 +2.65%/57.6%（一字剔除+含退市股口径，双段一致）
  detector: external:engine/strategy_zoo.py
  grade: 候选L2+（一字剔除✅ +2.72→幸存者修正后 +2.65%/57.6%（n=30684 含186退市股），双段 2.58/2.71 一致。幸存者偏差实测仅
    -0.07pp，方向如预测但幅度小）
  created: 2026-09-11
  audit_every_days: 30
  note: 一字剔除✅+含退市股✅，已达 external 背书下最高级；升 LAW 需影子前向20交易日
- id: MONDAY_EFFECT
  statement: 周一效应：周一日均+0.169%/60.8%（含退市股口径）
  detector: external:engine/factor_research.py
  grade: 候选L2+（2026-09-12 含退市股复审：+0.169%/60.8%，微降仍成立）
  created: 2026-09-11
  audit_every_days: 30
- id: TURNOVER_MAX_BLACKLIST
  statement: 高换手20%与彩票型20%组 91个月累计跑输-54.0%/-56.1%（含退市股，回避即相对收益）
  detector: external:engine/factor_research.py
  grade: 候选L2+（2026-09-12 含退市股复审：-54.0%/-56.1%，绞肉机结论强化）
  direction: negative
  created: 2026-09-11
  audit_every_days: 90
- id: PANIC_DEPTH_DOSE
  statement: 反转族/跌停接=恐慌深度单因子连续谱：T+1净额与同日超额随跌幅单调放大（-3~-5:+0.03 → ≤-9.5:+1.10，超额0.067→0.411）
  detector: external:engine/s3_combo.py
  grade: 候选L2（S3首测，含退市股+regime重建后数据）
  note: 分档仓位规则v1见sprint-s3报告；regime调制妖股期最佳，不用位置/星期闸门
  created: '2026-09-12'
  audit_every_days: 30

```

# 附件：审计状态 claims_state.json

`claims_state.json` 完整内容：

```json
{
 "CANDLE_UPPER_LOW": {
  "status": "DEAD",
  "consecutive_fails": 3,
  "history": [
   {
    "date": "2026-09-11",
    "verdicts": {
     "5": [
      -0.86,
      0.0,
      false
     ],
     "20": [
      -1.26,
      0.5,
      false
     ]
    }
   },
   {
    "date": "2026-09-11",
    "verdicts": {
     "5": [
      -0.92,
      0.0,
      false
     ],
     "20": [
      -1.51,
      0.5,
      false
     ]
    }
   },
   {
    "date": "2026-09-11",
    "verdicts": {
     "5": [
      -0.92,
      0.0,
      false
     ],
     "20": [
      -1.51,
      0.5,
      false
     ]
    }
   }
  ]
 },
 "CANDLE_LOWER_LOW": {
  "status": "DEAD",
  "consecutive_fails": 3,
  "history": [
   {
    "date": "2026-09-11",
    "verdicts": {
     "5": [
      -0.65,
      0.0,
      false
     ],
     "20": [
      0.16,
      0.5,
      false
     ]
    }
   },
   {
    "date": "2026-09-11",
    "verdicts": {
     "5": [
      -0.69,
      0.0,
      false
     ],
     "20": [
      -0.22,
      0.5,
      false
     ]
    }
   },
   {
    "date": "2026-09-11",
    "verdicts": {
     "5": [
      -0.69,
      0.0,
      false
     ],
     "20": [
      -0.22,
      0.5,
      false
     ]
    }
   }
  ]
 },
 "TD9_BUY": {
  "status": "DEAD",
  "consecutive_fails": 3,
  "history": [
   {
    "date": "2026-09-11",
    "verdicts": {
     "5": [
      -0.41,
      0.0,
      false
     ],
     "20": [
      -1.04,
      0.0,
      false
     ]
    }
   },
   {
    "date": "2026-09-11",
    "verdicts": {
     "5": [
      -0.44,
      0.0,
      false
     ],
     "20": [
      -1.2,
      0.0,
      false
     ]
    }
   },
   {
    "date": "2026-09-11",
    "verdicts": {
     "5": [
      -0.44,
      0.0,
      false
     ],
     "20": [
      -1.2,
      0.0,
      false
     ]
    }
   }
  ]
 },
 "HIGH_UPPER_DISTRIBUTION": {
  "status": "CANDIDATE",
  "consecutive_fails": 0,
  "history": [
   {
    "date": "2026-09-11",
    "verdicts": {
     "20": [
      -2.14,
      0.2,
      true
     ]
    }
   },
   {
    "date": "2026-09-11",
    "verdicts": {
     "20": [
      -2.71,
      0.2,
      true
     ]
    }
   },
   {
    "date": "2026-09-11",
    "verdicts": {
     "20": [
      -2.71,
      0.2,
      true
     ]
    }
   }
  ]
 },
 "REVERSAL_OPEN_T1": {
  "status": "CANDIDATE",
  "consecutive_fails": 0,
  "history": []
 },
 "LIMITDOWN_NEXT_DAY": {
  "status": "CANDIDATE",
  "consecutive_fails": 0,
  "history": []
 },
 "MONDAY_EFFECT": {
  "status": "CANDIDATE",
  "consecutive_fails": 0,
  "history": []
 },
 "TURNOVER_MAX_BLACKLIST": {
  "status": "CANDIDATE",
  "consecutive_fails": 0,
  "history": []
 }
}
```

# 附件：S3组合层结果 s3_combo.json

`s3_combo_20260912.json` 完整内容：

```json
{
 "A 反转×主线期": {
  "n": 14819,
  "win%": 50.3,
  "net%": 0.14,
  "同日超额%": 0.01
 },
 "A 反转×妖股期": {
  "n": 121992,
  "win%": 51.6,
  "net%": 0.26,
  "同日超额%": 0.205
 },
 "A 反转×恐慌期": {
  "n": 191891,
  "win%": 51.6,
  "net%": 0.18,
  "同日超额%": 0.049
 },
 "A 反转×平淡期": {
  "n": 151399,
  "win%": 48.3,
  "net%": 0.06,
  "同日超额%": 0.11
 },
 "B 反转×周一": {
  "n": 108735,
  "win%": 53.5,
  "net%": 0.29,
  "同日超额%": 0.067
 },
 "B 反转×周二": {
  "n": 93671,
  "win%": 52.8,
  "net%": 0.37,
  "同日超额%": 0.175
 },
 "B 反转×周三": {
  "n": 85430,
  "win%": 47.6,
  "net%": 0.1,
  "同日超额%": 0.117
 },
 "B 反转×周四": {
  "n": 92630,
  "win%": 46.5,
  "net%": -0.03,
  "同日超额%": 0.085
 },
 "B 反转×周五": {
  "n": 99635,
  "win%": 51.3,
  "net%": 0.04,
  "同日超额%": 0.098
 },
 "C 跌幅-3~-5%": {
  "n": 317000,
  "win%": 49.7,
  "net%": 0.03,
  "同日超额%": 0.067
 },
 "C 跌幅-3~-5% T+5": {
  "n": 316481,
  "win%": 48.6,
  "net%": 0.17
 },
 "C 跌幅-5~-7%": {
  "n": 95751,
  "win%": 50.6,
  "net%": 0.17,
  "同日超额%": 0.104
 },
 "C 跌幅-5~-7% T+5": {
  "n": 95607,
  "win%": 49.8,
  "net%": 0.24
 },
 "C 跌幅-7~-9.5%": {
  "n": 35398,
  "win%": 53.7,
  "net%": 0.42,
  "同日超额%": 0.197
 },
 "C 跌幅-7~-9.5% T+5": {
  "n": 35332,
  "win%": 51.9,
  "net%": 0.85
 },
 "C 跌幅≤-9.5%": {
  "n": 31952,
  "win%": 54.1,
  "net%": 1.1,
  "同日超额%": 0.411
 },
 "C 跌幅≤-9.5% T+5": {
  "n": 31917,
  "win%": 56.2,
  "net%": 2.13
 },
 "D 反转∩恐慌期": {
  "n": 191891,
  "win%": 51.6,
  "net%": 0.18,
  "同日超额%": 0.049
 },
 "D 反转∩非恐慌": {
  "n": 288210,
  "win%": 49.8,
  "net%": 0.15,
  "同日超额%": 0.145
 },
 "D 反转∩MA60下": {
  "n": 273849,
  "win%": 50.8,
  "net%": 0.13,
  "同日超额%": 0.028
 },
 "D 反转∩MA60上": {
  "n": 206252,
  "win%": 50.1,
  "net%": 0.2,
  "同日超额%": 0.211
 },
 "D 反转∩周四五信号": {
  "n": 192265,
  "win%": 49.0,
  "net%": 0.01,
  "同日超额%": 0.092
 },
 "D 基准 反转全量": {
  "n": 480101,
  "win%": 50.5,
  "net%": 0.16,
  "同日超额%": 0.107
 },
 "D 基准 反转全量 T+5": {
  "n": 479337,
  "win%": 49.6,
  "net%": 0.36
 }
}
```

# 附件：S10跌停接复核 s10_retest.json

`s10_retest_20260912.json` 完整内容：

```json
{
 "raw": {
  "全段": {
   "T+1尾盘": {
    "n": 31917,
    "win%": 54.1,
    "mean%": 1.1,
    "med%": 0.48
   },
   "T+5尾盘": {
    "n": 31917,
    "win%": 56.2,
    "mean%": 2.13,
    "med%": 1.62
   }
  },
  "前半": {
   "T+1尾盘": {
    "n": 14662,
    "win%": 54.7,
    "mean%": 1.07,
    "med%": 0.59
   },
   "T+5尾盘": {
    "n": 14662,
    "win%": 55.6,
    "mean%": 1.84,
    "med%": 1.33
   }
  },
  "后半": {
   "T+1尾盘": {
    "n": 17255,
    "win%": 53.6,
    "mean%": 1.12,
    "med%": 0.39
   },
   "T+5尾盘": {
    "n": 17255,
    "win%": 56.7,
    "mean%": 2.37,
    "med%": 1.87
   }
  }
 },
 "noLU": {
  "全段": {
   "T+1尾盘": {
    "n": 31880,
    "win%": 54.1,
    "mean%": 1.1,
    "med%": 0.49
   },
   "T+5尾盘": {
    "n": 31880,
    "win%": 56.2,
    "mean%": 2.12,
    "med%": 1.62
   }
  },
  "前半": {
   "T+1尾盘": {
    "n": 14653,
    "win%": 54.7,
    "mean%": 1.07,
    "med%": 0.59
   },
   "T+5尾盘": {
    "n": 14653,
    "win%": 55.6,
    "mean%": 1.83,
    "med%": 1.33
   }
  },
  "后半": {
   "T+1尾盘": {
    "n": 17227,
    "win%": 53.6,
    "mean%": 1.13,
    "med%": 0.4
   },
   "T+5尾盘": {
    "n": 17227,
    "win%": 56.7,
    "mean%": 2.37,
    "med%": 1.87
   }
  }
 },
 "noLU_noLD": {
  "全段": {
   "T+1尾盘": {
    "n": 30684,
    "win%": 56.2,
    "mean%": 1.15,
    "med%": 0.72
   },
   "T+5尾盘": {
    "n": 30684,
    "win%": 57.6,
    "mean%": 2.65,
    "med%": 1.97
   }
  },
  "前半": {
   "T+1尾盘": {
    "n": 13998,
    "win%": 57.3,
    "mean%": 1.13,
    "med%": 0.85
   },
   "T+5尾盘": {
    "n": 13998,
    "win%": 57.5,
    "mean%": 2.58,
    "med%": 1.8
   }
  },
  "后半": {
   "T+1尾盘": {
    "n": 16686,
    "win%": 55.4,
    "mean%": 1.17,
    "med%": 0.59
   },
   "T+5尾盘": {
    "n": 16686,
    "win%": 57.7,
    "mean%": 2.71,
    "med%": 2.11
   }
  }
 }
}
```

# 附件：submit闸门结果 law_pipeline_submit.json

`law_pipeline_submit_20260911.json` 完整内容：

```json
{
 "避雷针_低位": {
  "信号": "避雷针_低位",
  "闸门": {
   "G1_tNW≥3": "✅",
   "G2_时间分段": "✅",
   "G3_regime≥3/4": "✅",
   "G4_市值≥4/5": "✅",
   "G5_位置匹配边际>0": "✅",
   "G6_0.30%成本仍正": "✅"
  },
  "判决": "PASS 可入注册表",
  "位置匹配边际pp": {
   "5": 0.65,
   "20": 1.28
  },
  "日历时间DSR": 0.029,
  "每票每年触发": 1.82,
  "全样本": {
   "n": 46194,
   "win%": 51.5,
   "mean%": 0.89,
   "med%": 0.26,
   "t": 22.7
  },
  "随机对照": {
   "n": 9999,
   "win%": 47.8,
   "mean%": 0.14,
   "med%": -0.15,
   "t": 2.2
  }
 },
 "高窄旗形HTF": {
  "信号": "高窄旗形HTF",
  "闸门": {
   "G1_tNW≥3": "✅",
   "G2_时间分段": "❌",
   "G3_regime≥3/4": "❌",
   "G4_市值≥4/5": "❌",
   "G5_位置匹配边际>0": "❌",
   "G6_0.30%成本仍正": "❌"
  },
  "判决": "REJECT",
  "位置匹配边际pp": {
   "5": -0.76,
   "20": -1.14
  },
  "日历时间DSR": 0.102,
  "每票每年触发": 0.22,
  "全样本": {
   "n": 5485,
   "win%": 40.6,
   "mean%": -0.7,
   "med%": -1.33,
   "t": -6.2
  },
  "随机对照": {
   "n": 9999,
   "win%": 47.8,
   "mean%": 0.14,
   "med%": -0.15,
   "t": 2.2
  }
 },
 "涨停洗盘Shakeout": {
  "信号": "涨停洗盘Shakeout",
  "闸门": {
   "G1_tNW≥3": "❌",
   "G2_时间分段": "❌",
   "G3_regime≥3/4": "✅",
   "G4_市值≥4/5": "❌",
   "G5_位置匹配边际>0": "❌",
   "G6_0.30%成本仍正": "❌"
  },
  "判决": "REJECT",
  "位置匹配边际pp": {
   "5": -0.06,
   "20": -1.03
  },
  "日历时间DSR": 0.0,
  "每票每年触发": 0.11,
  "全样本": {
   "n": 2685,
   "win%": 44.2,
   "mean%": -0.09,
   "med%": -1.0,
   "t": -0.4
  },
  "随机对照": {
   "n": 9999,
   "win%": 47.8,
   "mean%": 0.14,
   "med%": -0.15,
   "t": 2.2
  }
 },
 "上升趋势跌停ULD": {
  "信号": "上升趋势跌停ULD",
  "闸门": {
   "G1_tNW≥3": "✅",
   "G2_时间分段": "❌",
   "G3_regime≥3/4": "❌",
   "G4_市值≥4/5": "❌",
   "G5_位置匹配边际>0": "❌",
   "G6_0.30%成本仍正": "❌"
  },
  "判决": "REJECT",
  "位置匹配边际pp": {
   "5": -1.02,
   "20": -0.92
  },
  "日历时间DSR": 0.0,
  "每票每年触发": 0.18,
  "全样本": {
   "n": 4473,
   "win%": 39.6,
   "mean%": -0.97,
   "med%": -2.23,
   "t": -6.0
  },
  "随机对照": {
   "n": 9999,
   "win%": 47.8,
   "mean%": 0.14,
   "med%": -0.15,
   "t": 2.2
  }
 }
}
```

# 附件：形态实测 candle_research.json

`candle_research_20260911.json` 完整内容：

```json
{
 "TD9买入": {
  "n": 268682,
  "win%": 51.8,
  "mean%": 0.42,
  "med%": 0.18
 },
 "TD9卖出": {
  "n": 198489,
  "win%": 44.3,
  "mean%": -0.1,
  "med%": -0.66
 },
 "大长腿_低位": {
  "n": 33011,
  "win%": 51.7,
  "mean%": 0.73,
  "med%": 0.27
 },
 "大长腿_高位": {
  "n": 48880,
  "win%": 42.5,
  "mean%": -0.61,
  "med%": -1.49
 },
 "避雷针_低位": {
  "n": 43034,
  "win%": 52.1,
  "mean%": 1.0,
  "med%": 0.33
 },
 "避雷针_高位": {
  "n": 95491,
  "win%": 45.1,
  "mean%": 0.08,
  "med%": -0.86
 },
 "随机对照": {
  "n": 20000,
  "win%": 47.9,
  "mean%": 0.19,
  "med%": -0.15
 }
}
```

# 附件：因子实测 factor_research.json

`factor_research_20260911.json` 完整内容：

```json
{
 "因子月度超额(相对全宇宙等权)": {
  "MAX彩票-最低20%": {
   "months": 91,
   "月均超额%": 0.12,
   "月胜率%": 51.6,
   "累计超额%": 9.3
  },
  "MAX彩票-最高20%": {
   "months": 91,
   "月均超额%": -0.85,
   "月胜率%": 34.1,
   "累计超额%": -56.1
  },
  "低价股-其余": {
   "months": 91,
   "月均超额%": -0.06,
   "月胜率%": 50.5,
   "累计超额%": -5.4
  },
  "低价股-最低20%": {
   "months": 91,
   "月均超额%": 0.24,
   "月胜率%": 49.5,
   "累计超额%": 20.7
  },
  "换手率-最低20%": {
   "months": 91,
   "月均超额%": 0.09,
   "月胜率%": 48.4,
   "累计超额%": 5.5
  },
  "换手率-最高20%": {
   "months": 91,
   "月均超额%": -0.79,
   "月胜率%": 38.5,
   "累计超额%": -54.0
  }
 },
 "日历效应-星期": {
  "周一": {
   "n": 365,
   "日均%": 0.169,
   "胜率%": 60.8
  },
  "周二": {
   "n": 376,
   "日均%": 0.115,
   "胜率%": 56.4
  },
  "周三": {
   "n": 376,
   "日均%": 0.043,
   "胜率%": 54.8
  },
  "周四": {
   "n": 378,
   "日均%": -0.017,
   "胜率%": 50.8
  },
  "周五": {
   "n": 367,
   "日均%": -0.028,
   "胜率%": 52.0
  }
 },
 "日历效应-月份": {
  "1月": {
   "n": 152,
   "日均%": -0.14,
   "胜率%": 46.7
  },
  "2月": {
   "n": 133,
   "日均%": 0.351,
   "胜率%": 63.9
  },
  "3月": {
   "n": 176,
   "日均%": 0.016,
   "胜率%": 53.4
  },
  "4月": {
   "n": 163,
   "日均%": -0.097,
   "胜率%": 51.5
  },
  "5月": {
   "n": 152,
   "日均%": 0.069,
   "胜率%": 56.6
  },
  "6月": {
   "n": 161,
   "日均%": 0.028,
   "胜率%": 56.5
  },
  "7月": {
   "n": 179,
   "日均%": 0.101,
   "胜率%": 57.5
  },
  "8月": {
   "n": 175,
   "日均%": 0.085,
   "胜率%": 57.7
  },
  "9月": {
   "n": 148,
   "日均%": 0.038,
   "胜率%": 51.4
  },
  "10月": {
   "n": 118,
   "日均%": 0.048,
   "胜率%": 50.8
  },
  "11月": {
   "n": 149,
   "日均%": 0.197,
   "胜率%": 57.7
  },
  "12月": {
   "n": 156,
   "日均%": 0.021,
   "胜率%": 55.1
  }
 }
}
```