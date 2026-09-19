# 红队审计报告 — 焚诀引擎 2026-09-19

按严重度排序。只报有依据的问题。

---

## 致命

### F1. `capacity_sim` 的 `pick="deep"` 排序键有除零/None 崩溃风险，且排序方向与注释相反
**文件**：`engine/law_pipeline.py` `capacity_sim` 内 `pick=="deep"` 分支
```python
cands.sort(key=lambda s: -(1 - stocks[s[0]]["c"][s[1]] / stocks[s[0]]["ma60"][s[1]])
           if stocks[s[0]]["ma60"][s[1]] else 0)
```
**问题**：
1. `ma60[s[1]]` 为 `None` 时，`if ... else 0` 只保护了 `None` 本身，但 `ma60[s[1]]` 若为 `0`（脏数据）会 `ZeroDivisionError`；`c[s[1]]` 为 0 也会崩。`_collect_sigs` 只过滤了 `c[i-1]<=0 or c[i]<=0`，没过滤 `ma60` 为 0。
2. 排序键 `-(1 - c/ma)`：`c/ma` 越小（越深跌）→ `1-c/ma` 越大 → 取负后越小 → **排在后面**。而注释写「超跌最深优先」。实际是**超跌最浅优先**，与宣称的 `pick="deep"` 语义相反。这是逻辑 bug，不是存疑。
3. `ma60` 为 `None` 时键取 `0`，会插到中间，破坏排序语义。

**修法**：
```python
def _deep_key(s):
    d = stocks[s[0]]; ma = d["ma60"][s[1]]; c = d["c"][s[1]]
    if not ma or ma <= 0 or c <= 0: return 1e9   # 无数据排最后
    return c / ma - 1                             # 越负越深，升序=最深优先
cands.sort(key=_deep_key)
```
并加断言/单测验证「deep 头名 = 当日距 MA60 最远者」。

---

### F2. `_ma60_exit_hold` 与 `exit_rule_grid` 的 `ma60_out` 口径不一致（宣称「对齐」但没对齐）
**文件**：`engine/law_pipeline.py` `_ma60_exit_hold` vs `engine/exit_rule_grid.py` `simulate` 的 `kind=="ma60"`
**问题**：
- `_ma60_exit_hold`：`if c[j] <= entry*0.905: continue`（跌停顺延），然后 `if ma[j] is not None and c[j] > ma[j]: return j-ei`。
- `exit_rule_grid`：`if sellable and c[j] <= entry*(1+LD_LOCK): continue`，`LD_LOCK=-0.095`，即 `c[j] <= entry*0.905` 顺延——**这条一致**。
- 但 `exit_rule_grid` 的 `ma60_out` 兜底是 `CAP_HOLD=21` 天，且兜底时若全程锁死返回 `None`（剔除）；`_ma60_exit_hold` 兜底 `min(cap, max(1, n-1-ei))`，**不剔除**，且 `cap=21` 但 `max(1, n-1-ei)` 可能 <21。
- 更关键：`_ma60_exit_hold` 从 `ei+1` 起判，`exit_rule_grid` 从 `ei` 起判但 `sellable = j > ei`，等价。**但 `_ma60_exit_hold` 的跌停顺延用 `entry*0.905`，而 `exit_rule_grid` 用 `entry*(1+LD_LOCK)`，`LD_LOCK=-0.095` → `entry*0.905`，一致。**
- 真正不一致：`_ma60_exit_hold` 里 `if c[j] <= 0 or c[j] <= entry*0.905: continue`——`c[j]<=0` 也顺延，`exit_rule_grid` 没有 `c[j]<=0` 分支（会直接算收益）。脏数据下行为不同。

**为什么是问题**：docstring 明写「对齐 exit_rule_grid ma60_out 口径」，但两处实现独立，未来任一处改动就会漂移。这正是项目自己立的「单实现纪律」被违反。

**修法**：`_ma60_exit_hold` 直接调用 `exit_rule_grid.simulate(d, i, ("ma60",))` 取持有天数，或把 `ma60_out` 逻辑抽到 `law_pipeline` 单一函数，`exit_rule_grid` 反向引用。

