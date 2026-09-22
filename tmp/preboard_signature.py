"""首板前置识别（2026-09-22 深夜，用户问「游资进场之前能不能抓到」）。

中国西电案例：避险持仓中游资来抬轿——问题=首板启动前有没有可检测的吸筹签名。
设计（8 年日K，含退市）：
  事件 = 首板日（60 日无板后首个 ≥+9.8% 涨停，剔一字）。
  前置签名（t 日，票处于无板期）：近 10 日
    A 温和爬升：ret10 ∈ [+2%, +12%]（吸筹不急拉）
    B 量能温和放大：v5/v10 ∈ [1.1, 2.5]（量能起来但不爆）
    C 阳线占比 ≥60%
    D 收盘贴近 20 日高（>0.97×20日高）
  标签：未来 5 个交易日内出首板？
  读数：P(首板|签名) vs P(首板|基率)；买签名日持有到首板日收盘的捕获率（captured return）
  对照：无签名日基率 + 同位置随机。
"""
import collections
import json
import math
import statistics as st
import sys

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

ROOT = "/opt/data/fenjue"
FEE = 0.0015

stocks = lp.load_universe()
print("universe", len(stocks), flush=True)

names = {str(s["code"]).zfill(6): s.get("name", "")
         for s in json.loads(open(f"{ROOT}/data/main_board_codes.json").read())["stocks"]}

sig_days = []      # 签名日
base_days = 0      # 无签名无板期日（基率分母）
base_hits = 0
sig_hits = []
captured = []      # 签名日后 5 日内首板：签名日收盘→首板日收盘的收益
miss_cost = []     # 假阳性成本：签名日收盘买，5 日后收盘卖
fired = 0
for code, d in stocks.items():
    if code[:2] not in ("60", "00"):
        continue
    nm = names.get(code, "")
    if "ST" in nm or "退" in nm:
        continue
    c, o, h, l, v, n = d["c"], d["o"], d["h"], d["l"], d["v"], d["n"]
    # 板日序列
    boards = [i for i in range(1, n) if c[i - 1] > 0 and c[i] / c[i - 1] - 1 >= 0.098]
    board_set = set(boards)
    for i in range(65, n - 6):
        # 无板期（近 60 日无板）
        if any((i - 60) <= b < i for b in boards):
            continue
        if c[i - 1] <= 0:
            continue
        # 未来 5 日首板？
        hit = None
        for j in range(i + 1, min(i + 6, n)):
            if j in board_set:
                hit = j
                break
        # 签名特征
        r10 = c[i] / c[i - 10] - 1 if c[i - 10] > 0 else 0
        v5 = sum(v[i - 4:i + 1]) / 5
        v10 = sum(v[i - 9:i + 1]) / 10
        vr = v5 / v10 if v10 > 0 else 0
        yang = sum(1 for j in range(i - 9, i + 1) if c[j] > c[j - 1]) / 10
        hi20 = max(h[i - 19:i + 1])
        near_hi = c[i] / hi20 if hi20 > 0 else 0
        is_sig = (0.02 <= r10 <= 0.12 and 1.1 <= vr <= 2.5 and yang >= 0.6 and near_hi > 0.97)
        if is_sig:
            fired += 1
            if hit is not None:
                sig_hits.append(1)
                captured.append(c[hit] / c[i] - 1 - FEE)
            else:
                sig_hits.append(0)
                miss_cost.append(c[min(i + 5, n - 1)] / c[i] - 1 - FEE)  # 假阳性成本：签名日收盘买，5 日后收盘卖
        else:
            base_days += 1
            if hit is not None:
                base_hits += 1

p_sig = sum(sig_hits) / len(sig_hits) if sig_hits else 0
p_base = base_hits / base_days if base_days else 0
print(f"\n签名日 {fired}（触发率 {fired/(fired+base_days)*100:.1f}% 的无板期日）")
print(f"P(5日内首板|签名) = {p_sig*100:.2f}%  vs  P(5日内首板|无签名) = {p_base*100:.2f}%  → lift {p_sig/p_base if p_base else 0:.1f}x")
if captured:
    print(f"命中时 签名日收盘→首板日收盘：均值 {st.mean(captured)*100:+.2f}% 中位 {st.median(captured)*100:+.2f}% 胜率 {sum(1 for x in captured if x>0)/len(captured)*100:.0f}% (n={len(captured)})")
if miss_cost:
    print(f"假阳性（没等到板，5日后卖）：均值 {st.mean(miss_cost)*100:+.2f}% 中位 {st.median(miss_cost)*100:+.2f}% (n={len(miss_cost)})")
    exp = p_sig * st.mean(captured) + (1 - p_sig) * st.mean(miss_cost)
    print(f"═══ 签名日全期望（命中吃板+假阳性扛5天）: {exp*100:+.2f}% ═══")
    # 成本口径：签名日收盘买，5 日后收盘卖（没等到板）
    # captured 只含命中——未命中的持有成本需要另算（从签名日收盘买，5日后收盘卖）
print(f"\n基率参考：全部无板期日 {base_days}，5 日内出板 {base_hits}")
json.dump({"签名日": fired, "P签名": round(p_sig, 4), "P基率": round(p_base, 4),
           "lift": round(p_sig / p_base, 2) if p_base else None,
           "命中收益": {"n": len(captured), "mean": round(st.mean(captured) * 100, 2) if captured else None}},
          open(f"{ROOT}/data/preboard_signature_20260922.json", "w"), ensure_ascii=False, indent=1)
print("saved data/preboard_signature_20260922.json")
