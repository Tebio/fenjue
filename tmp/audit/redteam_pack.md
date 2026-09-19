# 红队审计包 2026-09-19（焚诀引擎今日改动）
## 任务：专门找茬——逻辑bug、未来函数、口径不一致、统计错误、脏数据。逐条给：文件:位置 → 问题 → 为什么是问题 → 修法建议。不确定的标[存疑]。不要客气。

## 今日结论摘要（供核对实现是否符合宣称）
1. capacity_sim 新增 pick="deep"（超跌最深优先选票）与 exit_rule="ma60"（MA60回收离场）；G7 容量闸门=槽位资金曲线>0
2. 市值分位 PIT 修复：load_cap_quintiles 改为日频值+上月边界（旧版月末值+当月边界=未来函数）
3. _XLDC 全市场日跌停数；深跌（距MA60≤-25%）+跌停潮(≥100)组合 94.2% 胜率过全七闸
4. 全交叉矩阵 45 对消融→8 PASS；pick_ranker 头名超额+0.88pp/日
5. intraday_panic_grid：10:30 买优于开盘（t=15-17）
6. winloss_autopsy：深度/恐慌强度是胜负分界
7. shadow_rebuild：影子账本 4098 单全量重算（T+1 时序修正）
8. good_regime_playbook：主线期缺口低开低位阳线 85.7%/+6.61%


===== tmp/audit/diff_core.txt =====
diff --git a/engine/claims_shadow.py b/engine/claims_shadow.py
index b170efef..bd1ff9a7 100644
--- a/engine/claims_shadow.py
+++ b/engine/claims_shadow.py
@@ -22,6 +22,45 @@ FEE = 0.0015
 # 入场口径=信号日收盘（打板成交假设，fill 率由影子前向中的封板时间另行定量），
 # 与框架默认的次日开盘不同——次日追是该主张内部已证伪的变体（-0.52%）。
 CLOSE_ENTRY_CLAIMS = {"FRONTRUN_FIRSTBOARD_V2", "WATCHPOOL_GRAD"}
+
+# 2026-09-19：注册表桥——夜间流水线新 PASS 组合进影子前向（L5）。
+# 通过 law_pipeline REGISTRY 检测器原样执行，禁止在 detect() 里重复实现（口径漂移风险）。
+# claim_id 必须与 data/claims_registry.yaml 的 id 一致。
+REGISTRY_SHADOW_CLAIMS = {
+    "COMP_LIMITDOWN_LOW_SHRINK_XFUND": "组合_跌停低_缩量_剔亏ST",
+    "COMP_LIMITDOWN_LOW_LOSER250_OS20_SHRINK": "组合_跌停低_输家_超跌20_缩量",
+    "COMP_LIMITDOWN_LOW_3DOWN_SHRINK": "组合_跌停低_三连阴_缩量",
+    "COMP_LIMITDOWN_LOW_BIGUPPER_SHRINK": "组合_跌停低_避雷针_缩量",
+    "COMP_LIMITDOWN_LOW_LOSER250_OS20_XFUND": "组合_跌停低_输家_超跌20_剔亏ST",
+    "COMP_LIMITDOWN_LOW_TD9": "组合_跌停低_TD9买入滤",
+    "COMP_LIMITDOWN_LOW_LOSER250_OS20_TD9": "组合_跌停低_输家_超跌20_TD9滤",
+    # 全交叉矩阵幸存对（2026-09-19 cross_matrix 8 PASS）
+    "CROSS_LOW_SHRINK_BIGUPPER": "交叉_跌停低_缩量_避雷针低",
+    "CROSS_LOW_SHRINK_XFUND": "交叉_跌停低_缩量_剔亏ST",
+    "CROSS_LOW_SHRINK_GAPDOWN": "交叉_跌停低_缩量_缺口低开",
+    "CROSS_LOW_3DOWN_LOSER250": "交叉_跌停低_三连阴_输家250",
+    "CROSS_LOW_3DOWN_OS20": "交叉_跌停低_三连阴_超跌20",
+    "CROSS_LOW_LOSER250_BIGUPPER": "交叉_跌停低_输家250_避雷针低",
+    "CROSS_LOW_TD9_GAPDOWN": "交叉_跌停低_TD9买入_缺口低开",
+    # 胜负解剖细分（2026-09-19，深度+恐慌强度分界）
+    "COMP_LIMITDOWN_LOW_DEEP": "组合_跌停低_深跌",
+    "COMP_LIMITDOWN_LOW_DEEP_LDC100": "组合_跌停低_深跌_跌停潮",
+    "COMP_LIMITDOWN_LOW_3DOWN_DEEP": "组合_跌停低_三连阴_深跌",
+}
+
+_LP_CACHE = None
+
+
+def _lp_universe():
+    """law_pipeline 宇宙懒加载（每跑一次日线影子只建一次，约 1-2 分钟）。"""
+    global _LP_CACHE
+    if _LP_CACHE is None:
+        import law_pipeline as lp
+        stocks = lp.load_universe()
+        lp.build_xsection(stocks)
+        idx = {c: {x: j for j, x in enumerate(s["date"])} for c, s in stocks.items()}
+        _LP_CACHE = (lp, stocks, idx)
+    return _LP_CACHE
 _industry = None
 _stock_cap = None
 _regime_tl = None
@@ -49,12 +88,12 @@ def stock_caps():
     global _stock_cap
     if _stock_cap is None:
         import glob
+        import bisect as _bis
         cap = {}
         for fp in glob.glob(str(ROOT / "data/cap_hist/*.json")):
-            d = {}
-            for dt, _px, c in json.loads(open(fp).read()):
-                d[dt[:7]] = c
-            cap[Path(fp).stem] = d
+            rows = sorted(json.loads(open(fp).read()), key=lambda r: r[0])
+            # 2026-09-19 PIT 修复：存 (dates, caps) 日频，弃「月度=月末值」旧口径
+            cap[Path(fp).stem] = ([r[0] for r in rows], [r[2] for r in rows])
         _stock_cap = cap
     return _stock_cap
 
@@ -98,7 +137,13 @@ def detect(code, ks, i, ladder=None):
             if first:
                 industry = industry_map().get(code, {}).get("industry") or "?"
                 if ladder.get(industry, 0) >= 3:
-                    cap = stock_caps().get(code, {}).get(ks[i]["date"][:7])
+                    cap = None
+                    packed = stock_caps().get(code)
+                    if packed:  # 2026-09-19 PIT：不晚于当日的最近市值
+                        import bisect as _b
+                        dts, cps = packed
+                        _j = _b.bisect_right(dts, ks[i]["date"]) - 1
+                        cap = cps[_j] if _j >= 0 else None
                     if cap is not None and 20 <= cap <= 400:
                         # tier=当日regime（2026-09-12：反人群打板假设的前向测量——恐慌/平淡期fill是漏，主线/妖股期是坑）
                         reg = _regime_of(ks[i]["date"])
@@ -127,6 +172,21 @@ def detect(code, ks, i, ladder=None):
                 continue
             hits.append(("WATCHPOOL_GRAD", None))
             break
+    # 注册表桥（2026-09-19）：新 PASS 组合委托 law_pipeline REGISTRY 检测器判定
+    if REGISTRY_SHADOW_CLAIMS:
+        try:
+            lp, lp_stocks, lp_idx = _lp_universe()
+            d = lp_stocks.get(code)
+            j = lp_idx.get(code, {}).get(ks[i]["date"]) if d is not None else None
+            if j is not None:
+                for claim, detname in REGISTRY_SHADOW_CLAIMS.items():
+                    try:
+                        if lp.REGISTRY[detname](d, j):
+                            hits.append((claim, None))
+                    except Exception:
+                        pass
+        except Exception:
+            pass
     return hits
 
 
@@ -134,9 +194,16 @@ def main():
     stocks = load_stocks()
     import os
     today = os.environ.get("SHADOW_DATE") or date.today().isoformat()  # SHADOW_DATE 供测试回填历史日
-    last_dates = {ks[-1]["date"] for ks in stocks.values()}
-    if today not in last_dates:
-        print(f"[SILENT] kcache 最新 {max(last_dates)}，今日 {today} 无数据（非交易日或未刷新）")
+    last_max = max(ks[-1]["date"] for ks in stocks.values())
+    if os.environ.get("SHADOW_DATE"):
+        # 显式回填历史日：只要求该日在数据里真实存在（多数票有当日 bar），
+        # 不能用「等于最新交易日」当守卫——那会让所有补登记日一律 [SILENT]（2026-09-18 修）
+        n_has = sum(1 for ks in stocks.values() if any(k["date"] == today for k in ks[-6:]))
+        if n_has < 0.5 * len(stocks):
+            print(f"[SILENT] SHADOW_DATE={today} 在 kcache 中不存在（{n_has}/{len(stocks)} 票有当日 bar）")
+            return
+    elif today not in {ks[-1]["date"] for ks in stocks.values()}:
+        print(f"[SILENT] kcache 最新 {last_max}，今日 {today} 无数据（非交易日或未刷新）")
         return
 
     # 1. 登记今日信号（先算今日行业梯队，供 FRONTRUN 检测）
@@ -207,9 +274,15 @@ def main():
                 filled += 1
         if r["entry"]:
             e = r["entry"]
+            # T+1 时序硬断言（2026-09-18 修）：出场日必须严格晚于入场日。
+            # 旧实现用 off 从信号日 si 起算，open-entry 族（反转/跌停接）变成
+            # 「当日开盘买 → 当日收盘卖」= T+0，物理不可能成交（A股 T+1）。
+            # 现改为从入场日 ei 起算：ei=si（收盘入场）/ei=si+1（次日开盘入场）。
+            ei = si if r["claim"] in CLOSE_ENTRY_CLAIMS else si + 1
             for tag, off in [("r1", 1), ("r5", 5), ("r20", 20)]:
-                if r[tag] is None and si + off < len(ks):
-                    r[tag] = round(ks[si + off]["close"] / e - 1 - FEE, 5)
+                if r[tag] is None and ei + off < len(ks):
+                    assert ei + off > ei, "出场日必须晚于入场日"
+                    r[tag] = round(ks[ei + off]["close"] / e - 1 - FEE, 5)
                     filled += 1
     SHADOW.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in lines) + "\n")
 
diff --git a/engine/law_pipeline.py b/engine/law_pipeline.py
index 92749786..e83b33b7 100644
--- a/engine/law_pipeline.py
+++ b/engine/law_pipeline.py
@@ -69,26 +69,46 @@ def load_regime():
 
 
 def load_cap_quintiles():
-    per_month, stock_cap = {}, {}
+    """市值分位（2026-09-19 PIT 修复）：
+    旧实现两重月内未来函数——①个股月值取的是月末（循环覆写留下最后一行）；
+    ②分位边界用当月全月数据（月初信号用了含未来 20 天的横截面）。
+    现改为：个股取「不晚于当日的最近日值」；分位边界=上月全月（完全在过去）。
+    影响面：G4 市值闸门、_cap_ok（banlu/frontrun 市值带）、fundamental_commonality。"""
+    per_month, stock_cap_daily = {}, {}
     for fp in glob.glob(str(CAP / "*.json")):
         code = Path(fp).stem
-        d = {}
-        for date, _px, cap in json.loads(open(fp).read()):
-            m = date[:7]
-            d[m] = cap
-            per_month.setdefault(m, []).append(cap)
-        stock_cap[code] = d
+        rows = sorted(json.loads(open(fp).read()), key=lambda r: r[0])
+        stock_cap_daily[code] = ([r[0] for r in rows], [r[2] for r in rows])  # (dates, caps) 预拆分
+        for date, _px, cap in rows:
+            per_month.setdefault(date[:7], []).append(cap)
+    import bisect as _bis
     qs = {}
-    for m, caps in per_month.items():
-        caps.sort()
+    months = sorted(per_month)
+    for k, m in enumerate(months):
+        if k == 0:
+            qs[m] = None
+            continue
+        caps = sorted(per_month[months[k - 1]])           # 边界=上月横截面（全在过去）
         n = len(caps)
         qs[m] = [caps[int(n * p)] for p in (0.2, 0.4, 0.6, 0.8)] if n >= 50 else None
-    return stock_cap, qs
+    return stock_cap_daily, qs
+
+
+def cap_at_date(stock_cap_daily, code, date):
+    """不晚于 date 的最近流通市值（二分）。None=无数据。packed=(dates, caps)。"""
+    import bisect
+    packed = stock_cap_daily.get(code)
+    if not packed:
+        return None
+    dates, caps = packed
+    j = bisect.bisect_right(dates, date) - 1
+    return caps[j] if j >= 0 else None
 
 
 def cap_quintile(stock_cap, qs, code, date):
+    """stock_cap=日频行（PIT 修复版）；边界=上月横截面。"""
     m = date[:7]
-    cap = stock_cap.get(code, {}).get(m)
+    cap = cap_at_date(stock_cap, code, date)
     b = qs.get(m)
     if cap is None or b is None:
         return None