---

### F3. `claims_shadow.py` 的 `_lp_universe` 缓存与 `build_xsection` 的全局状态冲突
**文件**：`engine/claims_shadow.py` `_lp_universe`
```python
def _lp_universe():
    global _LP_CACHE
    if _LP_CACHE is None:
        import law_pipeline as lp
        stocks = lp.load_universe()
        lp.build_xsection(stocks)
        ...
```
**问题**：`build_xsection` 内部有 `if _XLADDER is not None: return` 的幂等守卫，但 `_XLDC` 在 `build_xsection` 开头被 `_XLDC = defaultdict(int)` **无条件重置**，然后才检查 `_XLADDER`。看代码：
```python
def build_xsection(stocks):
    global _XLADDER, _XCAP, _XREGIME, _IND, _XLOSERQ, _XFUND, _XLDC
    _XLDC = defaultdict(int)          # ← 先重置
    if _XLADDER is not None:
        return                        # ← 再返回
```
**为什么是问题**：如果 `claims_shadow` 先跑（`_XLADDER` 已建），再跑 `law_pipeline` 主流程调 `build_xsection`，`_XLDC` 会被清空成空 dict，而 `_XLADDER` 守卫直接 return，**跌停数横截面永久丢失**。`组合_跌停低_深跌_跌停潮` 依赖 `_XLDC`，会静默变成「跌停数=0」→ 该信号永不触发。这是静默错误，最危险。

**修法**：把 `_XLDC = defaultdict(int)` 移到 `if _XLADDER is not None: return` 之后，或纳入幂等守卫：
```python
if _XLADDER is not None:
    return
_XLDC = defaultdict(int)
```

---

## 严重

### S1. `_fund_healthy` 的「取之前最近记录」是 O(n) 线性扫描，且用 `max(ks)` 而非二分
**文件**：`engine/law_pipeline.py` `_fund_healthy`
```python
ks = [k for k in m.keys() if k <= dt]
if not ks: return False
cand = m[max(ks)]
```
**问题**：每个信号日都重建整个 key 列表，`m` 是日频（~2000 天），全市场 × 全历史 = O(N²)。`_collect_sigs` 里对每个 detector 每个 bar 都调 `_fund_healthy`，性能会炸。更严重的是**逻辑**：`m` 是 dict，`max(ks)` 是字符串比较，日期格式 `YYYY-MM-DD` 字符串比较正确，但**如果 fund_cache 里有非 ISO 格式日期**（如 `2026/09/19`），字符串比较会错。需确认 `fetch_fundamentals.FIELDS` 的日期格式。

**修法**：`_load_fund_xsection` 时把每个 code 的日期排序存成 `(dates, vals)` 元组，`_fund_healthy` 用 `bisect_right`。并加格式断言。

---

### S2. `_fund_healthy` 拿不到数据 = 不健康，导致「剔亏ST」类信号在 fund_cache 缺失时全灭
**文件**：`engine/law_pipeline.py` `_fund_healthy`
```python
if _XFUND is None: return False
m = _XFUND.get(d["code"])
if not m: return False
```
**问题**：`_XFUND` 是 `_load_fund_xsection()` 从 `data/fund_cache/*.json` 加载。如果某票没有 fund_cache（新股、退市、抓取失败），`_fund_healthy` 返回 `False`，该票**永远不进** `组合_跌停低_缩量_剔亏ST` 等信号。docstring 说「诚实缺席→视为不健康（宁缺毋滥）」，但这会**系统性剔除小票/新股**，与「小市值」组件方向冲突，且让「剔亏ST」的边际效应被「数据可得性」污染——你测的不是「剔亏ST有没有用」，而是「有 fund_cache 的票 vs 没有的票」。

**为什么是问题**：这是**选择偏差**，不是策略。`组合_跌停低_缩量_剔亏ST` 的 PASS 可能来自「有 fund_cache 的票本身更好」，而非「剔亏ST」。

**修法**：要么把「无数据」单独作为一档做敏感性分析（有数据/无数据分组对比），要么在 `_collect_sigs` 层面统计「因无 fund 数据被剔除的票占比」，若 >5% 必须报告。

