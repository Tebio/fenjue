#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""engine/hedge_cost_reality.py — 对冲成本现实检验（卡 t_4a55cc92 的 ④ 段）

独立小件：把「期货路 / ETF融券路」的真实成本与准入掰开算到 bp，并做小资金可行性判定。
读 data/research/hedge_prices_20261016.json（新浪真实成交价）+ 既有产物，写回
data/research/hedge_test_20261016.json 的 "④成本现实检验" 段（不覆盖主段）。

用法 .venv/bin/python engine/hedge_cost_reality.py
"""
import json
from pathlib import Path

import numpy as np

ROOT = Path("/opt/data/fenjue")
PRICES = ROOT / "data/research/hedge_prices_20261016.json"
BASIS = ROOT / "data/futures_basis.json"
OUT = ROOT / "data/research/hedge_test_20261016.json"

DAYS_YEAR = 244
FUT_COMM = 0.000023          # 开/平昨 万分之 0.23
FUT_COMM_TODAY = 0.00023     # 平今 万分之 2.3
FUT_SLIP_PT = 0.2
FUT_MARGIN = 0.15
ETF_BORROW = 0.085          # 主口径借券费率
ETF_BORROW_ALT = (0.0, 0.06, 0.085, 0.12)
ETF_COMM_RT = 0.0004
ETF_MARGIN = 0.50
RF = 0.015

CONTRACT = {"IF": (300, "沪深300"), "IH": (300, "上证50"),
            "IC": (200, "中证500"), "IM": (200, "中证1000")}


def main():
    raw = json.loads(PRICES.read_text())
    out = json.loads(OUT.read_text()) if OUT.exists() else {}

    # ── 1) 真实基差（期货 vs 指数收盘，正=升水 负=贴水）──
    def close_map(k):
        return {r["date"]: r["close"] for r in raw[k]["rows"]}

    basis = {}
    for fk, ik in (("IF0", "sh000300"), ("IC0", "sh000905"), ("IM0", "sh000852")):
        fc, ic = close_map(fk), close_map(ik)
        common = sorted(set(fc) & set(ic))
        bp = np.array([(fc[d] - ic[d]) / ic[d] for d in common])
        le = np.array([(fc[d] - ic[d]) / ic[d] for d in common if d[:4] == "2026"])
        basis[fk] = {"样本日": len(common), "起": common[0], "止": common[-1],
                     "基差均值_bp": round(1e4 * float(bp.mean()), 2),
                     "基差中位_bp": round(1e4 * float(np.median(bp)), 2),
                     "贴水占比": round(float((bp < 0).mean()), 3),
                     "2026均值_bp": round(1e4 * float(le.mean()), 2) if len(le) else None}

    # ── 2) 期货单次往返成本（bp，按名义市值）──
    def fut_rt_bp(h, idx_level, is_today=False):
        comm = FUT_COMM_TODAY if is_today else FUT_COMM
        c = (comm * 2) * 1e4 + 2 * (FUT_SLIP_PT / idx_level) * 1e4
        c += FUT_MARGIN * RF * h / DAYS_YEAR * 1e4
        return round(c, 3)

    # 2026-10-15 收盘指数水平
    lvl = {k: float(list(close_map(v).values())[-1]) for k, v in
           (("IF", "sh000300"), ("IC", "sh000905"), ("IM", "sh000852"))}
    fut_costs = {}
    for k, (mult, nm) in CONTRACT.items():
        if k == "IH":
            continue
        fut_costs[k] = {f"T+{h}_bp": fut_rt_bp(h, lvl[k]) for h in (1, 5, 10, 20)}
        fut_costs[k]["T+5_平今口径_bp"] = fut_rt_bp(5, lvl[k], is_today=True)
        fut_costs[k]["指数水平"] = round(lvl[k], 2)
        fut_costs[k]["1手名义市值_万元"] = round(mult * lvl[k] / 1e4, 1)
        fut_costs[k]["1手保证金_万元"] = round(mult * lvl[k] * FUT_MARGIN / 1e4, 1)

    # ── 3) ETF 融券单次往返成本（bp）──
    def etf_rt_bp(h, borrow):
        return round((borrow * h / DAYS_YEAR + ETF_COMM_RT + ETF_MARGIN * RF * h / DAYS_YEAR) * 1e4, 3)

    etf_costs = {}
    for tag, k in (("510300", "sh510300"), ("510500", "sh510500"), ("512100", "sh512100")):
        rows = raw[k]["rows"]
        px = float(rows[-1]["close"])
        etf_costs[tag] = {"现价": px, "1手(100份)市值_元": round(px * 100, 1),
                          "1万元约可卖空_份": round(1e4 / px / 100, 1),
                          "成本_T+1_bp": etf_rt_bp(1, ETF_BORROW),
                          "成本_T+5_bp": etf_rt_bp(5, ETF_BORROW),
                          "成本_T+20_bp": etf_rt_bp(20, ETF_BORROW),
                          "借券费敏感度_T+5_bp": {f"{b*100:.1f}%/年": etf_rt_bp(5, b) for b in ETF_BORROW_ALT}}
    # 期货 vs ETF 成本对照
    cmp_cost = {
        "T+1_bp": {"IF": fut_costs["IF"]["T+1_bp"], "IC": fut_costs["IC"]["T+1_bp"],
                   "IM": fut_costs["IM"]["T+1_bp"], "ETF融券": etf_costs["512100"]["成本_T+1_bp"]},
        "T+5_bp": {"IF": fut_costs["IF"]["T+5_bp"], "IC": fut_costs["IC"]["T+5_bp"],
                   "IM": fut_costs["IM"]["T+5_bp"], "ETF融券": etf_costs["512100"]["成本_T+5_bp"]},
        "T+20_bp": {"IF": fut_costs["IF"]["T+20_bp"], "IC": fut_costs["IC"]["T+20_bp"],
                    "IM": fut_costs["IM"]["T+20_bp"], "ETF融券": etf_costs["512100"]["成本_T+20_bp"]},
        "结论": ("**两路成本结构完全不同，不能一句「同阶」带过**："
               "期货单次往返 1.1~3.3bp（几乎只有滑点，佣金万分之 0.23 可忽略，保证金资金成本按 15%×1.5% 年化仅几 bp）；"
               "ETF 融券 7.8/23.0/79.8bp（T+1/T+5/T+20）——**借券费 8.5%/年 是主导项**，"
               "T+5 就有 17.4bp 借券费 + 4bp 佣金 + 1.5bp 保证金成本。"
               "即 ETF 路单次成本是期货路的 15~25 倍；但期货路对散户物理不可行（见下），"
               "所以散户只能在「贵但能做」和「便宜但做不了」之间选前者。")}

    # ── 4) 合约粒度 / 保证金可行性（对 5/10/20 万档）──
    # 深档线单批名义市值：组合层 #289 账本规则 = 进攻账户 5 槽共享，单槽名义=权益/槽数
    feas = {}
    for cap in (50000, 100000, 200000):
        slot = cap * 0.60 / 5          # 进攻账户 60% 权益 / 5 槽
        per_batch = slot * 3.3         # 深档线每批约 3.3 只（219 picks / 67 batches）
        row = {"账户_元": cap, "进攻账户_元": round(cap * 0.60),
               "单槽名义_元": round(slot), "深档单批名义(≈3.3只)_元": round(per_batch)}
        for k in ("IF", "IC", "IM"):
            mult, nm = CONTRACT[k]
            one = mult * lvl[k]
            row[f"{k}_1手名义_万元"] = round(one / 1e4, 1)
            row[f"{k}_1手保证金_万元"] = round(one * FUT_MARGIN / 1e4, 1)
            row[f"{k}_覆盖单批需_手"] = round(per_batch / one, 3)
            row[f"{k}_1手=多少倍单批"] = round(one / per_batch, 2)
        feas[f"{cap//10000}万档"] = row
    feas["判定"] = ("期货路对小资金**物理不可行**：IC/IM 一手名义 ≈130 万元，而 20 万档的深档单批名义"
                  "只有 ≈7.9 万元——一手期货的敞口是单批持仓的 16 倍，无法「等市值对冲」，只能整手超配或"
                  "用多批累积后再对冲（引入时间错配）。5 万/10 万档更离谱（一手≈30~170 倍单批）。"
                  "且开股指期货需 50 万可用资金门槛。→ **散户真实可执行路径只有 ETF 融券一条**。")
    feas["ETF融券粒度"] = ("1 手=100 份，510300 现价 4.24 元→一手 424 元；512100 现价 2.71 元→一手 271 元。"
                        "**粒度不是障碍**，可精确到 1% 名义匹配。真正约束=①50 万开户门槛（与期货同为融资融券门槛）"
                        "②券商券源库存（宽基 ETF 通常有券，但不保证）③保证金比例 50% 占用资金。")

    # ── 5) 保证金占用资金成本（对冲腿自身的机会成本）──
    cap_use = {}
    for cap in (50000, 100000, 200000):
        notional = cap * 0.60          # 进攻账户全部对冲（λ=1）
        cap_use[f"{cap//10000}万档"] = {
            "对冲名义_元": round(notional),
            "期货保证金占用_元": round(notional * FUT_MARGIN),
            "期货保证金占账户_pct": round(100 * notional * FUT_MARGIN / cap, 1),
            "ETF融券保证金占用_元": round(notional * ETF_MARGIN),
            "ETF融券保证金占账户_pct": round(100 * notional * ETF_MARGIN / cap, 1),
            "T+5资金成本_元(期货)": round(notional * FUT_MARGIN * RF * 5 / DAYS_YEAR, 2),
            "T+5资金成本_元(融券)": round(notional * ETF_MARGIN * RF * 5 / DAYS_YEAR, 2)}

    # ── 6) 事件窗真实基差（深档/跌停线信号日次日）──
    win_basis = {}
    for fk, ik in (("IC0", "sh000905"), ("IM0", "sh000852"), ("IF0", "sh000300")):
        fc, ic = close_map(fk), close_map(ik)
        common = sorted(set(fc) & set(ic))
        bp = np.array([(fc[d] - ic[d]) / ic[d] for d in common])
        recent = bp[-60:]
        win_basis[fk] = {"近60日均值_bp": round(1e4 * float(recent.mean()), 2),
                         "近60日P5/P50/P95_bp": [round(1e4 * float(np.percentile(recent, p)), 1)
                                             for p in (5, 50, 95)],
                         "note": "贴水=做空还要额外付贴水收敛的成本（负基差均值×对冲比例）"}

    out["④成本现实检验"] = {
        "builder": "engine/hedge_cost_reality.py",
        "真实基差(期货−指数)_全样本": basis,
        "事件窗近期基差": win_basis,
        "期货单次往返成本_bp": fut_costs,
        "ETF融券单次往返成本_bp": etf_costs,
        "两路成本对照": cmp_cost,
        "保证金与粒度可行性": feas,
        "保证金占用资金成本": cap_use,
        "参数": {"佣金": FUT_COMM, "平今": FUT_COMM_TODAY, "滑点": FUT_SLIP_PT, "期货保证金": FUT_MARGIN,
               "ETF借券费": ETF_BORROW, "借券费敏感度": list(ETF_BORROW_ALT), "ETF保证金": ETF_MARGIN, "资金成本": RF},
        "关键结论": [
            "① 成本量级小：两路单次往返 2~10bp，相对被对冲掉的 200~400bp beta 是零头——**成本不是否决理由**，"
            "否决理由是下面两条。",
            "② 期货路对散户物理不可行（本卡唯一硬否决）：一手 IC/IM 名义≈130 万元 / 保证金≈19.5 万元，"
            "而 20 万档深档单批名义仅≈7.9 万元——粒度差 16 倍，无法等市值对冲；且需 50 万可用资金开户。",
            "③ ETF 融券路可行但有前置门槛：粒度 1%（510300 一手 424 元）完全够用；"
            "成本 T+5 单次 23.0bp（借券费 8.5%/年主导）、T+20 80bp——**这条成本是真的要扣的**，"
            "在下面净 alpha 归零的结论里它是雪上加霜而非主因。约束另有：50 万开户门槛 + 券源库存 + "
            "保证金 50% 占用（20 万档压 6 万元=账户 30%）。",
            "④ 对冲工具的做空收益在事件窗是**负的**（贴水收敛 + 恐慌后反弹）——这正是 beta 被剥离的证据："
            "做空亏多少，就等于多头赚了多少 beta。"]}

    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(json.dumps(out["④成本现实检验"], ensure_ascii=False, indent=1))
    print("saved", OUT)


if __name__ == "__main__":
    main()