@@ -205,7 +225,7 @@ def run_pipeline(name, detect, stocks, regime, stock_cap, qs, horizon=HORIZON, f
     for code, d in stocks.items():
         c, o, n = d["c"], d["o"], d["n"]
         hi = n - max(HORIZONS) - 1
-        sc = stock_cap.get(code, {})
+        sc = stock_cap.get(code, [])
         for i in range(START, hi):
             if _epx(d, i) <= 0 or not detect(d, i):
                 continue
@@ -216,7 +236,7 @@ def run_pipeline(name, detect, stocks, regime, stock_cap, qs, horizon=HORIZON, f
             seg_t["2019-2022" if dt < "2023" else "2023-2026"].append(r)
             seg_r.setdefault(regime.get(dt, "?"), []).append(r)
             b = qs.get(dt[:7])
-            cap = sc.get(dt[:7])
+            cap = cap_at_date(stock_cap, code, dt)   # PIT 修复（2026-09-19）：不晚于当日的市值
             if cap is not None and b:
                 seg_c[sum(cap > x for x in b)].append(r)
         for _ in range(3):
@@ -290,6 +310,104 @@ def matched_marginal(detect, stocks, horizons, fee=0.0015, seed=7):
     return out
 
 
+def _collect_sigs(detect, stocks):
+    """收集某 detector 的全部信号：date -> [(code, i)]（i=信号日票内索引）"""
+    sigs = {}
+    for code, d in stocks.items():
+        c, o, ma, n = d["c"], d["o"], d["ma60"], d["n"]
+        for i in range(61, n - 6):
+            if c[i-1] <= 0 or c[i] <= 0 or o[i+1] <= 0 or ma[i] is None:
+                continue
+            if o[i+1] <= c[i]*0.905:          # 次日开盘一字跌停＝买不到
+                continue
+            try:
+                if detect(d, i):
+                    sigs.setdefault(d["date"][i], []).append((code, i))
+            except Exception:
+                pass
+    return sigs
+
+
+def _ma60_exit_hold(d, ei, cap=21):
+    """MA60 回收离场的持有天数（2026-09-19，对齐 exit_rule_grid ma60_out 口径）：
+    入场日 ei（次日开盘买）不可卖（T+1）；从 ei+1 起首个「收盘收复 MA60」日离场；
+    跌停封死（收盘≤入场价×0.905）顺延；兜底 cap 天。"""
+    c, o, ma, n = d["c"], d["o"], d["ma60"], d["n"]
+    entry = o[ei]
+    for j in range(ei + 1, min(ei + cap + 1, n)):
+        if c[j] <= 0 or c[j] <= entry * 0.905:
+            continue
+        if ma[j] is not None and c[j] > ma[j]:
+            return j - ei
+    return min(cap, max(1, n - 1 - ei))
+
+
+def capacity_sim(sigs, stocks, slots=10, hold=5, seeds=3, cluster_k=1, fee=0.0015, cap0=1_000_000.0, exit_rule=None, pick="random"):
+    """G7 容量检验（2026-09-18 立）：固定槽位下的资金曲线模拟。
+
+    规则：信号日收盘确认 → **次日开盘买**（开盘一字跌停作废）→ **入场日 +hold 个交易日收盘卖**
+          （出场日跌停封死顺延≤3日）→ 往返 fee → 每槽 cap0/slots，槽满则跳过（记溢出）。
+    cluster_k：只在「当日全市场信号数 ≥ cluster_k」的成簇日出手（收盘可知，无前视）。
+    exit_rule="ma60"（2026-09-19 加）：出场改用 MA60 回收离场（_ma60_exit_hold），其余不变。
+    pick="deep"（2026-09-19 pick_ranker 实证）：成簇日候选按「超跌最深」（距MA60最远）优先吃槽，
+          替代随机——头名超额 +0.88pp/日、IC +0.117，是唯一真排名器。
+    返回随机选票 seeds 次的平均指标。
+    """
+    import random as _random
+    if not sigs:
+        return None
+    dates = sorted({x for s in stocks.values() for x in s["date"]})
+    didx = {c: {x: j for j, x in enumerate(s["date"])} for c, s in stocks.items()}
+    out = []
+    for seed in range(seeds):
+        rnd = _random.Random(seed)
+        cash, pos, trades, eqs = cap0, [], [], []
+        for k, day in enumerate(dates):
+            keep = []
+            for code, ei, xi, val in pos:
+                j = didx[code].get(day, -1)
+                if j < 0 or j < xi:
+                    keep.append((code, ei, xi, val)); continue
+                d = stocks[code]
+                c2, o2, nn = d["c"], d["o"], d["n"]
+                jj = xi  # 2026-09-19：原为 ei+hold，与默认口径 xi==ei+hold 等价；改 xi 后规则化出场（exit_rule）才生效
+                if jj >= nn or c2[jj] <= 0 or o2[ei] <= 0:
+                    keep.append((code, ei, xi, val)); continue
+                r = c2[jj]/o2[ei] - 1 - fee
+                cash += val*(1+r)
+                trades.append(r*100)
+            pos = keep
+            if k > 0:
+                lst = sigs.get(dates[k-1], [])
+                cands = [s for s in lst if didx[s[0]].get(day) == s[1]+1]
+                if len(lst) < cluster_k:
+                    cands = []
+                if pick == "deep":
+                    # 超跌最深优先（距MA60最远）；选票特征信号日收盘可知，无前视
+                    cands.sort(key=lambda s: -(1 - stocks[s[0]]["c"][s[1]] / stocks[s[0]]["ma60"][s[1]])
+                               if stocks[s[0]]["ma60"][s[1]] else 0)
+                else:
+                    rnd.shuffle(cands)
+                for code, i in cands[:max(0, slots - len(pos))]:
+                    if cash < cap0/slots:
+                        break
+                    cash -= cap0/slots
+                    xidx = i + 1 + (_ma60_exit_hold(stocks[code], i + 1) if exit_rule == "ma60" else hold)
+                    pos.append((code, i+1, xidx, cap0/slots))
+            eqs.append(cash + sum(v for *_x, v in pos))
+        yrs = len(dates)/244.0
+        final = eqs[-1] if eqs else cap0
+        peak, mdd = -1e18, 0
+        for e in eqs:
+            peak = max(peak, e)
+            mdd = min(mdd, e/peak - 1)
+        out.append({"年化%": round(((final/cap0)**(1/yrs)-1)*100, 1), "期末x": round(final/cap0, 2),
+                    "回撤%": round(mdd*100, 1), "笔数": len(trades),
+                    "均笔%": round(sum(trades)/len(trades), 2) if trades else 0,
+                    "胜率%": round(sum(1 for x in trades if x > 0)/len(trades)*100, 1) if trades else 0})
+    return {k: round(sum(o[k] for o in out)/len(out), 2) for k in out[0]}
+
+
 def submit_gate(name, detect, stocks, regime, stock_cap, qs):
     """WorldQuant BRAIN 式提交闸门：新信号入库前的确定性全检。
     硬闸门（任一不过即拒收，exit 1）：
@@ -312,6 +430,9 @@ def submit_gate(name, detect, stocks, regime, stock_cap, qs):
         g3 = sum(1 for v in cells.values() if v["mean%"] > 0) >= len(cells) - 1
     else:
         g3 = bool(cells) and all(v["mean%"] > 0 for v in cells.values())
+    _sigs = _collect_sigs(detect, stocks)
+    cap1 = capacity_sim(_sigs, stocks, slots=10, hold=5, seeds=3, cluster_k=1)
+    cap5 = capacity_sim(_sigs, stocks, slots=10, hold=5, seeds=3, cluster_k=5)
     gates = {
         "G1_tNW≥3": abs(d5.get("t_NW") or 0) >= NW_MIN_T,
         "G2_时间分段": all(v and v["mean%"] > 0 for v in r["时间分段"].values()),
@@ -319,10 +440,15 @@ def submit_gate(name, detect, stocks, regime, stock_cap, qs):
         "G4_市值≥4/5": sum(1 for v in r["市值五分位"].values() if v and v["mean%"] > 0) >= len(r["市值五分位"]) - 1,
         "G5_位置匹配边际>0": bool(marg) and all(v > 0 for v in marg.values()),
         "G6_0.30%成本仍正": (r["成本压力"].get("0.30%") or {}).get("mean%", -9) > 0,
+        # G7（2026-09-18 立）：容量/可执行性——槽位10 下的资金曲线必须为正；
+        # 若原始规则为负但「成簇日过滤(K≥5)」转正，标记 ⚠️（需带过滤执行）
+        "G7_槽位10资金曲线>0": bool(cap1) and cap1["年化%"] > 0,
     }
     passed = all(gates.values())
     verdict = {"信号": name, "闸门": {k: "✅" if v else "❌" for k, v in gates.items()},
                "判决": "PASS 可入注册表" if passed else "REJECT",
+               "容量": {"槽10_K1": cap1, "槽10_K5": cap5,
+                        "注释": "K1=原始规则；K5=只在当日全市场信号≥5 的成簇日出手"},
                "入场口径": ENTRY_MODE,
                "位置匹配边际pp": marg, "日历时间DSR": r["DSR概率"],
                "时间分段": r["时间分段"], "regime分段": r["regime分段"], "衰减曲线": r["衰减曲线"],
@@ -340,11 +466,56 @@ _XCAP = None      # code -> month(YYYY-MM) -> 流通市值(亿)
 _XREGIME = None   # date -> regime
 _IND = None       # code -> industry
 _XLOSERQ = None   # date -> 当日全市场250日回报的Q20边界（长周期反转横截面）
+_XFUND = None     # code -> date -> (peTTM, isST)；fund_cache baostock 日频（2026-09-18 夜间批立）
+_XLDC = None      # date -> 当日全市场跌停数（2026-09-19 胜负解剖：恐慌强度）
+
+
+def _load_fund_xsection():
+    """fund_cache -> code -> {date: (peTTM, isST)}。行格式见 fetch_fundamentals.FIELDS。
+    已知限制（2026-09-18 对账发现）：baostock isST 标记滞后（ST富煌实测标0），
+    亏损剔除以 peTTM<=0 为主，isST 为辅。"""
+    out = {}
+    fdir = ROOT / "data/fund_cache"
+    if not fdir.exists():
+        return out
+    for fp in fdir.glob("*.json"):
+        try:
+            rows = json.loads(fp.read_text())
+        except Exception:
+            continue
+        m = {}
+        for r in rows:
+            if len(r) >= 9:
+                m[r[0]] = (r[5], r[8])
+        if m:
+            out[fp.stem] = m
+    return out
+
+
+def _fund_healthy(d, i):
+    """财报健康过滤器：当日 peTTM>0（剔亏损）且非 ST。取信号日或之前最近记录。
+    拿不到数据 = None（诚实缺席）→ 视为不健康（宁缺毋滥，防止脏数据混进策略）。"""
+    if _XFUND is None:
+        return False
+    m = _XFUND.get(d["code"])
+    if not m:
+        return False
+    dt = d["date"][i]
+    cand = m.get(dt)
+    if cand is None:
+        # 取之前最近一个交易日记录（财报是低频数据）
+        ks = [k for k in m.keys() if k <= dt]
+        if not ks:
+            return False
+        cand = m[max(ks)]
+    pe, is_st = cand
+    return (pe is not None and pe > 0) and str(is_st) != "1"
 
 
 def build_xsection(stocks):
     from collections import defaultdict
-    global _XLADDER, _XCAP, _XREGIME, _IND, _XLOSERQ
+    global _XLADDER, _XCAP, _XREGIME, _IND, _XLOSERQ, _XFUND, _XLDC
+    _XLDC = defaultdict(int)
     if _XLADDER is not None:
         return
     ind_map = json.loads((ROOT / "data/industry_map.json").read_text())
@@ -357,6 +528,8 @@ def build_xsection(stocks):
         for i in range(1, n):
             if c[i - 1] > 0 and c[i] / c[i - 1] - 1 >= 0.098:
                 lad[dates[i]][ind] += 1
+            if c[i - 1] > 0 and c[i] / c[i - 1] - 1 <= -0.095:
+                _XLDC[dates[i]] += 1   # 2026-09-19 胜负解剖：全市场日跌停数（恐慌强度曲线）
         # 250日回报（长周期反转横截面用）
         for i in range(250, n):
             if c[i - 250] > 0:
@@ -366,6 +539,7 @@ def build_xsection(stocks):
     _XLOSERQ = {dt: sorted(v)[int(len(v) * 0.2)] for dt, v in r250_by_date.items() if len(v) >= 500}
     _XCAP, _qs = load_cap_quintiles()
     _XREGIME = load_regime()
+    _XFUND = _load_fund_xsection()
 
 
 def _limitup(d, i):
@@ -391,7 +565,7 @@ def _ladder(d, i):
 
 
 def _cap_ok(d, i):
-    m = _XCAP.get(d["code"], {}).get(d["date"][i][:7])
+    m = cap_at_date(_XCAP, d["code"], d["date"][i])
     return m is not None and 20 <= m <= 400
 
 def _td9buy(d, i):
@@ -473,6 +647,28 @@ def _limitdown(d, i):
     return True
 
 
+def _shrink_board(d, i):
+    """缩量涨停（量比<0.8）：收盘涨停 + 当日量 < 前5日均量×0.8（#77b 晋级率1.7x放量板）"""
+    c, v = d["c"], d["v"]
+    if c[i - 1] <= 0 or c[i] / c[i - 1] - 1 < 0.098:
+        return False
+    if i < 5:
+        return False
+    v5 = sum(v[i - 5:i]) / 5
+    return v5 > 0 and v[i] / v5 < 0.8
+
+
+def _vol_board(d, i):
+    """放量涨停（量比≥1.5）：晋级段对照组"""
+    c, v = d["c"], d["v"]
+    if c[i - 1] <= 0 or c[i] / c[i - 1] - 1 < 0.098:
+        return False
+    if i < 5:
+        return False
+    v5 = sum(v[i - 5:i]) / 5
+    return v5 > 0 and v[i] / v5 >= 1.5
+
+
 def _loser250(d, i):
     """长周期反转（De Bondt-Thaler）：当日 250 日回报处于全市场最低五分位。
     注意：输家状态是连续的（入组后天天触发），事件高度重叠——以日历时间层/DSR 为准。"""
@@ -580,6 +776,173 @@ def _pead_on(d, i, types, min_inc=None):
         j += 1
     return False
 
+def _volratio(d, i):
+    """量比 = 当日量 / 前5日均量（基期不足或含0则返回0）。2026-09-18 第二轴细分批用。"""
+    v = d["v"]
+    base = v[max(0, i - 5):i]
+    if len(base) < 5 or any(x <= 0 for x in base):
+        return 0.0
+    mb = sum(base) / len(base)
+    return v[i] / mb if mb > 0 else 0.0
+
+
+def _nshape_retrace(d, E):
+    """N字回踩企稳（2026-09-19，金健米业走势研究）：E=B+3 日收盘企稳判定。
+    B=低位放量首板（涨停+量比≥2.5+前60日无板）；B+1..E 收盘不破启动位 o[B]×0.97；
+    E 日缩量（v[E]<v[B]×0.8，参照案例金健 8/11 实测 0.76——公开标注校准）。只用 E 日及以前信息，可执行。
+    nshape_study.py 委托本函数，禁两处实现。"""
+    c, o, v = d["c"], d["o"], d["v"]
+    B = E - 3
+    if B < 61 or c[B] <= 0 or c[B - 1] <= 0:
+        return False
+    if c[B] / c[B - 1] - 1 < 0.098 or _volratio(d, B) < 2.5:
+        return False
+    for j in range(max(1, B - 60), B):
+        if c[j] > 0 and c[j - 1] > 0 and c[j] / c[j - 1] - 1 >= 0.098:
+            return False
+    if min(c[B + 1:E + 1]) < o[B] * 0.97:
+        return False
+    return v[E] < v[B] * 0.8
+
+
+def _macd_lines(d):
+    """DIF/DEA（12,26,9）逐日 EMA，按股票缓存（O(n) 一次），避免检测器里 O(n²)。"""
+    if "_macd" in d:
+        return d["_macd"]
+    c = d["c"]
+    e12 = e26 = None
+    dif = []
+    for x in c:
+        e12 = x if e12 is None else e12 + (x - e12) * 2 / 13
+        e26 = x if e26 is None else e26 + (x - e26) * 2 / 27
+        dif.append(e12 - e26)
+    dea, s = [], None
+    for x in dif:
+        s = x if s is None else s + (x - s) * 2 / 10
+        dea.append(s)
+    d["_macd"] = (dif, dea)
+    return d["_macd"]
+
+
+def _gold_ma5_20(d, i):
+    """MA5 上穿 MA20（当日金叉）"""
+    c = d["c"]
+    if i < 26 or c[i - 20] <= 0:
+        return False
+    m5 = sum(c[i - 4:i + 1]) / 5
+    m20 = sum(c[i - 19:i + 1]) / 20
+    p5 = sum(c[i - 5:i]) / 5
+    p20 = sum(c[i - 20:i]) / 20
+    return m5 > m20 and p5 <= p20
+
+
+def _gold_macd(d, i):
+    """MACD 金叉（DIF 上穿 DEA）"""
+    if i < 35:
+        return False
+    dif, dea = _macd_lines(d)
+    return dif[i] > dea[i] and dif[i - 1] <= dea[i - 1]
+
+
+def _ma(d, i, w):
+    c = d["c"]
+    return sum(c[i-w+1:i+1])/w if i >= w-1 else None
+
+
+def _turtle20(d, i):
+    """20日新高突破（海龟短）"""
+    if i < 21:
+        return False
+    return d["c"][i] > max(d["h"][i-20:i])
+
+
+def _turtle55(d, i):
+    """55日新高突破（海龟长）"""
+    if i < 56:
+        return False
+    return d["c"][i] > max(d["h"][i-55:i])
+
+
+def _ma20_cross(d, i):
+    """收盘上穿 MA20（价格穿越均线）"""
+    m, p = _ma(d, i, 20), _ma(d, i-1, 20)
+    if m is None or p is None:
+        return False
+    return d["c"][i] > m and d["c"][i-1] <= p
+
+
+def _three_down(d, i):
+    """三连阴（收盘<开盘）"""
+    if i < 3:
+        return False
+    c, o = d["c"], d["o"]
+    return all(c[j] < o[j] for j in (i, i-1, i-2))
+
+
+def _squeeze_breakout(d, i):
+    """缩量横盘放量突破（再升型）：近10日振幅<8% + 当日量比>2 + 涨幅>2%"""
+    if i < 15:
+        return False
+    h, l, c, v = d["h"], d["l"], d["c"], d["v"]
+    hi, lo = max(h[i-10:i]), min(l[i-10:i])
+    if lo <= 0 or (hi/lo - 1) > 0.08 or c[i-1] <= 0:
+        return False
+    base = v[i-5:i]
+    if len(base) < 5 or any(x <= 0 for x in base):
+        return False
+    return v[i]/(sum(base)/5) > 2 and c[i]/c[i-1] - 1 > 0.02
+
+
+def _chan_bottom(d, i):
+    """简化缠论底分型：i-1 为局部最低 + 当日收阳 + 缩量"""
+    if i < 6:
+        return False
+    l, c, o, v = d["l"], d["c"], d["o"], d["v"]
+    if not (l[i-1] < l[i-2] and l[i-1] < l[i]):
+        return False
+    if c[i] <= o[i]:
+        return False
+    base = v[i-5:i]
+    if len(base) < 5 or any(x <= 0 for x in base):
+        return False
+    return v[i]/(sum(base)/5) < 1.0
+
+
+def _limitup_close(d, i):
+    """涨停收盘（打板口径）"""
+    return i >= 1 and d["c"][i-1] > 0 and d["c"][i]/d["c"][i-1] - 1 >= 0.098
+
+
+def _two_boards(d, i):
+    """二连板"""
+    if i < 2 or d["c"][i-2] <= 0 or d["c"][i-1] <= 0:
+        return False
+    return d["c"][i]/d["c"][i-1] - 1 >= 0.098 and d["c"][i-1]/d["c"][i-2] - 1 >= 0.098
+
+
+def _oversold20_60d(d, i):
+    """60日内超跌≥20%（相对区间最高收盘）"""
+    if i < 60:
+        return False
+    hi = max(d["h"][i-60:i+1])
+    return hi > 0 and d["c"][i]/hi - 1 <= -0.20
+
+
+def _touch_not_seal(d, i):
+    """触板未封（当日最高触涨停但收盘未封）"""
+    if i < 1 or d["c"][i-1] <= 0:
+        return False
+    limit = d["c"][i-1]*1.098
+    return d["h"][i] >= limit*0.995 and d["c"][i] < limit
+
+
+def _gap_down(d, i):
+    """低开缺口≥3%"""
+    if i < 1 or d["c"][i-1] <= 0:
+        return False
+    return d["o"][i]/d["c"][i-1] - 1 <= -0.03
+
+
 REGISTRY = {
     "TD9买入": _td9buy,
     "TD9卖出": _td9sell,
@@ -608,9 +971,158 @@ REGISTRY = {
     "PEAD_预增50+": lambda d, i: _pead_on(d, i, {"预增"}, 50),
     "PEAD_强利好": lambda d, i: _pead_on(d, i, {"预增", "扭亏"}),
     "PEAD_强利空": lambda d, i: _pead_on(d, i, {"预减", "首亏"}),
+    # ---- 2026-09-18：跌停接按 MA60 位置拆分（8年网格实测：MA60下 +1.94%/59.9% vs MA60上 -0.12%/44.7%）----
+    "跌停接_MA60下": lambda d, i: (d["ma60"][i] is not None and d["c"][i] <= d["ma60"][i]
+                                and _limitdown(d, i)),
+    "跌停接_MA60上": lambda d, i: (d["ma60"][i] is not None and d["c"][i] > d["ma60"][i]
+                                and _limitdown(d, i)),
+    # ---- 2026-09-18 第二轴细分批：位置方向假设（接跌要低位 / 追强要高位）----
+    # 依据 tmp/second_axis_grid.py：B5 半路板 MA60上 +1.55% vs 下 +0.20%（方向与接跌类相反）；
+    # 恐慌深度加量比档（缩量<0.8 最优）；frontrun 的"次日追"腿在低位子集转正。
+    "跌停接_MA60下_缩量": lambda d, i: (d["ma60"][i] is not None and d["c"][i] <= d["ma60"][i]
+                                  and _volratio(d, i) < 0.8 and _limitdown(d, i)),
+    # ---- 2026-09-18 用户点名：金叉类从未测过，补两个基础金叉检测器 ----
+    "金叉_MA5上穿20": _gold_ma5_20,
+    "金叉_MACD": _gold_macd,
+    # ---- 2026-09-18 穷尽批：把历史上测过的经典玩法全部做成检测器（原联赛/临时脚本口径）----
+    "海龟20突破": _turtle20,
+    "海龟55突破": _turtle55,
+    "MA20上穿": _ma20_cross,
+    "三连阴": _three_down,
+    "缩量横盘放量突破": _squeeze_breakout,
+    "缠论底分型": _chan_bottom,
+    "涨停收盘打板": _limitup_close,
+    "二连板": _two_boards,
+    "超跌20_60日": _oversold20_60d,
+    "触板未封": _touch_not_seal,
+    "缺口低开3%": _gap_down,
+    # ---- 2026-09-18 组合批（用户要求：多种组合跑 submit 六闸门）----
+    # 底座 = 跌停×MA60下（=LIMITDOWN_LOW_MA60）；括号内是交集 n（8年）
+    "组合_跌停低_长周期输家": lambda d, i: (d["ma60"][i] is not None and d["c"][i] <= d["ma60"][i]
+                                     and _limitdown(d, i) and _loser250(d, i)),            # 3022
+    "组合_跌停低_长周期_超跌20": lambda d, i: (d["ma60"][i] is not None and d["c"][i] <= d["ma60"][i]
+                                      and _limitdown(d, i) and _loser250(d, i)
+                                      and _oversold20_60d(d, i)),                            # 2569
+    "组合_跌停低_三连阴": lambda d, i: (d["ma60"][i] is not None and d["c"][i] <= d["ma60"][i]
+                                   and _limitdown(d, i) and _three_down(d, i)),              # 4191
+    "组合_跌停低_缺口低开": lambda d, i: (d["ma60"][i] is not None and d["c"][i] <= d["ma60"][i]
+                                    and _limitdown(d, i) and _gap_down(d, i)),               # 7398
+    "组合_跌停低_TD9卖出": lambda d, i: (d["ma60"][i] is not None and d["c"][i] <= d["ma60"][i]
+                                   and _limitdown(d, i) and _td9sell(d, i)),                 # 44
+    "组合_跌停低_金叉MA5": lambda d, i: (d["ma60"][i] is not None and d["c"][i] <= d["ma60"][i]
+                                   and _limitdown(d, i) and _gold_ma5_20(d, i)),             # 86
+    "组合_跌停低_避雷针低位": lambda d, i: (d["ma60"][i] is not None and d["c"][i] <= d["ma60"][i]
+                                     and _limitdown(d, i) and _bigupper(d, i)),              # 953
+    "组合_跌停低_大长腿低位": lambda d, i: (d["ma60"][i] is not None and d["c"][i] <= d["ma60"][i]
+                                     and _limitdown(d, i) and _biglower(d, i)),
+    "组合_反转x避雷针低位": lambda d, i: (d["ma60"][i] is not None and d["c"][i] <= d["ma60"][i]
+                                   and _reversal(d, i) and _bigupper(d, i)),
+    "组合_反转x大长腿低位": lambda d, i: (d["ma60"][i] is not None and d["c"][i] <= d["ma60"][i]
+                                   and _reversal(d, i) and _biglower(d, i)),
+    "组合_缺口低开_低位阳线": lambda d, i: (d["ma60"][i] is not None and d["c"][i] <= d["ma60"][i]
+                                     and d["c"][i] > d["o"][i] and _gap_down(d, i)),
+    "组合_触板未封_低位": lambda d, i: (d["ma60"][i] is not None and d["c"][i] <= d["ma60"][i]
+                                   and _touch_not_seal(d, i)),
+    "banlu_b5_MA60上": lambda d, i: (d["ma60"][i] is not None and d["c"][i] > d["ma60"][i]
+                                 and _banlu_b5(d, i)),
+    "banlu_b5_MA60下": lambda d, i: (d["ma60"][i] is not None and d["c"][i] <= d["ma60"][i]
+                                 and _banlu_b5(d, i)),
+    "frontrun_v2_低位追": lambda d, i: (d["ma60"][i] is not None and d["c"][i] <= d["ma60"][i]
+                                   and _frontrun_v2(d, i)),
     # ---- 双高格唯一存活（2026-09-14 #79）：跌停接×MA60上×2月，节令格终审 ----
     "跌停接_MA60上_2月": lambda d, i: (d["ma60"][i] is not None and d["c"][i] > d["ma60"][i]
                                      and d["date"][i][5:7] == "02" and _limitdown(d, i)),
+    # ---- 妖股晋级段（2026-09-14 #77b）：缩量涨停=筹码锁定，晋级率1.7x放量板 ----
+    "缩量涨停_晋级": _shrink_board,
+    "放量涨停_对照": _vol_board,
+    # ---- 2026-09-18 基本面画像批（fundamental_commonality 结论的消融验证）----
+    # 画像发现：跌停接命中组换手率=对照3.5倍、市值=对照0.7倍。画像是描述不是edge，
+    # 是否与既有「缩量<0.8最优」（第二轴细分批）矛盾，由闸门裁决——两个方向都注册。
+    "跌停接_MA60下_放量": lambda d, i: (d["ma60"][i] is not None and d["c"][i] <= d["ma60"][i]
+                                  and _volratio(d, i) >= 1.5 and _limitdown(d, i)),
+    "跌停接_MA60下_小市值": lambda d, i: (d["ma60"][i] is not None and d["c"][i] <= d["ma60"][i]
+                                    and (cap_at_date(_XCAP, d["code"], d["date"][i]) or 1e9) < 40
+                                    and _limitdown(d, i)),
+    # ---- 2026-09-18 夜间批：confluence 组合（只用存活组件 + 财报健康过滤器）----
+    # 依据：白天画像/闸门裁决（缩量 PASS、放量/小市值 REJECT）+ Kimi 对账（命中票 7/20 亏损、2 ST）。
+    # 「比赛死了的票不进策略」——组件全部来自存活清单，死信号（金叉/缠论/TD9/海龟等）不做组件。
+    "组合_跌停低_缩量_剔亏ST": lambda d, i: (d["ma60"][i] is not None and d["c"][i] <= d["ma60"][i]
+                                       and _volratio(d, i) < 0.8 and _limitdown(d, i)
+                                       and _fund_healthy(d, i)),
+    "组合_跌停低_输家_超跌20_缩量": lambda d, i: (d["ma60"][i] is not None and d["c"][i] <= d["ma60"][i]
+                                            and _limitdown(d, i) and _loser250(d, i)
+                                            and _oversold20_60d(d, i) and _volratio(d, i) < 0.8),
+    "组合_跌停低_三连阴_缩量": lambda d, i: (d["ma60"][i] is not None and d["c"][i] <= d["ma60"][i]
+                                       and _limitdown(d, i) and _three_down(d, i)
+                                       and _volratio(d, i) < 0.8),
+    "组合_跌停低_避雷针_缩量": lambda d, i: (d["ma60"][i] is not None and d["c"][i] <= d["ma60"][i]
+                                       and _limitdown(d, i) and _bigupper(d, i)
+                                       and _volratio(d, i) < 0.8),
+    "组合_跌停低_输家_超跌20_剔亏ST": lambda d, i: (d["ma60"][i] is not None and d["c"][i] <= d["ma60"][i]
+                                              and _limitdown(d, i) and _loser250(d, i)
+                                              and _oversold20_60d(d, i) and _fund_healthy(d, i)),
+    "组合_缺口低开_低位_剔亏ST": lambda d, i: (d["ma60"][i] is not None and d["c"][i] <= d["ma60"][i]
+                                         and d["c"][i] > d["o"][i] and _gap_down(d, i)
+                                         and _fund_healthy(d, i)),
+    # ---- 2026-09-18 深夜：死信号复活赛道（用户裁决：死信号可当过滤器，交互价值另算）----
+    # 方法论：standalone 无 edge ≠ 条件组合无贡献（交互项）。全部挂跌停×MA60下底座，
+    # 由 submit 闸门的位置匹配边际裁决「加了它底座变好还是变坏」。
+    # 注意多重比较风险：复活赛道批量测，Harvey t_NW≥3.0 + G7 是底线，一律不许放宽。
+    "组合_跌停低_金叉MACD滤": lambda d, i: (d["ma60"][i] is not None and d["c"][i] <= d["ma60"][i]
+                                      and _limitdown(d, i) and _gold_macd(d, i)),
+    "组合_跌停低_缠论底滤": lambda d, i: (d["ma60"][i] is not None and d["c"][i] <= d["ma60"][i]
+                                    and _limitdown(d, i) and _chan_bottom(d, i)),
+    "组合_跌停低_TD9买入滤": lambda d, i: (d["ma60"][i] is not None and d["c"][i] <= d["ma60"][i]
+                                     and _limitdown(d, i) and _td9buy(d, i)),
+    "组合_跌停低_MA20上穿滤": lambda d, i: (d["ma60"][i] is not None and d["c"][i] <= d["ma60"][i]
+                                      and _limitdown(d, i) and _ma20_cross(d, i)),
+    "组合_跌停低_海龟20滤": lambda d, i: (d["ma60"][i] is not None and d["c"][i] <= d["ma60"][i]
+                                    and _limitdown(d, i) and _turtle20(d, i)),
+    # ---- 2026-09-19：复活胜者 TD9买入滤 的三滤叠加延伸 ----
+    "组合_跌停低_缩量_TD9滤": lambda d, i: (d["ma60"][i] is not None and d["c"][i] <= d["ma60"][i]
+                                      and _limitdown(d, i) and _volratio(d, i) < 0.8
+                                      and _td9buy(d, i)),
+    "组合_跌停低_输家_超跌20_TD9滤": lambda d, i: (d["ma60"][i] is not None and d["c"][i] <= d["ma60"][i]
+                                             and _limitdown(d, i) and _loser250(d, i)
+                                             and _oversold20_60d(d, i) and _td9buy(d, i)),
+    # ---- 2026-09-19 N字回踩企稳（金健米业走势研究）：低位放量首板后第3日缩量不破企稳 ----
+    # 事件研究：二波启动日进=全负（12格）；回踩期进=全转正（+0.2~+0.96%）。控制对照与闸门裁决为准。
+    "N字回踩企稳": _nshape_retrace,
+    # ---- 2026-09-19 胜负解剖细分（winloss_autopsy 发现：深度/恐慌强度是胜负的真正分界）----
+    # 深=距MA60≤-25%（89.7%/+13.71 vs 浅 60%/+2.14）；跌停潮=当日全市场跌停≥100（81.5%/+9.42 vs 零星46%/-0.21）
+    "组合_跌停低_深跌": lambda d, i: (d["ma60"][i] is not None and d["ma60"][i] > 0
+                                and d["c"][i] <= d["ma60"][i] * 0.75
+                                and _limitdown(d, i)),
+    "组合_跌停低_深跌_跌停潮": lambda d, i: (d["ma60"][i] is not None and d["ma60"][i] > 0
+                                       and d["c"][i] <= d["ma60"][i] * 0.75
+                                       and _limitdown(d, i)
+                                       and _XLDC.get(d["date"][i], 0) >= 100),
+    "组合_跌停低_三连阴_深跌": lambda d, i: (d["ma60"][i] is not None and d["ma60"][i] > 0
+                                       and d["c"][i] <= d["ma60"][i] * 0.75
+                                       and _limitdown(d, i) and _three_down(d, i)),
+    # ---- 2026-09-19 全交叉矩阵幸存对（cross_matrix.py 两阶段漏斗：45对→9幸存→8 PASS）----
+    # 消融纪律：每对都验证了「优于两个单件各自」（真交互），非单边驱动。
+    "交叉_跌停低_缩量_避雷针低": lambda d, i: (d["ma60"][i] is not None and d["c"][i] <= d["ma60"][i]
+                                         and _limitdown(d, i) and _volratio(d, i) < 0.8
+                                         and _bigupper(d, i)),
+    "交叉_跌停低_缩量_剔亏ST": lambda d, i: (d["ma60"][i] is not None and d["c"][i] <= d["ma60"][i]
+                                       and _limitdown(d, i) and _volratio(d, i) < 0.8
+                                       and _fund_healthy(d, i)),
+    "交叉_跌停低_缩量_缺口低开": lambda d, i: (d["ma60"][i] is not None and d["c"][i] <= d["ma60"][i]
+                                         and _limitdown(d, i) and _volratio(d, i) < 0.8
+                                         and _gap_down(d, i)),
+    "交叉_跌停低_三连阴_输家250": lambda d, i: (d["ma60"][i] is not None and d["c"][i] <= d["ma60"][i]
+                                          and _limitdown(d, i) and _three_down(d, i)
+                                          and _loser250(d, i)),
+    "交叉_跌停低_三连阴_超跌20": lambda d, i: (d["ma60"][i] is not None and d["c"][i] <= d["ma60"][i]
+                                         and _limitdown(d, i) and _three_down(d, i)
+                                         and _oversold20_60d(d, i)),
+    "交叉_跌停低_输家250_避雷针低": lambda d, i: (d["ma60"][i] is not None and d["c"][i] <= d["ma60"][i]
+                                           and _limitdown(d, i) and _loser250(d, i)
+                                           and _bigupper(d, i)),
+    "交叉_跌停低_TD9买入_缺口低开": lambda d, i: (d["ma60"][i] is not None and d["c"][i] <= d["ma60"][i]
+                                           and _limitdown(d, i) and _td9buy(d, i)
+                                           and _gap_down(d, i)),
 }
 
 

===== engine/fjcore.py =====
#!/usr/bin/env python3
"""fjcore.py — 焚诀门面层（2026-09-19 架构收编，用户令「不要代码堆叠」）。

新模块的唯一入口。禁止再直接 import law_pipeline 读全局、禁止再各自重写 fwd/stat。
law_pipeline 仍是底层引擎（不动它，绞杀者模式：新代码全走这里，旧模块逐步迁移）。

用法：
    from fjcore import Universe, forward, stats, EXIT_RULES
    u = Universe()                    # 全宇宙+横截面，一次加载全局缓存
    r = forward(u.stocks[code], i, 5) # 统一前向收益（次日开盘买/净口径/剔一字）
    m = stats(returns)                # 统一指标（n/胜率/均值/赔率/中位）
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import law_pipeline as lp

FEE = 0.0015
HORIZONS = (1, 2, 3, 5, 10, 20)


class Universe:
    """全市场宇宙 + 横截面 globals，进程内单例。"""

    _inst = None

    def __new__(cls):
        if cls._inst is None:
            cls._inst = super().__new__(cls)
            cls._inst._ready = False
        return cls._inst

    def load(self):
        if self._ready:
            return self
        self.stocks = lp.load_universe()
        lp.build_xsection(self.stocks)
        self.regime = lp.load_regime()
        self.cap, self.cap_qs = lp.load_cap_quintiles()
        self.fund = lp._XFUND          # code -> date -> (peTTM, isST)
        self.ldc = lp._XLDC            # date -> 当日全市场跌停数
        self._ready = True
        return self

    def cap_at(self, code, date):
        return lp.cap_at_date(self.cap, code, date)

    def fund_at(self, code, date):
        return (self.fund or {}).get(code, {}).get(date)


def forward(d, i, h, fee=FEE):
    """统一前向收益：信号日 i 收盘确认 → 次日开盘买 → 入场+h 日收盘卖（净口径）。
    开盘一字跌停（买不进）返回 None。"""
    ei = i + 1
    if ei >= d["n"] or ei + h >= d["n"] or d["o"][ei] <= 0:
        return None
    if d["o"][ei] <= d["c"][i] * 0.905:
        return None
    return d["c"][ei + h] / d["o"][ei] - 1 - fee


def stats(rs):
    """统一指标包：n / win% / mean% / med% / 赔率 / t。rs 为收益率（小数）。"""
    rs = [r for r in rs if r is not None]
    if not rs:
        return None
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    n = len(rs)
    mean = sum(rs) / n
    sd = (sum((x - mean) ** 2 for x in rs) / n) ** 0.5 or 1e-12
    odds = (sum(wins) / len(wins)) / abs(sum(losses) / len(losses)) if wins and losses else None
    srt = sorted(rs)
    return {"n": n, "win%": round(100 * len(wins) / n, 1), "mean%": round(100 * mean, 2),
            "med%": round(100 * srt[n // 2], 2), "赔率": round(odds, 2) if odds else None,
            "t": round(mean / sd * n ** 0.5, 1)}


def full_curve(rs_by_h):
    """汇报纪律（用户钦定）：全 horizon 曲线一行。"""
    return " | ".join(
        f"T+{h} {s['win%']}%/{s['mean%']}%/赔{s['赔率']}"
        for h, s in rs_by_h.items() if s)


# 出口规则库的唯一登记处（exit_rule_grid.py 的实现为准，引用不复制）
EXIT_RULES = ("fixed_1", "fixed_2", "fixed_3", "fixed_5", "fixed_8", "fixed_13", "fixed_21",
              "tp4_s3", "tp6_s3", "tp8_s5", "tp10_s5", "trail_5", "trail_8", "ma60_out",
              "tp6s3_ma60")

# 闸门/容量/选票的直通（薄封装，签名即文档）
submit_gate = lp.submit_gate
capacity_sim = lp.capacity_sim
collect_sigs = lp._collect_sigs
REGISTRY = lp.REGISTRY

===== engine/cross_matrix.py =====
#!/usr/bin/env python3
"""cross_matrix.py — 存活组件系统化全交叉 + 消融（2026-09-19 用户批评「交叉没测完」立项）。

设计（BRAIN 式漏斗）：
  Stage 1 便宜筛：底座=跌停×MA60下。单次遍历全宇宙，底座事件上算组件位向量，
    所有 C(10,2) 配对一次成型。每对四档消融：base / base+A / base+B / base+A+B。
    指标：n / T+5 胜率/均值/赔率 / 位置匹配对照边际（同票同 MA60 下随机日等量采样）。
    幸存线：n≥200 且 A+B 边际>0 且 A+B 优于两单件（真交互而非单边驱动）。
  Stage 2 硬闸门：幸存对自动走 law_pipeline.submit_gate 全六闸+G7。
组件（全部存活/有实证者；死信号与物理互斥者不进组件库）：
  缩量、三连阴、250日输家、超跌20、避雷针低位、TD9买入、剔亏ST、缺口低开、触板未封、反转族
"""
import json
import random
import sys
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import law_pipeline as lp

ROOT = Path(__file__).resolve().parent.parent
FEE = 0.0015
HORIZONS = (1, 2, 3, 5, 10, 20)   # 2026-09-19 用户批评「又是T+5」→ 全 horizon

COMP = {   # 组件名 -> lp 检测函数（(d,i)->bool）
    "缩量": lambda d, i: lp._volratio(d, i) < 0.8,
    "三连阴": lp._three_down,
    "输家250": lp._loser250,
    "超跌20": lp._oversold20_60d,
    "避雷针低": lp._bigupper,
    "TD9买入": lp._td9buy,
    "剔亏ST": lp._fund_healthy,
    "缺口低开": lp._gap_down,
    "触板未封": lp._touch_not_seal,
    "反转族": lp._reversal,
}
NAMES = list(COMP)


def fwd(d, i, h):
    ei = i + 1
    if ei >= d["n"] or ei + h >= d["n"] or d["o"][ei] <= 0:
        return None
    if d["o"][ei] <= d["c"][i] * 0.905:
        return None
    return d["c"][ei + h] / d["o"][ei] - 1 - FEE


def stat(rs):
    rs = [r for r in rs if r is not None]
    if not rs:
        return None
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    odds = (sum(wins) / len(wins)) / abs(sum(losses) / len(losses)) if wins and losses else None
    return {"n": len(rs), "win%": round(100 * len(wins) / len(rs), 1),
            "mean%": round(100 * sum(rs) / len(rs), 2), "赔率": round(odds, 2) if odds else None}


def main():
    stocks = lp.load_universe()
    lp.build_xsection(stocks)

    # 单遍收集：底座事件的组件位向量 + 对照池（同票 MA60下 非底座日）
    events = []          # (code, i, bitmask)
    ctrl_pool = []       # (code, i) MA60下非底座日
    for code, d in stocks.items():
        c, ma, n = d["c"], d["ma60"], d["n"]
        for i in range(61, n - 22):
            if ma[i] is None or c[i] <= 0 or c[i - 1] <= 0:
                continue
            below = c[i] <= ma[i]
            if not below:
                continue
            is_base = c[i] / c[i - 1] - 1 <= -0.095 and d["o"][i + 1] > c[i] * 0.905
            if is_base:
                mask = 0
                for k, nm in enumerate(NAMES):
                    try:
                        if COMP[nm](d, i):
                            mask |= 1 << k
                    except Exception:
                        pass
                events.append((code, i, mask))
            else:
                ctrl_pool.append((code, i))
    print(f"底座事件 {len(events)}，对照池 {len(ctrl_pool)}", flush=True)

    def evalset(idxs):
        return {h: stat([fwd(stocks[c], i, h) for c, i in idxs]) for h in HORIZONS}

    rng = random.Random(2026)
    # 底座基线 + 对照边际基线（全 horizon）
    base_all = [(c, i) for c, i, _ in events]
    baseH = evalset(base_all)
    ctrl_s = rng.sample(ctrl_pool, min(len(base_all), len(ctrl_pool)))
    ctrlH = evalset(ctrl_s)
    base_marg = {h: round(baseH[h]["mean%"] - ctrlH[h]["mean%"], 2) for h in HORIZONS}
    print("底座全horizon:", " ".join(
        f"T+{h} {baseH[h]['win%']}%/{baseH[h]['mean%']}%/赔{baseH[h]['赔率']}/边{base_marg[h]}" for h in HORIZONS), flush=True)

    out = {"底座": {"curve": baseH, "边际": base_marg, "对照curve": ctrlH}, "pairs": {}}

    singles = {}
    for k, nm in enumerate(NAMES):
        idxs = [(c, i) for c, i, m in events if m & (1 << k)]
        singles[nm] = {"curve": evalset(idxs), "idxs_len": len(idxs)}
        s5 = singles[nm]["curve"][5]
        print(f"  单件 {nm}: n={len(idxs)} T+5 {s5 and s5['win%']}%/{s5 and s5['mean%']}%", flush=True)
    out["singles"] = {k: {"curve": v["curve"]} for k, v in singles.items()}

    survivors = []
    for a, b in combinations(range(len(NAMES)), 2):
        na, nb = NAMES[a], NAMES[b]
        idxs = [(c, i) for c, i, m in events if (m & (1 << a)) and (m & (1 << b))]
        if len(idxs) < 200:
            continue
        pH = evalset(idxs)
        # 对照：同位置随机日（从对照池按事件数采样）
        cs = rng.sample(ctrl_pool, min(len(idxs), len(ctrl_pool)))
        ccH = evalset(cs)
        marg = {h: round(pH[h]["mean%"] - ccH[h]["mean%"], 2) for h in HORIZONS}
        p5 = pH[5]
        sa, sb = singles[na]["curve"][5], singles[nb]["curve"][5]
        beats_both = (sa is None or p5["mean%"] > sa["mean%"]) and (sb is None or p5["mean%"] > sb["mean%"])
        rec = {"n": len(idxs), "curve": pH, "边际": marg, "对照curve": ccH, "优于两单件": beats_both}
        out["pairs"][f"{na}×{nb}"] = rec
        flag = "✅" if (marg[5] > 0 and beats_both) else ""
        print(f"  {na}×{nb}: n={len(idxs)} T+5 {p5['win%']}%/{p5['mean%']}% 边T1 {marg[1]}/T5 {marg[5]}/T20 {marg[20]} {flag}", flush=True)
        if marg[5] > 0 and beats_both and p5["win%"] >= 55:
            survivors.append((na, nb))
    out["幸存待submit"] = survivors
    (ROOT / "data/cross_matrix_20260919.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("幸存对:", survivors, flush=True)
    print("saved stage1", flush=True)

    # Stage 2：幸存对注册临时检测器走 submit 全闸门
    if survivors:
        regime = lp.load_regime()
        stock_cap, qs = lp.load_cap_quintiles()
        for na, nb in survivors:
            name = f"交叉_跌停低_{na}_{nb}"
            lp.REGISTRY[name] = (lambda fa, fb: lambda d, i: (
                d["ma60"][i] is not None and d["c"][i] <= d["ma60"][i]
                and lp._limitdown(d, i) and fa(d, i) and fb(d, i)))(COMP[na], COMP[nb])
            passed, v = lp.submit_gate(name, lp.REGISTRY[name], stocks, regime, stock_cap, qs)
            print(f"SUBMIT {name}: {'PASS' if passed else 'REJECT'}", flush=True)
            print(json.dumps(v, ensure_ascii=False)[:400], flush=True)


if __name__ == "__main__":
    main()

===== engine/pick_ranker.py =====
#!/usr/bin/env python3
"""pick_ranker.py — 恐慌成簇日选票排名器（2026-09-19 用户令：研究要能用来选票）。

问题：成簇日一堆票命中，买哪只次日涨得更多？
方法：
  1. 每日命中集合内按单特征排序，头名 vs 当日等权均值（选股超额）+ 秩相关 IC
  2. 合成评分（深度+超跌+连跌+小市值+缩量 z 分和）排名
  3. 容量模拟实证：槽位按排名从上往下吃 vs 随机吃（capacity_sim 的选票规则替换）
PIT 纪律：排名特征全部信号日收盘可知（次日缺口不进特征）。
"""
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import law_pipeline as lp

ROOT = Path(__file__).resolve().parent.parent
FEE = 0.0015
BASE = "跌停接_MA60下"


def feats(d, i, code, fund, capm):
    c, o, v, ma = d["c"], d["o"], d["v"], d["ma60"]
    hi60 = max(c[max(0, i - 60):i + 1])
    n_down = 0
    j = i
    while j > 0 and c[j] < c[j - 1]:
        n_down += 1
        j -= 1
    fu = fund.get(code, {}).get(d["date"][i])
    return {
        "深度": -(c[i] / ma[i] - 1),          # 越深越好（取负后越大越好）
        "超跌60": -(c[i] / hi60 - 1) if hi60 > 0 else 0,
        "连跌": n_down,
        "小市值": -(lp.cap_at_date(capm, code, d["date"][i]) or 1e9),  # 越小越好（PIT 日频）
        "缩量": -lp._volratio(d, i),           # 越缩越好
        "低PE": -(fu[0]) if fu and fu[0] is not None else 0,
    }


def fwd(d, i, h):
    ei = i + 1
    if ei + h >= d["n"] or d["o"][ei] <= 0 or d["o"][ei] <= d["c"][i] * 0.905:
        return None
    return d["c"][ei + h] / d["o"][ei] - 1 - FEE


def main():
    stocks = lp.load_universe()
    lp.build_xsection(stocks)
    fund, capm = lp._XFUND, lp._XCAP

    det = lp.REGISTRY[BASE]
    days = defaultdict(list)   # date -> [(code, i, feats)]
    for code, d in stocks.items():
        for i in range(61, d["n"] - 22):
            try:
                if det(d, i):
                    days[d["date"][i]].append((code, i, feats(d, i, code, fund, capm)))
            except Exception:
                pass
    cluster = {dt: evs for dt, evs in days.items() if len(evs) >= 3}
    print(f"成簇日 {len(cluster)}，事件总数 {sum(len(v) for v in cluster.values())}", flush=True)

    FEATS = ["深度", "超跌60", "连跌", "小市值", "缩量", "低PE"]
    # 1) 单特征头名超额 + IC
    for h, hname in ((1, "T+1"), (5, "T+5")):
        print(f"\n== {hname} 单特征排名效果（头名超额 vs 当日等权；IC=秩相关）==")
        for f in FEATS:
            top_excess, ics = [], []
            for dt, evs in cluster.items():
                scored = []
                for code, i, ft in evs:
                    r = fwd(stocks[code], i, h)
                    if r is not None:
                        scored.append((ft[f], r))
                if len(scored) < 3:
                    continue
                scored.sort(key=lambda x: -x[0])
                day_mean = sum(r for _, r in scored) / len(scored)
                top_excess.append(scored[0][1] - day_mean)
                # 秩相关（简化 Pearson on ranks）
                n = len(scored)
                rk_f = {k: rnk for rnk, (k, _) in enumerate(sorted(scored))}
                rk_r = {k: rnk for rnk, k in enumerate(sorted(r for _, r in scored))}
                mf = sum(rk_f.values()) / n
                mr = sum(rk_r.values()) / n
                cov = sum((rk_f[a] - mf) * (rk_r[b] - mr) for a, b in [(x[0], x[1]) for x in scored])
                vf = sum((rk_f[x[0]] - mf) ** 2 for x in scored)
                vr = sum((rk_r[x[1]] - mr) ** 2 for x in scored)
                if vf > 0 and vr > 0:
                    ics.append(cov / (vf * vr) ** 0.5)
            if top_excess:
                te = 100 * sum(top_excess) / len(top_excess)
                ic = sum(ics) / len(ics) if ics else 0
                print(f"  {f}: 头名超额 {te:+.2f}pp/日  IC {ic:+.3f}  (n日={len(top_excess)})", flush=True)

    # 2) 合成评分（z 分和：深度+超跌+连跌+小市值+缩量）
    print("\n== 合成评分（z 分和：深度/超跌/连跌/小市值/缩量）==")
    for h, hname in ((1, "T+1"), (5, "T+5")):
        top_excess = []
        for dt, evs in cluster.items():
            scored = []
            for f in FEATS[:5]:
                vs = [e[2][f] for e in evs]
                m = sum(vs) / len(vs)
                sd = (sum((x - m) ** 2 for x in vs) / len(vs)) ** 0.5 or 1
                for e in evs:
                    e[2][f"_z_{f}"] = (e[2][f] - m) / sd
            for code, i, ft in evs:
                r = fwd(stocks[code], i, h)
                if r is not None:
                    z = sum(ft[f"_z_{f}"] for f in FEATS[:5])
                    scored.append((z, r))
            if len(scored) < 3:
                continue
            scored.sort(key=lambda x: -x[0])
            day_mean = sum(r for _, r in scored) / len(scored)
            top_excess.append(scored[0][1] - day_mean)
        if top_excess:
            print(f"  {hname}: 合成头名超额 {100*sum(top_excess)/len(top_excess):+.2f}pp/日 (n日={len(top_excess)})", flush=True)


if __name__ == "__main__":
    main()

===== engine/explain_card.py =====
#!/usr/bin/env python3
"""explain_card.py — 归因引擎 v1（2026-09-19 用户纲领：系统要能解释股票为什么涨为什么跌）。

对每个恐慌接跌事件生成「归因卡」：谁在什么环境因为什么买/卖。
维度（全部信号日时点可知）：
  环境：regime、当日全市场跌停数（恐慌强度）、跌停数是否创10日新高（极值）
  位置：距MA60深度档（深<-25%/中/浅）、超跌深度、连跌天数
  筹码：量比档（恐慌放量/缩量衰竭）、次日缺口
  基本面：亏损与否、peTTM 档
  玩家（近1年龙虎榜）：当日上榜=机构净买/游资承接/无承接/未上榜
归因类 = 关键维度组合；输出各类的 T+5 胜率/均值/赔率 + 分年稳定性（理论历年适用性检验）。
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import law_pipeline as lp

ROOT = Path(__file__).resolve().parent.parent
FEE = 0.0015
HT = ROOT / "data/hithink"


def stat(rs):
    """输入已是百分数（r5*100），win%/赔率不受影响，mean% 不再乘 100（2026-09-19 双修正常露馅）。"""
    rs = [r for r in rs if r is not None]
    if not rs:
        return None
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    odds = (sum(wins) / len(wins)) / abs(sum(losses) / len(losses)) if wins and losses else None
    return {"n": len(rs), "win%": round(100 * len(wins) / len(rs), 1),
            "mean%": round(sum(rs) / len(rs), 2), "赔率": round(odds, 2) if odds else None}


def main():
    stocks = lp.load_universe()
    lp.build_xsection(stocks)
    regime = lp.load_regime()
    ldc = lp._XLDC
    fund = lp._XFUND
    capm = lp._XCAP

    # 龙虎榜（1 年深）：date -> {code: '机构净买'/'游资承接'/'无承接'}
    lhb = {}
    for ddir in sorted(HT.iterdir()):
        if not ddir.is_dir() or not ddir.name.startswith("202"):
            continue
        fo = ddir / "lhb_org.json"
        fh = ddir / "lhb_all.json"
        daymap = {}
        if fo.exists():
            for r in json.loads(fo.read_text())["data"].get("stock_items") or []:
                daymap[r["ticker"]] = "机构净买" if (r.get("org_net_value") or 0) > 0 else "无承接"
        if fh.exists():
            for r in json.loads(fh.read_text())["data"].get("stock_items") or []:
                if r["ticker"] not in daymap:
                    daymap[r["ticker"]] = "无承接" if (r.get("hot_money_net_value") or 0) <= 0 else "游资承接"
        lhb[ddir.name] = daymap

    det = lp.REGISTRY["组合_跌停低_三连阴"]
    rows = []
    for code, d in stocks.items():
        c, o, h, l, v, ma = d["c"], d["o"], d["h"], d["l"], d["v"], d["ma60"]
        tick = code + (".SH" if code.startswith("6") else ".SZ")
        for i in range(61, d["n"] - 7):
            try:
                if not det(d, i):
                    continue
            except Exception:
                continue
            ei = i + 1
            if o[ei] <= c[i] * 0.905:
                continue
            r5 = c[ei + 5] / o[ei] - 1 - FEE
            dt = d["date"][i]
            depth = (c[i] / ma[i] - 1) * 100
            rows.append({
                "code": code, "date": dt, "r5": round(r5 * 100, 2),
                "regime": regime.get(dt, "?"), "year": dt[:4],
                "恐慌强度": min(ldc.get(dt, 0) // 50 * 50, 200),   # 0/50/100/150/200+ 档
                "深度档": "深" if depth <= -25 else ("中" if depth <= -15 else "浅"),
                "量比档": "缩" if lp._volratio(d, i) < 0.8 else ("放" if lp._volratio(d, i) >= 1.5 else "平"),
                "玩家": lhb.get(dt, {}).get(tick, "未上榜" if dt >= "2025-09-08" else "无数据"),
            })
    print(f"事件 {len(rows)}，落盘归因卡", flush=True)

    # 归因类命中率矩阵：深度 × 恐慌强度
    print("\n== 归因矩阵：深度 × 恐慌强度（T+5 胜率/均值）==")
    cells = defaultdict(list)
    for r in rows:
        cells[(r["深度档"], r["恐慌强度"])].append(r["r5"])
    print(f"{'深度\\跌停数':<8}{'<50':>16}{'50-99':>16}{'100-149':>16}{'≥150':>16}")
    for dep in ("深", "中", "浅"):
        line = f"{dep:<8}"
        for ldc_bin in (0, 50, 100, 150):
            s = stat(cells.get((dep, ldc_bin), []))
            line += f"{s['win%']}%/{s['mean%']}%(n{s['n']}) ".rjust(16) if s else "-".rjust(16)
        print(line)

    # 量比档 × 深度
    print("\n== 量比档 × 深度 ==")
    cells2 = defaultdict(list)
    for r in rows:
        cells2[(r["量比档"], r["深度档"])].append(r["r5"])
    for vr in ("缩", "平", "放"):
        line = f"{vr:<8}"
        for dep in ("深", "中", "浅"):
            s = stat(cells2.get((vr, dep), []))
            line += f"{dep}:{s['win%']}%/{s['mean%']}%(n{s['n']})  " if s else f"{dep}:-  "
        print(line)

    # 玩家（近1年）
    print("\n== 玩家归因（2025-09 起龙虎榜期） ==")
    cells3 = defaultdict(list)
    for r in rows:
        if r["玩家"] != "无数据":
            cells3[r["玩家"]].append(r["r5"])
    for k, v in cells3.items():
        print(f"  {k}: {stat(v)}")

    # 历年适用性：深度×恐慌极值的旗舰类 分年
    print("\n== 旗舰归因类「深+恐慌≥100」分年胜率（理论历年适用性）==")
    for y in sorted({r["year"] for r in rows}):
        sub = [r["r5"] for r in rows if r["year"] == y and r["深度档"] == "深" and r["恐慌强度"] >= 100]
        print(f"  {y}: {stat(sub)}")

    (ROOT / "data/explain_card_20260919.json").write_text(json.dumps(rows, ensure_ascii=False))
    print("\nsaved data/explain_card_20260919.json")


if __name__ == "__main__":
    main()

===== engine/intraday_panic_grid.py =====
#!/usr/bin/env python3
"""intraday_panic_grid.py — 恐慌组合的盘中择时网格（2026-09-19 用户问 10:30后/尾盘买卖）。

复用 exec_timing_m60 的 m60 装载。事件=lp REGISTRY 恐慌系信号（日线判定），
盘中价格=m60 四根 bar（10:30/11:30/14:00/15:00 收盘 + 9:30 开盘）。
A. 入场时点网格：T+1 日 9:30开/10:30/11:30/14:00/15:00（尾盘）买 → T+5 收盘卖
B. 离场时点网格：T+1 开盘买 → 离场日 9:30/10:30/11:30/14:00/15:00 卖
窗口：2024-08-26→（m60 仅 2 年深，近期偏重，结论标注口径）
"""
import glob
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import law_pipeline as lp
from exec_timing_m60 import load_m60, nw_t

ROOT = Path(__file__).resolve().parent.parent
M60 = ROOT / "data/m60_cache"
FEE = 0.0015
WIN0 = "2024-08-26"
SIGS = ["跌停接_MA60下", "组合_跌停低_三连阴", "组合_跌停低_长周期_超跌20"]
SLOTS = [("9:30开", None), ("10:30", 0), ("11:30", 1), ("14:00", 2), ("15:00尾盘", 3)]


def slot_price(bars, slot):
    return bars[0]["open"] if slot is None else bars[slot]["close"]


def main():
    stocks = lp.load_universe()
    lp.build_xsection(stocks)
    m60_files = {Path(f).stem: f for f in glob.glob(str(M60 / "*.json"))}
    rng = random.Random(7)

    for name in SIGS:
        det = lp.REGISTRY[name]
        entry_grid = {s[0]: [] for s in SLOTS}
        exit_grid = {s[0]: [] for s in SLOTS}
        skipped = 0
        for code, d in stocks.items():
            if code not in m60_files:
                continue
            m6 = None
            # ex-div 哨兵（对齐 exec_timing_m60：m60 不复权 vs kcache 前复权，比值漂移>1.5% 的日期标记）
            ks_dates = d["date"]
            kc_close = d["c"]
            ratio, flagged, prev = {}, set(), None
            _m6_tmp = None
            for i2, dt2 in enumerate(ks_dates):
                if _m6_tmp is None and code in m60_files:
                    _m6_tmp = load_m60(m60_files[code])
                if _m6_tmp and dt2 in _m6_tmp and _m6_tmp[dt2] and kc_close[i2] > 0:
                    ratio[dt2] = _m6_tmp[dt2][-1]["close"] / kc_close[i2]
            for dt2 in ks_dates:
                if dt2 in ratio:
                    if prev is not None and abs(ratio[dt2] / ratio[prev] - 1) > 0.015:
                        flagged.add(dt2)
                    prev = dt2
            m6 = _m6_tmp
            for i in range(61, d["n"] - 7):
                try:
                    if not det(d, i):
                        continue
                except Exception:
                    continue
                ei = i + 1
                xi = ei + 5
                if xi >= d["n"]:
                    continue
                ed, xd = d["date"][ei], d["date"][xi]
                if ed < WIN0:
                    continue
                if any(dd in flagged for dd in ks_dates[i:xi + 1]):   # 除权跨度剔除
                    skipped += 1
                    continue
                if m6 is None:
                    continue
                be, bx = m6.get(ed), m6.get(xd)
                if not be or not bx or len(be) < 4 or len(bx) < 4:
                    skipped += 1
                    continue
                # 一字跌停买不进（开盘≈跌停：bar0 open 贴信号日收盘×0.905）
                if be[0]["open"] <= d["c"][i] * 0.905:
                    skipped += 1
                    continue
                # A 入场网格：各时点买 → T+5 尾盘卖
                for sname, slot in SLOTS:
                    r = bx[3]["close"] / slot_price(be, slot) - 1 - FEE
                    entry_grid[sname].append(r)
                # B 离场网格：9:30 买 → 离场日各时点卖
                for sname, slot in SLOTS:
                    r = slot_price(bx, slot) / be[0]["open"] - 1 - FEE
                    exit_grid[sname].append(r)

        print(f"\n=== {name}（窗口 {WIN0}→今，2年）")
        base_e = entry_grid["9:30开"]
        for sname, _ in SLOTS:
            rs = entry_grid[sname]
            wins = sum(x > 0 for x in rs)
            mean = 100 * sum(rs) / len(rs)
            winsl = [x for x in rs if x > 0]
            lossl = [x for x in rs if x <= 0]
            odds = (sum(winsl) / len(winsl)) / abs(sum(lossl) / len(lossl)) if winsl and lossl else 0
            t = nw_t([a - b for a, b in zip(rs, base_e)]) if sname != "9:30开" else 0
            print(f"  入场{sname:<8} n={len(rs)} 胜{100*wins/len(rs):.1f}% 均{mean:+.2f}% 赔{odds:.2f} 对开盘差t={t:.1f}")
        base_x = exit_grid["15:00尾盘"]
        for sname, _ in SLOTS:
            rs = exit_grid[sname]
            wins = sum(x > 0 for x in rs)
            mean = 100 * sum(rs) / len(rs)
            t = nw_t([a - b for a, b in zip(rs, base_x)]) if sname != "15:00尾盘" else 0
            print(f"  离场{sname:<8} n={len(rs)} 胜{100*wins/len(rs):.1f}% 均{mean:+.2f}% 对尾盘差t={t:.1f}")
        print(f"  (剔除不可成交/缺bar {skipped})")


if __name__ == "__main__":
    main()

===== engine/research_queue_20260919.py =====
#!/usr/bin/env python3
"""research_queue_20260919.py — 用户五问研究队列（2026-09-19 立项，全排进去跑）。

R1 裸底座衰退机制：跌停接_MA60下 分年份 T+1/T+5 胜率/均值/位置匹配边际——edge 什么时候消失的
R2 成簇过滤 K×槽位二维网格：K∈{1,3,5,10,20} × slots∈{5,10,30}，3 个主信号，找容量最优区
R3 T1 强度加仓开关：T1 收盘≥+3% 次日开盘加一槽 vs 不加（组合_跌停低_长周期_超跌20，K5 口径）
R4 高位剧震回避黑名单：近10日≥2涨停 + 天量剧震 → 前向 T+1/5/20（预期显著为负→黑名单）
R5 席位×恐慌接跌：跌停低事件 ∩ 当日龙虎榜（格局席位净买/机构净买）分组对比（1年深度，诚实限量）
输出：data/research_queue_20260919.json（全部结果）+ 逐题打印
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import law_pipeline as lp

ROOT = Path(__file__).resolve().parent.parent
FEE = 0.0015
OUT = {}


def fwd(d, i, h):
    """次日开盘买，入场日+h 收盘卖，净口径。"""
    ei = i + 1
    if ei >= d["n"] or ei + h >= d["n"] or d["o"][ei] <= 0:
        return None
    if d["o"][ei] <= d["c"][i] * 0.905:   # 一字跌停买不进
        return None
    return d["c"][ei + h] / d["o"][ei] - 1 - FEE


def stat(rs):
    if not rs:
        return None
    wins = [r for r in rs if r > 0]
    return {"n": len(rs), "win%": round(100 * len(wins) / len(rs), 1),
            "mean%": round(100 * sum(rs) / len(rs), 2)}


# ---------------- R1 ----------------
def r1(stocks):
    det = lp.REGISTRY["跌停接_MA60下"]
    by_year = defaultdict(list)      # year -> [(code,i)]
    for code, d in stocks.items():
        c, ma, n = d["c"], d["ma60"], d["n"]
        for i in range(61, n - 22):
            if ma[i] is not None and c[i] <= ma[i] and c[i-1] > 0 and c[i]/c[i-1]-1 <= -0.095:
                by_year[d["date"][i][:4]].append((code, i))
    res = {}
    for y in sorted(by_year):
        evs = by_year[y]
        r1s = [fwd(stocks[c], i, 1) for c, i in evs]
        r5s = [fwd(stocks[c], i, 5) for c, i in evs]
        res[y] = {"n": len(evs), "T+1": stat([x for x in r1s if x is not None]),
                  "T+5": stat([x for x in r5s if x is not None])}
    OUT["R1_裸底座分年"] = res
    for y, v in res.items():
        print(f"R1 {y}: n={v['n']} T+1 {v['T+1']['win%']}%/{v['T+1']['mean%']}%  T+5 {v['T+5']['win%']}%/{v['T+5']['mean%']}%", flush=True)


# ---------------- R2 ----------------
def r2(stocks):
    grid = {}
    for name in ["跌停接_MA60下", "组合_跌停低_长周期_超跌20", "组合_跌停低_TD9买入滤"]:
        sigs = lp._collect_sigs(lp.REGISTRY[name], stocks)
        rec = {}
        for K in (1, 3, 5, 10, 20):
            for slots in (5, 10, 30):
                r = lp.capacity_sim(sigs, stocks, slots=slots, hold=5, cluster_k=K, seeds=2)
                rec[f"K{K}_槽{slots}"] = r
                print(f"R2 {name} K{K}槽{slots}: 年化{r['年化%']}% 均笔{r['均笔%']}% 回撤{r['回撤%']}%", flush=True)
        grid[name] = rec
    OUT["R2_Kx槽位"] = grid


# ---------------- R3 ----------------
def r3(stocks):
    """T1 强度加仓：买入后首日(T1)收盘 ≥+3% → T2 开盘加一槽。对照=不加。K5 成簇过滤。"""
    import random as _random
    name = "组合_跌停低_长周期_超跌20"
    sigs = lp._collect_sigs(lp.REGISTRY[name], stocks)
    dates = sorted({x for s in stocks.values() for x in s["date"]})
    didx = {c: {x: j for j, x in enumerate(s["date"])} for c, s in stocks.items()}

    def run(add_on_strength):
        rnd = _random.Random(7)
        cap0, slots, hold = 1_000_000.0, 10, 5
        cash, pos, trades, eqs = cap0, [], [], []
        for k, day in enumerate(dates):
            keep = []
            for code, ei, xi, val, added in pos:
                j = didx[code].get(day, -1)
                d = stocks[code]
                # T1 收盘判定加仓（T1=入场日 ei；次日 ei+1 开盘加一槽）
                if add_on_strength and not added and j == ei + 1:
                    pc = d["o"][ei]
                    if pc > 0 and d["c"][ei] / pc - 1 >= 0.03 and cash >= cap0 / slots:
                        cash -= cap0 / slots
                        keep.append((code, ei, xi, val, True))
                        keep.append((code, ei + 1, xi, cap0 / slots, True))  # 加仓腿：ei+1 开盘买
                        continue
                if j < 0 or j < xi:
                    keep.append((code, ei, xi, val, added)); continue
                if xi >= d["n"] or d["c"][xi] <= 0 or d["o"][ei] <= 0:
                    keep.append((code, ei, xi, val, added)); continue
                r = d["c"][xi] / d["o"][ei] - 1 - FEE
                cash += val * (1 + r)
                trades.append(r * 100)
            pos = keep
            if k > 0:
                lst = sigs.get(dates[k - 1], [])
                cands = [s for s in lst if didx[s[0]].get(day) == s[1] + 1]
                if len(lst) < 5:
                    cands = []
                rnd.shuffle(cands)
                for code, i in cands[:max(0, slots - len(pos))]:
                    if cash < cap0 / slots:
                        break
                    cash -= cap0 / slots
                    pos.append((code, i + 1, i + 1 + hold, cap0 / slots, False))
            eqs.append(cash + sum(v for *_x, v, _a in pos))
        yrs = len(dates) / 244.0
        final = eqs[-1]
        peak, mdd = -1e18, 0
        for e in eqs:
            peak = max(peak, e)
            mdd = min(mdd, e / peak - 1)
        return {"年化%": round(((final / cap0) ** (1 / yrs) - 1) * 100, 1),
                "回撤%": round(mdd * 100, 1), "笔数": len(trades),
                "均笔%": round(sum(trades) / len(trades), 2) if trades else 0}

    base, add = run(False), run(True)
    OUT["R3_T1加仓"] = {"不加仓": base, "T1≥3%加仓": add}
    print(f"R3: 不加 {base}  vs  加仓 {add}", flush=True)


# ---------------- R4 ----------------
def r4(stocks):
    """高位剧震回避：近10日≥2涨停 + 今日天量剧震（量比≥2 且 上影≥4%或大阴≤-4%）。"""
    def is_quake(d, i):
        c, o, h, l, v = d["c"], d["o"], d["h"], d["l"], d["v"]
        if i < 12 or c[i] <= 0 or c[i - 1] <= 0:
            return False
        boards = sum(1 for j in range(i - 10, i) if c[j] > 0 and c[j - 1] > 0 and c[j] / c[j - 1] - 1 >= 0.098)
        if boards < 2:
            return False
        base = v[i - 5:i]
        if len(base) < 5 or any(x <= 0 for x in base):
            return False
        mb = sum(base) / 5
        if mb <= 0 or v[i] / mb < 2.0:
            return False
        chg = c[i] / c[i - 1] - 1
        upper = (h[i] - c[i]) / c[i]
        return upper >= 0.04 or chg <= -0.04

    rs = {1: [], 5: [], 20: []}
    ctrl = {1: [], 5: [], 20: []}
    import random
    rng = random.Random(19)
    for code, d in stocks.items():
        c, ma, n = d["c"], d["ma60"], d["n"]
        hits_i = []
        for i in range(61, n - 22):
            if ma[i] is not None and c[i] > ma[i] and is_quake(d, i):   # 高位=MA60上
                hits_i.append(i)
        for i in hits_i:
            for h in (1, 5, 20):
                r = fwd(d, i, h)
                if r is not None:
                    rs[h].append(r)
        # 同票高位非剧震对照（等量）
        pool = [i for i in range(61, n - 22) if ma[i] is not None and c[i] > ma[i] and not is_quake(d, i)]
        for i in rng.sample(pool, min(len(hits_i) * 2, len(pool))):
            for h in (1, 5, 20):
                r = fwd(d, i, h)
                if r is not None:
                    ctrl[h].append(r)
    OUT["R4_高位剧震"] = {f"T+{h}": {"剧震": stat(rs[h]), "高位对照": stat(ctrl[h]),
                                "边际pp": round((sum(rs[h]) / len(rs[h]) - sum(ctrl[h]) / len(ctrl[h])) * 100, 2)
                                if rs[h] and ctrl[h] else None}
                          for h in (1, 5, 20)}
    for h in (1, 5, 20):
        print(f"R4 T+{h}: 剧震 {stat(rs[h])} vs 高位对照 {stat(ctrl[h])}", flush=True)


# ---------------- R5 ----------------
def r5(stocks):
    HT = ROOT / "data/hithink"
    det = lp.REGISTRY["跌停接_MA60下"]
    # 格局型席位（seat_gene v1 实证：T5 衰减慢 = 题材含金量）
    GEJU = ("成都", "中山东路", "章盟主", "炒股养家")
    groups = {"格局席位净买": [], "机构净买": [], "上榜但无": [], "未上榜": []}
    for ddir in sorted(HT.iterdir()):
        if not ddir.is_dir():
            continue
        day = ddir.name
        hot = org = None
        fh, fo = ddir / "lhb_hot.json", ddir / "lhb_org.json"
        geju_codes, org_codes, board_codes = set(), set(), set()
        if fh.exists():
            hot = json.loads(fh.read_text())["data"]
            for seat in hot.get("hot_money_items") or []:
                sname = seat.get("name", "")
                if any(g in sname for g in GEJU):
                    for r in seat.get("rows") or []:
                        if (r.get("hot_money_item_net_value") or 0) > 0:
                            geju_codes.add(r["ticker"])
                        board_codes.add(r["ticker"])
        if fo.exists():
            org = json.loads(fo.read_text())["data"]
            for r in org.get("stock_items") or []:
                board_codes.add(r["ticker"])
                if (r.get("org_net_value") or 0) > 0:
                    org_codes.add(r["ticker"])
        for code, d in stocks.items():
            idx = {x: j for j, x in enumerate(d["date"])}
            i = idx.get(day)
            if i is None or i < 61:
                continue
            c, ma = d["c"], d["ma60"]
            if not (ma[i] is not None and c[i] <= ma[i] and c[i-1] > 0 and c[i]/c[i-1]-1 <= -0.095):
                continue
            r = fwd(d, i, 5)
            if r is None:
                continue
            tick = code + (".SH" if code.startswith("6") else ".SZ")
            if code in geju_codes or tick in geju_codes:
                groups["格局席位净买"].append(r)
            elif code in org_codes or tick in org_codes:
                groups["机构净买"].append(r)
            elif code in board_codes or tick in board_codes:
                groups["上榜但无"].append(r)
            else:
                groups["未上榜"].append(r)
    OUT["R5_席位x恐慌"] = {k: stat(v) for k, v in groups.items()}
    for k, v in groups.items():
        print(f"R5 {k}: {stat(v)}", flush=True)


def main():
    stocks = lp.load_universe()
    lp.build_xsection(stocks)
    for fn in (r1, r2, r3, r4, r5):
        try:
            fn(stocks)
        except Exception as e:
            print(f"[ERR] {fn.__name__}: {e}", flush=True)
            OUT[fn.__name__ + "_error"] = str(e)
        (ROOT / "data/research_queue_20260919.json").write_text(
            json.dumps(OUT, ensure_ascii=False, indent=1))
    print("saved", ROOT / "data/research_queue_20260919.json")


if __name__ == "__main__":
    main()

===== engine/winloss_autopsy.py =====
#!/usr/bin/env python3
"""winloss_autopsy.py — 命中票的胜负解剖（2026-09-19 用户立项：不是差不多就完事）。

对组合命中事件逐笔算 T+5，按收益分档（大赢>+10% / 大胜>+3% / 平 / 大亏<-5%），
对比各档在信号日的特征分布，找「涨的和跌的」之间真正分开的变量。
特征（全部信号日时点可知）：量比、距MA60深度、连跌天数、60日超跌深度、跌停日是否开板
（h>c 承接痕迹）、一字跌停（h==l）、次日缺口、流通市值、peTTM/亏损、regime、年份。
另输出 top10/bottom10 具名案例供人工复盘。
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import law_pipeline as lp

ROOT = Path(__file__).resolve().parent.parent
FEE = 0.0015
SIG = sys.argv[1] if len(sys.argv) > 1 else "组合_跌停低_三连阴"


def feats(d, i, code, fund, capm):
    c, o, h, l, v, ma = d["c"], d["o"], d["h"], d["l"], d["v"], d["ma60"]
    f = {}
    f["量比"] = lp._volratio(d, i)
    f["距MA60%"] = round((c[i] / ma[i] - 1) * 100, 1) if ma[i] else None
    f["连跌天数"] = 0
    j = i
    while j > 0 and c[j] < c[j - 1]:
        f["连跌天数"] += 1
        j -= 1
    hi60 = max(c[max(0, i - 60):i + 1])
    f["超跌深度%"] = round((c[i] / hi60 - 1) * 100, 1) if hi60 > 0 else None
    f["跌停开板"] = h[i] > c[i] * 1.001      # 盘中高于收盘=开板过（有承接/撬板）
    f["一字跌停"] = h[i] == l[i]
    f["次日缺口%"] = round((o[i + 1] / c[i] - 1) * 100, 1) if i + 1 < d["n"] else None
    cap = lp.cap_at_date(capm, code, d["date"][i])  # PIT 日频
    f["市值亿"] = cap
    fu = fund.get(code, {}).get(d["date"][i])
    f["peTTM"] = fu[0] if fu else None           # _XFUND 值=(peTTM, isST) 二元组
    f["亏损"] = (fu[0] is not None and fu[0] <= 0) if fu else None
    return f


def main():
    stocks = lp.load_universe()
    lp.build_xsection(stocks)
    regime = lp.load_regime()
    fund = lp._XFUND
    capm = lp._XCAP

    det = lp.REGISTRY[SIG]
    rows = []
    for code, d in stocks.items():
        for i in range(61, d["n"] - 7):
            try:
                if not det(d, i):
                    continue
            except Exception:
                continue
            ei = i + 1
            if d["o"][ei] <= d["c"][i] * 0.905:
                continue
            r5 = d["c"][ei + 5] / d["o"][ei] - 1 - FEE
            f = feats(d, i, code, fund, capm)
            f.update({"code": code, "date": d["date"][i], "r5": round(r5 * 100, 2),
                      "regime": regime.get(d["date"][i], "?"), "year": d["date"][i][:4]})
            rows.append(f)
    print(f"{SIG}: 事件 {len(rows)}")

    # 分档
    big_win = [r for r in rows if r["r5"] >= 10]
    win = [r for r in rows if 3 <= r["r5"] < 10]
    flat = [r for r in rows if -3 < r["r5"] < 3]
    big_loss = [r for r in rows if r["r5"] <= -5]
    print(f"大赢(≥+10%) {len(big_win)} | 中赢(+3~10) {len(win)} | 平 {len(flat)} | 大亏(≤-5%) {len(big_loss)}")

    KEYS = ["量比", "距MA60%", "连跌天数", "超跌深度%", "次日缺口%", "市值亿", "peTTM"]

    def med(rs, k):
        vs = sorted(r[k] for r in rs if r.get(k) is not None)
        return round(vs[len(vs) // 2], 2) if vs else None

    def rate(rs, k):
        vs = [r[k] for r in rs if r.get(k) is not None]
        return round(100 * sum(vs) / len(vs), 1) if vs else None

    print(f"\n{'特征':<10}{'大赢':>8}{'中赢':>8}{'平':>8}{'大亏':>8}")
    for k in KEYS:
        print(f"{k:<10}{med(big_win, k)!s:>8}{med(win, k)!s:>8}{med(flat, k)!s:>8}{med(big_loss, k)!s:>8}")
    for k in ("跌停开板", "一字跌停", "亏损"):
        print(f"{k + '率%':<10}{rate(big_win, k)!s:>8}{rate(win, k)!s:>8}{rate(flat, k)!s:>8}{rate(big_loss, k)!s:>8}")

    # regime/年份分布
    for dim in ("regime", "year"):
        print(f"\n按{dim}（大赢占比% / 大亏占比%）:")
        groups = defaultdict(lambda: [0, 0, 0])
        for r in rows:
            g = groups[r[dim]]
            g[0] += 1
            if r["r5"] >= 10:
                g[1] += 1
            if r["r5"] <= -5:
                g[2] += 1
        for k in sorted(groups):
            n, w, l = groups[k]
            print(f"  {k}: n={n} 大赢{100*w/n:.0f}% 大亏{100*l/n:.0f}%")

    # 具名案例
    rows.sort(key=lambda r: -r["r5"])
    print("\n=== 大赢案例 TOP10")
    for r in rows[:10]:
        print(f"  {r['date']} {r['code']} r5={r['r5']}% 量比{r['量比']:.1f} 距MA60 {r['距MA60%']}% 连跌{r['连跌天数']} 超跌{r['超跌深度%']}% 开板{r['跌停开板']} 市值{r['市值亿']} pe{r['peTTM']} {r['regime']}")
    print("=== 大亏案例 TOP10")
    for r in rows[-10:]:
        print(f"  {r['date']} {r['code']} r5={r['r5']}% 量比{r['量比']:.1f} 距MA60 {r['距MA60%']}% 连跌{r['连跌天数']} 超跌{r['超跌深度%']}% 开板{r['跌停开板']} 市值{r['市值亿']} pe{r['peTTM']} {r['regime']}")

    (ROOT / f"data/winloss_autopsy_{SIG}_20260919.json").write_text(
        json.dumps(rows, ensure_ascii=False))


if __name__ == "__main__":
    main()

===== engine/exit_rule_grid.py =====
#!/usr/bin/env python3
"""exit_rule_grid.py — 卖点研究：存活信号的出场规则网格（2026-09-18 夜间批）。

用户原话：「不光研究买点，而且要研究卖的时机让收益最大化，不是笼统固定时间买卖」。
口径（对齐 law_pipeline.capacity_sim）：
  信号日 i 收盘确认 → 次日 i+1 开盘买（开盘一字跌停作废，o[i+1]<=c[i]*0.905）
  → 出场规则触发 → 净收益 = exit/entry - 1 - 0.0015（往返费）。
T+1 物理：入场日当天不能卖，所有盘中规则最早次日（j>i+1）生效；
  当天高低同时触止盈止损 = 保守记止损先（同 bar 不可知顺序）。

规则族：
  fixed_N    : 入场日+N 天收盘卖，N∈{1,2,3,5,8,13,21}（基线）
  tpX_sY     : 止盈 +X% / 止损 -Y% 盘中触价（high/low），先到先走，兜底 T+21 收盘
  trail_Z    : 移动止盈：收盘从峰值回撤 Z% 离场，兜底 T+21
  ma60_out   : 收盘收复 MA60 次日收盘离场，兜底 T+21
  tp6s3_ma60 : 止盈止损 + MA60 回收 双条件先到先走
指标：n / win% / mean% / med% / 赔率(平均盈利/|平均亏损|) / 期望 / 平均持有天数。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import law_pipeline as lp

ROOT = Path(__file__).resolve().parent.parent
FEE = 0.0015
CAP_HOLD = 21          # 所有规则兜底持有上限
LD_LOCK = -0.095       # 跌停封死（收盘<=入场日基准×(1-9.5%) 视为卖不出顺延）

# 受试信号：G7/事件研究存活系（死的票不进策略——用户裁决）
SIGNALS = [
    "跌停接_MA60下_缩量",
    "组合_跌停低_长周期_超跌20",
    "组合_跌停低_三连阴",
    "组合_跌停低_避雷针低位",
    "组合_缺口低开_低位阳线",
    "组合_触板未封_低位",
]

RULES_FIXED = [("fixed_%d" % n, ("fixed", n)) for n in (1, 2, 3, 5, 8, 13, 21)]
RULES_TP = [(f"tp{tp}_s{sl}", ("tpsl", tp / 100, sl / 100)) for tp, sl in ((4, 3), (6, 3), (8, 5), (10, 5))]
RULES_TRAIL = [(f"trail_{z}", ("trail", z / 100)) for z in (5, 8)]
RULES = RULES_FIXED + RULES_TP + RULES_TRAIL + [
    ("ma60_out", ("ma60",)),
    ("tp6s3_ma60", ("tpsl_ma60", 0.06, 0.03)),
]


def collect_events(detect, stocks):
    """(code, i) 事件列表，口径同 _collect_sigs。"""
    evs = []
    for code, d in stocks.items():
        c, o, ma, n = d["c"], d["o"], d["ma60"], d["n"]
        for i in range(61, n - CAP_HOLD - 2):
            if c[i-1] <= 0 or c[i] <= 0 or o[i+1] <= 0 or ma[i] is None:
                continue
            if o[i+1] <= c[i] * 0.905:
                continue
            try:
                if detect(d, i):
                    evs.append((code, i))
            except Exception:
                pass
    return evs


def simulate(d, i, rule):
    """返回 (净收益率, 持有天数)。买=o[i+1]；规则见模块 docstring。"""
    c, o, h, l, ma, n = d["c"], d["o"], d["h"], d["l"], d["ma60"], d["n"]
    ei = i + 1
    entry = o[ei]
    kind = rule[0]
    if kind == "fixed":
        hold = rule[1]
        j = ei + hold
        while j < n and c[j] <= entry * (1 + LD_LOCK):   # 出场日跌停顺延（≤3 天）
            if j - ei >= hold + 3:
                break
            j += 1
        if j >= n:
            return None
        return c[j] / entry - 1 - FEE, j - ei

    peak = entry
    for j in range(ei, min(ei + CAP_HOLD + 1, n)):
        # 入场日只记录峰值/观察，不卖（T+1）
        sellable = j > ei
        if sellable and c[j] <= entry * (1 + LD_LOCK):
            continue  # 跌停封死卖不出，顺延
        if kind in ("tpsl", "tpsl_ma60"):
            tp, sl = rule[1], rule[2]
            if sellable:
                hit_tp = h[j] >= entry * (1 + tp)
                hit_sl = l[j] <= entry * (1 - sl)
                if hit_sl:      # 同 bar 双触保守记止损
                    return (entry * (1 - sl)) / entry - 1 - FEE, j - ei
                if hit_tp:
                    return tp - FEE, j - ei
                if kind == "tpsl_ma60" and ma[j] is not None and c[j] > ma[j]:
                    return c[j] / entry - 1 - FEE, j - ei
        elif kind == "trail":
            z = rule[1]
            peak = max(peak, c[j])
            if sellable and c[j] <= peak * (1 - z):
                return c[j] / entry - 1 - FEE, j - ei
        elif kind == "ma60":
            if sellable and ma[j] is not None and c[j] > ma[j]:
                return c[j] / entry - 1 - FEE, j - ei
    j = min(ei + CAP_HOLD, n - 1)
    while j > ei and c[j] <= entry * (1 + LD_LOCK):
        j -= 1
        if j <= ei:
            return None  # 全程锁死，剔除（买不进/卖不出幻觉剔除）
    return c[j] / entry - 1 - FEE, j - ei


def metrics(rs):
    if not rs:
        return None
    wins = [r for r, _ in rs if r > 0]
    losses = [r for r, _ in rs if r <= 0]
    rets = sorted(r for r, _ in rs)
    n = len(rets)
    mean = sum(rets) / n
    odds = (sum(wins) / len(wins)) / abs(sum(losses) / len(losses)) if wins and losses else None
    return {
        "n": n,
        "win%": round(100 * len(wins) / n, 1),
        "mean%": round(100 * mean, 2),
        "med%": round(100 * rets[n // 2], 2),
        "赔率": round(odds, 2) if odds else None,
        "期望pp": round(100 * mean, 2),
        "avg持有天": round(sum(h for _, h in rs) / n, 1),
    }


def main():
    # 2026-09-19 用户裁决「比赛也得配上卖点」：--all 时对 REGISTRY 全部信号跑入场×出场矩阵
    sig_list = SIGNALS
    if "--all" in sys.argv:
        sig_list = sorted(lp.REGISTRY.keys())
    stocks = lp.load_universe()
    lp.build_xsection(stocks)
    out = {}
    for name in sig_list:
        det = lp.REGISTRY.get(name)
        if det is None:
            print(f"[skip] {name} 不在注册表", flush=True)
            continue
        evs = collect_events(det, stocks)
        print(f"{name}: 事件 {len(evs)}", flush=True)
        rec = {}
        for rname, rule in RULES:
            rs = []
            for code, i in evs:
                r = simulate(stocks[code], i, rule)
                if r is not None:
                    rs.append(r)
            m = metrics(rs)
            if m:
                rec[rname] = m
        out[name] = rec
        best = max(rec.items(), key=lambda kv: kv[1]["期望pp"]) if rec else None
        print(f"  最优: {best[0]} 期望{best[1]['期望pp']}pp 胜{best[1]['win%']}% 赔{best[1]['赔率']}" if best else "  无有效", flush=True)
    dst = ROOT / f"data/exit_rule_grid{'_all' if '--all' in sys.argv else ''}_20260919.json"
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("saved", dst)


if __name__ == "__main__":
    main()

===== engine/shadow_rebuild.py =====
#!/usr/bin/env python3
"""shadow_rebuild.py — 影子账本全量重建清洗（2026-09-19 用户立项：旧账有脏数据/bug）。

背景：claims_shadow.jsonl 早期条目的 entry/r1/r5/r20 是在有 bug 的实现下填的——
  · C2（9/12 前）：可成交性在信号日判（应在入场日判）
  · T+0 幻觉（9/18 前）：open-entry 族的收益从信号日开盘价算到当日收盘，物理不可能
  · C3（9/12 前）：退市股末日幽灵信号
本脚本不删历史、全部用现行正确口径重算，逐条覆写；改动量写报告。
口径源 = claims_shadow.py 第 230-268 行的现行回填逻辑（逐行对齐，禁自由发挥）。
"""
import json
import shutil
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHADOW = ROOT / "data/claims_shadow.jsonl"
SUMMARY = ROOT / "data/claims_shadow_summary.json"
FEE = 0.0015
CLOSE_ENTRY_CLAIMS = {"FRONTRUN_FIRSTBOARD_V2", "WATCHPOOL_GRAD"}


def load_stocks():
    out = {}
    for fp in sorted((ROOT / "data/big_kcache").glob("*.json")):
        ks = json.loads(fp.read_text())
        if len(ks) >= 2:
            out[fp.stem] = ks
    return out


def refill(r, ks):
    """重置并用现行口径重算一条单。返回是否有改动。"""
    old = dict(r)
    for k in ("entry", "r1", "r5", "r20", "untradeable"):
        r.pop(k, None)
    idx = {k["date"]: j for j, k in enumerate(ks)}
    si = idx.get(r["signal_date"])
    if si is None:
        r["stale"] = "信号日不在该票k线（幽灵/已退市缺数据）"
        return old != r
    if r["claim"] in CLOSE_ENTRY_CLAIMS:
        if ks[si]["high"] <= ks[si]["low"]:
            r["untradeable"] = "信号日一字板买不进"
        else:
            e = ks[si]["close"]
            if e > 0:
                r["entry"] = e
        ei = si
    else:
        if si + 1 >= len(ks):
            r["stale"] = "信号日为最后一根bar，无入场日"
            return old != r
        e = ks[si + 1]["open"]
        pc0 = ks[si]["close"]
        gap = e / pc0 - 1 if pc0 > 0 else 0
        amp = (ks[si + 1]["high"] - ks[si + 1]["low"]) / pc0 if pc0 > 0 else 1
        if gap >= 0.095:
            r["untradeable"] = "一字涨停买不进"
        elif gap <= -0.095 and amp < 0.01:
            r["untradeable"] = "一字跌停锁死"
        elif e > 0:
            r["entry"] = e
        ei = si + 1
    if r.get("entry"):
        e = r["entry"]
        for tag, off in (("r1", 1), ("r5", 5), ("r20", 20)):
            if ei + off < len(ks):
                r[tag] = round(ks[ei + off]["close"] / e - 1 - FEE, 5)
    return old != r


def main():
    bak = SHADOW.with_suffix(".jsonl.bak_20260919")
    if not bak.exists():
        shutil.copy2(SHADOW, bak)
    stocks = load_stocks()
    lines, seen, dedup = [], set(), 0
    changed = 0
    missing_stock = 0
    for raw in SHADOW.read_text().splitlines():
        r = json.loads(raw)
        key = (r["signal_date"], r["claim"], r["code"], r.get("tier"))
        if key in seen:
            dedup += 1
            continue
        seen.add(key)
        ks = stocks.get(r["code"])
        if ks is None:
            missing_stock += 1
            r["stale"] = "kcache 无此票"
        else:
            if refill(r, ks):
                changed += 1
        lines.append(r)
    SHADOW.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in lines) + "\n")

    # 汇总（只统可成交单；口径同 claims_shadow.py 第3段）
    import statistics as st
    summ = defaultdict(list)
    for r in lines:
        if not r.get("entry"):
            continue
        for tag in ("r1", "r5", "r20"):
            v = r.get(tag)
            if v is not None:
                summ[(r["claim"], r.get("tier") or "-", tag)].append(v)
    out = {}
    for (claim, tier, tag), vs in sorted(summ.items()):
        out.setdefault(claim, {}).setdefault(tier, {})[tag] = {
            "n": len(vs), "win%": round(100 * sum(x > 0 for x in vs) / len(vs), 1),
            "mean%": round(100 * st.mean(vs), 2)}
    SUMMARY.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"重建完成：{len(lines)} 单（去重-{dedup}，无票-{missing_stock}），重算改动 {changed} 单")
    print(f"备份：{bak.name}")


if __name__ == "__main__":
    main()

===== engine/good_regime_playbook.py =====
#!/usr/bin/env python3
"""good_regime_playbook.py — 情绪好时玩什么（2026-09-19 用户批评「只有恐慌策略」立项）。

全注册表 × 4 regime × T+1/T+5 扫描，找主线期/妖股期的正期望格。
每格要求 n≥100 才显示；标 t 值。产出「情绪好时的可玩清单」。
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import law_pipeline as lp

ROOT = Path(__file__).resolve().parent.parent
FEE = 0.0015


def fwd(d, i, h):
    ei = i + 1
    if ei + h >= d["n"] or d["o"][ei] <= 0 or d["o"][ei] <= d["c"][i] * 0.905:
        return None
    return d["c"][ei + h] / d["o"][ei] - 1 - FEE


def stat(rs):
    rs = [r for r in rs if r is not None]
    if len(rs) < 100:
        return None
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    m = sum(rs) / len(rs)
    sd = (sum((x - m) ** 2 for x in rs) / len(rs)) ** 0.5 or 1e-9
    odds = (sum(wins) / len(wins)) / abs(sum(losses) / len(losses)) if wins and losses else None
    return {"n": len(rs), "win%": round(100 * len(wins) / len(rs), 1), "mean%": round(100 * m, 2),
            "t": round(m / sd * len(rs) ** 0.5, 1), "赔率": round(odds, 2) if odds else None}


# ---- 情绪好时的专用检测器（2026-09-19 加：注册表全是抄底味，补两只强势侧）----
def _strong_pullback_ma5(d, i):
    """强势股回踩MA5：近20日≥2次涨停（强势证明）+ 收盘在MA10上 + 今日盘中跌破MA5收回（回踩）。"""
    c, l, n = d["c"], d["l"], d["n"]
    if i < 25 or c[i] <= 0:
        return False
    boards = sum(1 for j in range(i - 20, i) if c[j] > 0 and c[j - 1] > 0 and c[j] / c[j - 1] - 1 >= 0.098)
    if boards < 2:
        return False
    ma5 = sum(c[i - 4:i + 1]) / 5
    ma10 = sum(c[i - 9:i + 1]) / 10
    return l[i] < ma5 <= c[i] and c[i] > ma10


def _strong_pullback_ma10(d, i):
    """强势股回踩MA10（更深一档回调）。"""
    c, l, n = d["c"], d["l"], d["n"]
    if i < 25 or c[i] <= 0:
        return False
    boards = sum(1 for j in range(i - 20, i) if c[j] > 0 and c[j - 1] > 0 and c[j] / c[j - 1] - 1 >= 0.098)
    if boards < 2:
        return False
    ma10 = sum(c[i - 9:i + 1]) / 10
    ma20 = sum(c[i - 19:i + 1]) / 20
    return l[i] < ma10 <= c[i] and c[i] > ma20


def main():
    stocks = lp.load_universe()
    lp.build_xsection(stocks)
    regime = lp.load_regime()
    registry = dict(lp.REGISTRY)
    registry["强势股回踩MA5"] = _strong_pullback_ma5
    registry["强势股回踩MA10"] = _strong_pullback_ma10
    # 每信号 × regime × horizon
    out = {}
    for name, det in registry.items():
        cells = defaultdict(list)
        for code, d in stocks.items():
            for i in range(61, d["n"] - 21):
                rg = regime.get(d["date"][i])
                if rg is None:
                    continue
                try:
                    if det(d, i):
                        r1 = fwd(d, i, 1)
                        r5 = fwd(d, i, 5)
                        if r1 is not None:
                            cells[(rg, 1)].append(r1)
                        if r5 is not None:
                            cells[(rg, 5)].append(r5)
                except Exception:
                    pass
        good = {}
        for rg in ("主线期", "妖股期"):
            for h in (1, 5):
                s = stat(cells.get((rg, h), []))
                if s:
                    good[f"{rg}_T+{h}"] = s
        if good:
            out[name] = good
    # 打印：主线期/妖股期里 T+5 为正的格子
    print("== 情绪好时（主线期/妖股期）T+5 正期望格 ==")
    found = []
    for name, g in out.items():
        for k, s in g.items():
            if s["mean%"] > 0 and s["t"] >= 2:
                found.append((k, name, s))
    found.sort(key=lambda x: -x[2]["mean%"])
    for k, name, s in found:
        print(f"  {k} | {name}: n={s['n']} 胜{s['win%']}% 均{s['mean%']}% t={s['t']} 赔{s['赔率']}")
    if not found:
        print("  （无 t≥2 正格）")
    (ROOT / "data/good_regime_playbook_20260919.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("saved")


if __name__ == "__main__":
    main()

===== engine/regime_full_study.py =====
#!/usr/bin/env python3
"""regime_full_study.py — 全 regime 覆盖 + 风格剧变期研究（2026-09-19 用户两连令）。

A. 全 regime（主线/妖股/恐慌/平淡）× 关键信号 × T+1/T+5 完整表（一个不落）
B. 风格剧变期：regime 日度转移矩阵 + 翻转窗口识别 +「regime 不稳日」（今日≠昨日）信号表现
"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import law_pipeline as lp

ROOT = Path(__file__).resolve().parent.parent
FEE = 0.0015
SIGS = ["跌停接_MA60下", "组合_跌停低_三连阴", "组合_跌停低_长周期_超跌20", "组合_跌停低_深跌_跌停潮",
        "组合_缺口低开_低位阳线", "组合_触板未封_低位", "强势股回踩MA5", "强势股回踩MA10",
        "反转族_T-1大跌", "金叉_MACD", "TD9买入"]


def fwd(d, i, h):
    ei = i + 1
    if ei + h >= d["n"] or d["o"][ei] <= 0 or d["o"][ei] <= d["c"][i] * 0.905:
        return None
    return d["c"][ei + h] / d["o"][ei] - 1 - FEE


def stat(rs):
    rs = [r for r in rs if r is not None]
    if len(rs) < 50:
        return None
    return {"n": len(rs), "win%": round(100 * sum(x > 0 for x in rs) / len(rs), 1),
            "mean%": round(100 * sum(rs) / len(rs), 2)}


def main():
    stocks = lp.load_universe()
    lp.build_xsection(stocks)
    regime = lp.load_regime()
    tl = json.loads((ROOT / "data/regime_timeline_hcap.json").read_text())
    tl_map = {x["date"]: x["regime"] for x in tl}
    days = sorted(tl_map)

    # B1 转移矩阵 + 翻转率
    trans = Counter()
    flip_days = set()
    for k in range(1, len(days)):
        trans[(tl_map[days[k - 1]], tl_map[days[k]])] += 1
        if tl_map[days[k]] != tl_map[days[k - 1]]:
            flip_days.add(days[k])
    total = sum(trans.values())
    print("== regime 日度转移 ==")
    same = sum(v for (a, b), v in trans.items() if a == b)
    print(f"延续 {same}/{total} = {100*same/total:.1f}%；日翻转率 {100-100*same/total:.1f}%")
    for (a, b), v in trans.most_common(8):
        if a != b:
            print(f"  {a}→{b}: {v} 次")

    # 翻转窗口：10 日内 ≥4 次翻转 = 剧变窗口
    win_flip = {}
    for k in range(len(days)):
        win_flip[days[k]] = sum(1 for d2 in days[max(0, k - 9):k + 1] if d2 in flip_days)
    violent = [d for d in days if win_flip[d] >= 4]
    print(f"\n剧变窗口日（10日内翻转≥4次）: {len(violent)} 天，占 {100*len(violent)/len(days):.1f}%")
    yr = Counter(d[:4] for d in violent)
    print("剧变日分年:", dict(sorted(yr.items())))

    # A+B2 信号 × regime × 稳定/翻转
    print("\n== 信号 × regime ×（稳定日/翻转日）T+5 ==")
    header = f"{'信号':<22}"
    for rg in ("主线期", "妖股期", "恐慌期", "平淡期"):
        header += f"{rg}(稳/翻)".rjust(20)
    print(header)
    out = {}
    for name in SIGS:
        det = lp.REGISTRY.get(name)
        if det is None:
            continue
        cells = defaultdict(list)
        for code, d in stocks.items():
            for i in range(61, d["n"] - 6):
                dt = d["date"][i]
                rg = tl_map.get(dt)
                if rg is None:
                    continue
                try:
                    if det(d, i):
                        r = fwd(d, i, 5)
                        if r is not None:
                            cells[(rg, dt not in flip_days)].append(r)
                except Exception:
                    pass
        line = f"{name:<22}"
        out[name] = {}
        for rg in ("主线期", "妖股期", "恐慌期", "平淡期"):
            ss = stat(cells.get((rg, True), []))
            fs = stat(cells.get((rg, False), []))
            out[name][rg] = {"稳定": ss, "翻转": fs}
            cell = f"{ss['win%']}/{ss['mean%']}n{ss['n']}" if ss else "-"
            cellf = f"{fs['win%']}/{fs['mean%']}" if fs else "-"
            line += f"{cell}|{cellf}".rjust(20)
        print(line, flush=True)

    (ROOT / "data/regime_full_study_20260919.json").write_text(json.dumps({
        "转移矩阵": {f"{a}->{b}": v for (a, b), v in trans.items()},
        "翻转率%": round(100 - 100 * same / total, 1),
        "剧变窗口日数": len(violent), "剧变分年": dict(sorted(yr.items())),
        "信号表": out}, ensure_ascii=False, indent=1))
    print("saved")


if __name__ == "__main__":
    main()

===== engine/nshape_study.py =====
#!/usr/bin/env python3
"""nshape_study.py — N字二波启动走势研究（2026-09-19 用户点名金健米业 600127 立项）。

走势解剖（600127，2026-08 至 09）：底部横盘 → 8/6 放量首板（量比4.7）→ 8/11-14 缩量回踩不破
→ 8/17-18 二波放量再启动 → 天量连板主升（5.6→14.9，+165%）→ 9/2 巨量剧震见顶 → 反包/二顶。

定义「N字二波」事件（检测日=二波启动日）：
  1. 首板日 B：前 3~15 日内，收盘≥+9.8%（涨停）+ 当日量比≥2.5 + 前60日无涨停（低位首板）
  2. 回踩期 B+1 ~ 检测日前：收盘价最低点 ≥ B 日开盘 ×0.97（不破启动位，容差3%）
     且回踩期日均量 ≤ B 日量 ×0.65（缩量洗盘）
  3. 检测日 T：涨幅 ≥ +4% 且 量比 ≥ 1.8（放量再起），收盘 > 回踩期最高收盘（过顶确认）
入场变体（用户裁决：不机械开盘买）：
  E_T_close  检测日收盘买（信号当日可判，14:50 执行口径）
  E_T_open   检测日次日开盘买（框架默认口径，对比用）
出场变体（全部收盘判 14:50 可执行，兜底 20 日；T+1 物理：最早入场日次日卖）：
  X_ma5      收盘跌破 MA5 离场
  X_quake    高位剧震离场：量≥5日均量×2 且（上影≥4% 或 实体大阴≤-4%）
  X_trail10  收盘从峰值回撤 10% 离场
  X_fix5/X_fix10  固定持有
  X_bignum   单日 ≤-7% 大阴离场
指标：n / win% / mean% / med% / 赔率 / 平均持有天；净口径 -0.15%。
对照：同票非事件日随机 5 倍采样（位置对照：涨停链股票波动大，必须同票比）。
"""
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import law_pipeline as lp

ROOT = Path(__file__).resolve().parent.parent
FEE = 0.0015
CAP = 20


def volratio(v, i, n=5):
    base = v[max(0, i - n):i]
    if len(base) < n or any(x <= 0 for x in base):
        return 0.0
    m = sum(base) / len(base)
    return v[i] / m if m > 0 else 0.0


def is_nshape(d, t):
    """检测日 t 是否为 N字二波启动日。返回首板日索引或 None。"""
    c, o, v, n = d["c"], d["o"], d["v"], d["n"]
    if t < 65 or c[t] <= 0 or c[t - 1] <= 0:
        return None
    # 条件3：检测日放量大涨过顶（量比阈值 1.5：参照案例金健 8/18 实测 1.74，1.8 会漏掉它——公开标注校准）
    if c[t] / c[t - 1] - 1 < 0.04 or volratio(v, t) < 1.5:
        return None
    for B in range(t - 3, max(60, t - 15), -1):  # 首板在 3~15 日前
        if c[B] <= 0 or c[B - 1] <= 0:
            continue
        if c[B] / c[B - 1] - 1 < 0.098:      # 首板涨停
            continue
        if volratio(v, B) < 2.5:             # 首板放量
            continue
        # 前60日无涨停（低位首板）
        if any(c[j] > 0 and c[j - 1] > 0 and c[j] / c[j - 1] - 1 >= 0.098
               for j in range(max(1, B - 60), B)):
            continue
        retrace = c[B + 1:t]                  # 回踩期
        if len(retrace) < 2:
            continue
        if min(retrace) < o[B] * 0.97:       # 破启动位
            continue
        # 缩量（2026-09-19 按参照案例校准并公开标注：金健首板次日仍天量，
        # 故分两段判——整体均量不超首板量 + 末端3日收敛到首板量8成以下。
        # 这是对着 n=1 案例调的阈值，属于模式定义而非证据，证据由全样本+闸门给出）
        rv = [v[j] for j in range(B + 1, t)]
        if sum(rv) / len(rv) > v[B]:
            continue
        if len(rv) >= 3 and sum(rv[-3:]) / 3 > v[B] * 0.8:
            continue
        if c[t] <= max(retrace):             # 未过回踩期高点（过顶确认）
            continue
        return B
    return None


def simulate_exit(d, ei, rule):
    """ei=入场日索引，entry=o[ei]。返回 (净收益率, 持有天数) 或 None。"""
    c, o, h, l, v, n = d["c"], d["o"], d["h"], d["l"], d["v"], d["n"]
    entry = o[ei]
    if entry <= 0:
        return None
    peak = entry
    for j in range(ei, min(ei + CAP + 1, n)):
        sellable = j > ei                      # T+1
        if not sellable:
            continue
        if c[j] <= 0:
            continue
        pc = c[j - 1]
        chg = c[j] / pc - 1 if pc > 0 else 0
        peak = max(peak, c[j])
        if rule == "X_ma5":
            if j >= ei + 4:
                ma5 = sum(c[j - 4:j + 1]) / 5
                if c[j] < ma5:
                    return c[j] / entry - 1 - FEE, j - ei
        elif rule == "X_quake":
            vr = volratio(v, j)
            upper = (h[j] - c[j]) / c[j] if c[j] > 0 else 0
            if vr >= 2.0 and (upper >= 0.04 or chg <= -0.04):
                return c[j] / entry - 1 - FEE, j - ei
        elif rule == "X_trail10":
            if c[j] <= peak * 0.90:
                return c[j] / entry - 1 - FEE, j - ei
        elif rule == "X_fix5" and j - ei >= 5:
            return c[j] / entry - 1 - FEE, j - ei
        elif rule == "X_fix10" and j - ei >= 10:
            return c[j] / entry - 1 - FEE, j - ei
        elif rule == "X_bignum" and chg <= -0.07:
            return c[j] / entry - 1 - FEE, j - ei
    j = min(ei + CAP, n - 1)
    if j <= ei:
        return None
    return c[j] / entry - 1 - FEE, j - ei


def metrics(rs):
    if not rs:
        return None
    rets = sorted(r for r, _ in rs)
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    n = len(rets)
    mean = sum(rets) / n
    odds = (sum(wins) / len(wins)) / abs(sum(losses) / len(losses)) if wins and losses else None
    return {"n": n, "win%": round(100 * len(wins) / n, 1), "mean%": round(100 * mean, 2),
            "med%": round(100 * rets[n // 2], 2), "赔率": round(odds, 2) if odds else None,
            "avg持有天": round(sum(h for _, h in rs) / n, 1)}


RULES = ["X_ma5", "X_quake", "X_trail10", "X_fix5", "X_fix10", "X_bignum"]


def find_retrace_entry(d, E):
    """委托 law_pipeline._nshape_retrace（单实现纪律，2026-09-19）。"""
    import law_pipeline as lp
    return True if lp._nshape_retrace(d, E) else None


def main():
    stocks = lp.load_universe()
    lp.build_xsection(stocks)
    events = []   # (code, t, B)
    for code, d in stocks.items():
        n = d["n"]
        for t in range(65, n - CAP - 2):
            B = is_nshape(d, t)
            if B is not None:
                events.append((code, t, B))
    print(f"N字二波事件: {len(events)}", flush=True)

    out = {"事件数": len(events), "入场x出场": {}}
    rng = random.Random(20260919)
    for entry_mode in ("T_close", "T_open"):
        for rule in RULES:
            rs = []
            for code, t, B in events:
                d = stocks[code]
                ei = t if entry_mode == "T_close" else t + 1
                if ei >= d["n"] - 1 or d["o"][ei] <= 0:
                    continue
                # 入场可成交性：次日开盘一字涨停买不进
                if entry_mode == "T_open" and d["o"][ei] / d["c"][t] - 1 >= 0.095:
                    continue
                # 收盘入场用收盘价的等价口径：把 entry 换成 c[t]
                if entry_mode == "T_close":
                    d2 = dict(d)
                    r = simulate_exit_close(d, t, rule)
                else:
                    r = simulate_exit(d, ei, rule)
                if r is not None:
                    rs.append(r)
            m = metrics(rs)
            out["入场x出场"][f"{entry_mode}+{rule}"] = m
            if m:
                print(f"{entry_mode}+{rule}: n={m['n']} 胜{m['win%']}% 均{m['mean%']}% 赔{m['赔率']} 持{m['avg持有天']}天", flush=True)
    dst = ROOT / "data/nshape_study_20260919.json"
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("saved", dst)

    # ---- 回踩期入场变体（E=B+3 收盘买，可执行口径）----
    revents = []
    for code, d in stocks.items():
        for E in range(64, d["n"] - CAP - 2):
            if find_retrace_entry(d, E) is not None:
                revents.append((code, E))
    print(f"回踩期入场事件: {len(revents)}", flush=True)
    for rule in RULES:
        rs = []
        for code, E in revents:
            r = simulate_exit_close(stocks[code], E, rule)
            if r is not None:
                rs.append(r)
        m = metrics(rs)
        out["入场x出场"][f"retrace+{rule}"] = m
        if m:
            print(f"retrace+{rule}: n={m['n']} 胜{m['win%']}% 均{m['mean%']}% 赔{m['赔率']} 持{m['avg持有天']}天", flush=True)
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("saved", dst)


def simulate_exit_close(d, t, rule):
    """收盘入场口径：entry=c[t]，ei=t（当日已持有，次日可卖）。"""
    c, o, h, l, v, n = d["c"], d["o"], d["h"], d["l"], d["v"], d["n"]
    entry = c[t]
    if entry <= 0:
        return None
    peak = entry
    for j in range(t + 1, min(t + CAP + 1, n)):
        if c[j] <= 0:
            continue
        pc = c[j - 1]
        chg = c[j] / pc - 1 if pc > 0 else 0
        peak = max(peak, c[j])
        if rule == "X_ma5":
            if j >= t + 4:
                ma5 = sum(c[j - 4:j + 1]) / 5
                if c[j] < ma5:
                    return c[j] / entry - 1 - FEE, j - t
        elif rule == "X_quake":
            vr = volratio(v, j)
            upper = (h[j] - c[j]) / c[j] if c[j] > 0 else 0
            if vr >= 2.0 and (upper >= 0.04 or chg <= -0.04):
                return c[j] / entry - 1 - FEE, j - t
        elif rule == "X_trail10":
            if c[j] <= peak * 0.90:
                return c[j] / entry - 1 - FEE, j - t
        elif rule == "X_fix5" and j - t >= 5:
            return c[j] / entry - 1 - FEE, j - t
        elif rule == "X_fix10" and j - t >= 10:
            return c[j] / entry - 1 - FEE, j - t
        elif rule == "X_bignum" and chg <= -0.07:
            return c[j] / entry - 1 - FEE, j - t
    j = min(t + CAP, n - 1)
    if j <= t:
        return None
    return c[j] / entry - 1 - FEE, j - t


if __name__ == "__main__":
    main()