---

### S3. `cross_matrix.py` 的对照采样 `rng.sample(ctrl_pool, ...)` 每次调用消耗 RNG 状态，导致「优于两单件」判定不可复现
**文件**：`engine/cross_matrix.py` `main` 内 `cs = rng.sample(ctrl_pool, min(len(idxs), len(ctrl_pool)))`
**问题**：`rng` 是全局 `random.Random(2026)`，在 `combinations` 循环里每次迭代都 `sample`，RNG 状态随迭代顺序变化。如果 `combinations` 顺序变（Python 版本、`NAMES` 顺序变），对照集就变，`marg` 变，`survivors` 变。**结果不可复现**。

**修法**：每个 pair 用独立 seed：`random.Random(hash((na,nb)) & 0xffffffff).sample(...)`，或预生成对照池的固定子集。

---

### S4. `cross_matrix.py` 的 `beats_both` 用 T+5 单点判定，但 `survivors` 用 `marg[5]>0 and beats_both and p5["win%"]>=55`——多重比较无校正
**文件**：`engine/cross_matrix.py` `main`
**问题**：45 对 × 6 horizon × 4 档消融 = 上千次比较，幸存线只有 `n≥200 + marg[5]>0 + beats_both + win%≥55`，**没有 t 值、没有 FDR/Bonferroni**。docstring 说「Stage 2 硬闸门」，但 Stage 1 的幸存判定本身就是多重比较重灾区。8 PASS 里有多少是噪声？

**修法**：Stage 1 幸存线加 `t_NW ≥ 2`（或至少 `mean/sd*sqrt(n) ≥ 2`），并对 45 对做 BH-FDR 校正。

---

### S5. `pick_ranker.py` 的 IC 计算是错的（秩相关实现有 bug）
**文件**：`engine/pick_ranker.py` `main` 内 IC 段
```python
rk_f = {k: rnk for rnk, (k, _) in enumerate(sorted(scored))}
rk_r = {k: rnk for rnk, k in enumerate(sorted(r for _, r in scored))}
...
cov = sum((rk_f[a] - mf) * (rk_r[b] - mr) for a, b in [(x[0], x[1]) for x in scored])
```
**问题**：
1. `rk_f` 的 key 是 `scored` 里的 `(feature, ret)` 元组？不，`sorted(scored)` 对 `(f, r)` 元组排序，`(k, _)` 解包后 `k` 是 feature 值。但 feature 值可能重复，`rk_f` 用 feature 值当 key，**重复 feature 会覆盖**，秩丢失。
2. `rk_r` 的 key 是 `r`（收益），同样重复收益会覆盖。
3. `cov` 里 `rk_f[a]` 和 `rk_r[b]` 用 `a=x[0]`（feature）、`b=x[1]`（ret），但 `rk_f` 的 key 是 feature 值、`rk_r` 的 key 是 ret 值——**如果 feature 和 ret 有相同数值，key 冲突**。
4. 这不是 Spearman，是「用值当 key 的伪秩相关」，重复值下完全错。

**修法**：用 `scipy.stats.spearmanr` 或手写正确的秩（`rankdata` 处理 ties）：
```python
from scipy.stats import spearmanr
ic, _ = spearmanr([x[0] for x in scored], [x[1] for x in scored])
```

---

### S6. `pick_ranker.py` 合成评分在循环内**修改 `evs` 里的 dict**，跨 horizon 污染
**文件**：`engine/pick_ranker.py` 合成评分段
```python
for f in FEATS[:5]:
    ...
    for e in evs:
        e[2][f"_z_{f}"] = (e[2][f] - m) / sd
```
**问题**：`evs` 是 `cluster[dt]` 的引用，`e[2]` 是 `feats` 返回的 dict。第一次 T+1 循环写入 `_z_深度` 等，第二次 T+5 循环**再次写入**（覆盖），但 `vs = [e[2][f] for e in evs]` 读的是原始 `f`，不是 `_z_f`，所以 z 分重算没问题。**但**：`e[2]` 被永久污染，如果后续代码读 `e[2]` 会看到 `_z_*` 键。当前无影响，但是定时炸弹。

**修法**：z 分算在局部 dict，不写回 `e[2]`。

---

### S7. `intraday_panic_grid.py` 的 `nw_t` 对配对差做检验，但配对样本不独立（同一事件多时点）
**文件**：`engine/intraday_panic_grid.py`
```python
t = nw_t([a - b for a, b in zip(rs, base_e)]) if sname != "9:30开" else 0
```
**问题**：`rs` 和 `base_e` 是同一批事件的「10:30 买」和「9:30 买」收益，配对差 `a-b` 是同一事件的两个时点。`nw_t` 若假设独立同分布，会低估方差（同一事件内相关）。且 `nw_t` 的 Newey-West 是时序自相关校正，这里 `rs` 是按事件顺序（code 遍历顺序）排列，**不是按时间排列**，NW 校正无意义。

**修法**：配对差用配对 t 检验（`scipy.stats.ttest_rel`），或按日期聚合后做 block bootstrap。

---

### S8. `intraday_panic_grid.py` 的除权哨兵逻辑有 bug：`prev` 只在 `dt2 in ratio` 时更新，但 `flagged` 判定用 `ratio[dt2]/ratio[prev]`
**文件**：`engine/intraday_panic_grid.py`
```python
for dt2 in ks_dates:
    if dt2 in ratio:
        if prev is not None and abs(ratio[dt2] / ratio[prev] - 1) > 0.015:
            flagged.add(dt2)
        prev = dt2
```
**问题**：`prev` 是上一个**有 ratio 的日期**，不是上一个交易日。如果中间有停牌/缺 m60 数据，`ratio[dt2]/ratio[prev]` 跨了多天，比值漂移可能来自多日累积而非除权。会**误标**。

**修法**：只在 `prev` 是 `dt2` 的前一交易日时才判定，否则跳过。

---

### S9. `shadow_rebuild.py` 的 `refill` 对 `CLOSE_ENTRY_CLAIMS` 用 `high<=low` 判一字板，但没判涨停一字
**文件**：`engine/shadow_rebuild.py` `refill`
```python
if r["claim"] in CLOSE_ENTRY_CLAIMS:
    if ks[si]["high"] <= ks[si]["low"]:
        r["untradeable"] = "信号日一字板买不进"
```
**问题**：`high<=low` 只判「一字」（全天一个价），但**一字涨停**和**一字跌停**都满足。收盘入场口径下，一字涨停买不进（封板），一字跌停**能买**（跌停价挂单成交）。这里把一字跌停也标成「买不进」，**误杀**。且 `claims_shadow.py` 主流程的 `CLOSE_ENTRY_CLAIMS` 分支没有这个判定（只判 `e>0`），**两处口径不一致**。

**修法**：`if ks[si]["high"] <= ks[si]["low"] and ks[si]["close"] > ks[si-1]["close"]`（一字涨停才买不进），或与 `claims_shadow.py` 主流程对齐。

---

### S10. `shadow_rebuild.py` 的 `refill` 对 open-entry 用 `gap>=0.095` 判一字涨停，但没考虑 `amp`
**文件**：`engine/shadow_rebuild.py` `refill`
```python
gap = e / pc0 - 1 if pc0 > 0 else 0
amp = (ks[si + 1]["high"] - ks[si + 1]["low"]) / pc0 if pc0 > 0 else 1
if gap >= 0.095:
    r["untradeable"] = "一字涨停买不进"
elif gap <= -0.095 and amp < 0.01:
    r["untradeable"] = "一字跌停锁死"
```
**问题**：`gap>=0.095` 判「开盘涨停」，但**开盘涨停不等于买不进**——如果盘中开板，开盘价能成交。真正买不进的是「开盘涨停且全天封死」（`amp<0.01`）。这里把「高开涨停但盘中开板」也标成买不进，**误杀**。而 `claims_shadow.py` 主流程的 open-entry 分支**没有这个判定**（只判 `e>0`），两处不一致。

**修法**：`if gap >= 0.095 and amp < 0.01`（一字涨停才买不进），与 `claims_shadow.py` 对齐。

---

## 轻微

### M1. `explain_card.py` 的 `stat` 输入是百分数，但 `odds` 计算用 `sum(wins)/len(wins)`——百分数下 odds 不变，但 `mean%` 注释说「不再乘 100」是对的，`win%` 也对。**但** `stat` 被 `cells` 调用时传入的是 `r["r5"]`（已是百分数），而 `winloss_autopsy.py` 的 `stat` 传入的是小数。**两个 `stat` 同名不同口径**，跨文件复制会错。

**修法**：统一 `stat` 输入为小数，输出时乘 100。

### M2. `explain_card.py` 的 `恐慌强度` 分档 `min(ldc.get(dt,0)//50*50, 200)`，`ldc` 是 `_XLDC`（defaultdict），`get` 返回 0 而非 KeyError，OK。但 `//50*50` 对 0-49 返回 0，50-99 返回 50，**边界正确**。无问题，仅记录。

### M3. `winloss_autopsy.py` 的 `f["一字跌停"] = h[i] == l[i]` 用浮点相等，脏数据下可能误判。建议 `abs(h[i]-l[i]) < 1e-6`。

### M4. `winloss_autopsy.py` 的 `f["跌停开板"] = h[i] > c[i]*1.001`——`1.001` 是 0.1% 容差，但涨停/跌停价是 `round(prev*1.1, 2)`，浮点误差可能 >0.1%。建议用 `h[i] > c[i] + 0.01`（一分钱）。

### M5. `nshape_study.py` 的 `is_nshape` 里 `for B in range(t-3, max(60, t-15), -1)`——`max(60, t-15)` 当 `t-15 < 60` 时下界是 60，但 `t` 最小 65，`t-15=50`，下界 60，**首板只能在 60~t-3 之间**，与 docstring「3~15 日前」不符（实际是 3~15 日或到 60 为止）。轻微口径漂移。

### M6. `nshape_study.py` 的 `simulate_exit_close` 里 `X_ma5` 用 `j >= t+4` 才判 MA5，但 `t+4` 时 `c[t-4:t+1]` 需要 `t>=4`，`t` 最小 65，OK。但 `X_ma5` 的 MA5 是 `c[j-4:j+1]`，**包含入场日**，而入场日是收盘买，MA5 含当日收盘——这是「当日收盘跌破 MA5 就卖」，但当日收盘你刚买，**T+1 不能卖**。`j` 从 `t+1` 起，`j>=t+4` 时 `j>t`，OK。无问题。

### M7. `good_regime_playbook.py` 的 `_strong_pullback_ma5` 用 `l[i] < ma5 <= c[i]`——`ma5` 是当日 MA5（含当日收盘），`l[i] < ma5` 是「盘中跌破」，`c[i] >= ma5` 是「收盘收回」。**但** `ma5` 含当日收盘，`c[i] >= ma5` 等价于 `c[i] >= (c[i-4]+...+c[i])/5`，即 `4*c[i] >= c[i-4]+...+c[i-1]`，这是「当日收盘拉回」。逻辑 OK，但**MA5 含当日**是「未来函数」吗？不，当日收盘时 MA5 可算。OK。

### M8. `regime_full_study.py` 的 `SIGS` 里有 `"反转族_T-1大跌"`、`"TD9买入"`，但 `REGISTRY` 里没有这两个 key（`REGISTRY` 有 `"TD9买入"` 吗？看 diff，`REGISTRY` 开头有 `"TD9买入": _td9buy`，OK；`"反转族_T-1大跌"` 不在 `REGISTRY`，`det = lp.REGISTRY.get(name)` 返回 `None`，`if det is None: continue`，**静默跳过**。用户以为测了，实际没测。

**修法**：`SIGS` 里不存在的 key 应打印警告。

### M9. `regime_full_study.py` 的 `tl_map` 从 `regime_timeline_hcap.json` 读，但 `regime = lp.load_regime()` 也读 regime，**两处 regime 源可能不一致**。`load_regime` 读哪个文件？需确认。若不同，`flip_days` 和 `cells` 的 regime 判定会错位。

### M10. `exit_rule_grid.py` 的 `simulate` 里 `tpsl` 分支：
```python
if hit_sl: return (entry*(1-sl))/entry - 1 - FEE, j-ei
if hit_tp: return tp - FEE, j-ei
```
`hit_sl` 用 `l[j] <= entry*(1-sl)`，`hit_tp` 用 `h[j] >= entry*(1+tp)`。同 bar 双触记止损——**保守**，OK。但 `return (entry*(1-sl))/entry - 1 - FEE` 等价于 `-sl - FEE`，**没考虑滑点/跌停无法成交**。若 `l[j]` 触及止损但当日跌停封死，实际卖不出。`LD_LOCK` 顺延只对 `c[j] <= entry*0.905` 生效，**盘中触及止损但收盘跌停**的情况没处理。

**修法**：`hit_sl` 时检查 `c[j] <= entry*0.905`，若是则顺延。

### M11. `exit_rule_grid.py` 的 `trail` 分支：`peak = max(peak, c[j])` 在 `sellable` 判定**之前**，即入场日 `j=ei` 也更新 peak。但入场日 `sellable=False`，不卖。OK。但 `peak` 用收盘价，**盘中最高价没进 peak**，移动止盈会滞后。这是口径选择，非 bug，但需在 docstring 说明。

### M12. `research_queue_20260919.py` 的 `r3` 加仓逻辑：
```python
if add_on_strength and not added and j == ei + 1:
    pc = d["o"][ei]
    if pc > 0 and d["c"][ei] / pc - 1 >= 0.03 and cash >= cap0/slots:
        ...
        keep.append((code, ei + 1, xi, cap0/slots, True))  # 加仓腿
```
**问题**：加仓腿 `ei+1` 开盘买，但 `xi` 是原腿的出场日 `i+1+hold`。加仓腿的出场日应该也是 `ei+1+hold`，但这里用 `xi`（原腿出场日），**加仓腿持有天数少 1 天**。且 `xi` 可能 < `ei+1`（若 hold 小），加仓腿立即出场。逻辑 bug。

**修法**：加仓腿 `xi_add = ei + 1 + hold`，独立出场。

### M13. `research_queue_20260919.py` 的 `r3` 里 `eqs.append(cash + sum(v for *_x, v, _a in pos))`——`pos` 元素是 5 元组 `(code, ei, xi, val, added)`，`*_x, v, _a` 解包为 `_x=[code,ei,xi]`, `v=val`, `_a=added`，OK。但 `capacity_sim` 里 `pos` 是 4 元组，**两处 pos 结构不同**，复制代码易错。

### M14. `research_queue_20260919.py` 的 `r4` 对照采样 `rng.sample(pool, min(len(hits_i)*2, len(pool)))`——`hits_i` 是 list，`len(hits_i)*2` 可能 > `len(pool)`，`min` 保护了。但 `rng` 是全局 `random.Random(19)`，跨票消耗状态，**不可复现**（同 S3）。

### M15. `research_queue_20260919.py` 的 `r5` 里 `idx = {x: j for j, x in enumerate(d["date"])}` 在**每个 code 的循环内**重建，O(N) per code，全市场 O(N²)。性能问题。

### M16. `research_queue_20260919.py` 的 `r5` 里 `if code in geju_codes or tick in geju_codes`——`geju_codes` 存的是 `r["ticker"]`（带 `.SH`/`.SZ`），`code` 是不带后缀的。`code in geju_codes` 永远 False，`tick in geju_codes` 才有效。冗余但无害。

### M17. `claims_shadow.py` 的 `main` 里 `n_has = sum(1 for ks in stocks.values() if any(k["date"] == today for k in ks[-6:]))`——只查最后 6 根 bar。如果 `SHADOW_DATE` 是 10 天前，`ks[-6:]` 不含该日，`n_has=0`，**误判为不存在**。回填历史日会失败。

**修法**：查全量 `any(k["date"] == today for k in ks)`，或二分。

### M18. `claims_shadow.py` 的 `detect` 里注册表桥：
```python
for claim, detname in REGISTRY_SHADOW_CLAIMS.items():
    try:
        if lp.REGISTRY[detname](d, j):
            hits.append((claim, None))
    except Exception:
        pass
```
**问题**：`except Exception: pass` 静默吞掉所有异常。如果 `lp.REGISTRY[detname]` 不存在（KeyError），或 detector 内部崩，**静默无信号**。用户以为注册了，实际没跑。

**修法**：至少 `except Exception as e: print(f"[WARN] {claim}: {e}")`。

### M19. `claims_shadow.py` 的 `_lp_universe` 里 `idx = {c: {x: j for j, x in enumerate(s["date"])} for c, s in stocks.items()}`——全市场建索引，内存 O(N)。且 `_LP_CACHE` 是模块级全局，**多进程/多线程不安全**。当前单进程 OK。

### M20. `law_pipeline.py` 的 `load_cap_quintiles` 里 `qs[m] = None` 对第一个月，但 `cap_quintile` 里 `b = qs.get(m)`，`b is None` 返回 `None`。**第一个月的信号全部无市值分位**，`G4_市值≥4/5` 会少一个月数据。轻微。

### M21. `law_pipeline.py` 的 `cap_at_date` 用 `bisect_right(dates, date) - 1`，`dates` 是字符串列表，`date` 是字符串。ISO 格式下字符串比较 = 日期比较，OK。但若 `dates` 含非 ISO 格式，错。

### M22. `law_pipeline.py` 的 `_collect_sigs` 里 `for i in range(61, n-6)`——`n-6` 而非 `n-22`，与 `run_pipeline` 的 `hi = n - max(HORIZONS) - 1`（`max=20`，`hi=n-21`）不一致。`_collect_sigs` 只到 `n-6`，**T+20 的信号被截断**。`capacity_sim` 用 `_collect_sigs`，hold=5 时 `n-6` 够，但若 hold 改大就错。

**修法**：`range(61, n - max(HORIZONS) - 1)`。

### M23. `law_pipeline.py` 的 `capacity_sim` 里 `dates = sorted({x for s in stocks.values() for x in s["date"]})`——全市场日期并集，O(N)。每次调用重建，`submit_gate` 调两次（cap1/cap5），`research_queue` 调 15 次，**性能浪费**。

### M24. `law_pipeline.py` 的 `capacity_sim` 里 `if k > 0: lst = sigs.get(dates[k-1], [])`——用 `dates[k-1]` 而非 `day` 的前一交易日。若 `dates` 有跳空（停牌日），`dates[k-1]` 是前一交易日，OK。但 `cands = [s for s in lst if didx[s[0]].get(day) == s[1]+1]`——`s[1]+1` 是信号日的下一根 bar，若该票停牌，`didx[code].get(day)` 可能不是 `s[1]+1`，**候选被过滤**。这是正确的（停牌买不进），但 `len(lst) < cluster_k` 用的是 `lst`（信号日全市场信号数），**不是可成交候选数**。成簇判定用原始信号数，OK。

### M25. `law_pipeline.py` 的 `capacity_sim` 里 `xidx = i + 1 + (_ma60_exit_hold(stocks[code], i+1) if exit_rule=="ma60" else hold)`——`_ma60_exit_hold` 返回持有天数，`i+1+hold_days` 是出场日索引。但 `_ma60_exit_hold` 内部 `for j in range(ei+1, min(ei+cap+1, n))`，返回 `j-ei`，即持有天数。`i+1+(j-ei) = i+1+j-(i+1) = j`，**出场日 = j**，正确。但 `_ma60_exit_hold` 兜底 `min(cap, max(1, n-1-ei))`，若 `n-1-ei < 1`，返回 1，`xidx = i+2`，可能 > `n`，后续 `if jj >= nn` 保护。OK。

### M26. `law_pipeline.py` 的 `capacity_sim` 里 `if jj >= nn or c2[jj] <= 0 or o2[ei] <= 0: keep.append(...); continue`——`jj = xi`，`xi` 是出场日索引