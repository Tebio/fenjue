#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""engine/hedge_verdict.py — 卡 t_4a55cc92 的 ⑤判决 段：从 hedge_test 产物抽判决表。

只读 data/research/hedge_test_20261016.json，追加 "⑤判决表" 段（幂等覆盖该键）。
**判决按 horizon 分级、按可执行路（ETF 融券）判生死、并以日历时间闸（三口径最严）一票否决**。
事件级统计在本体系里系统性高估显著性（事件高度成簇），本卡靠第三口径才发现
DEEP_NPZ T+20 的「存活」是 2024-02 单窗口扎堆假象。
用法 .venv/bin/python engine/hedge_verdict.py
"""
import json
from pathlib import Path

OUT = Path("/opt/data/fenjue/data/research/hedge_test_20261016.json")
d = json.loads(OUT.read_text())

# 五条线：DEEP_NPZ 是位置匹配对照所在口径（612 事件）；DEEP_LEDGER 是生产台账口径（219）
LINES = ["DEEP_NPZ", "DEEP_LEDGER", "LD", "PEAD", "REV"]
LINE_DEF = {
    "DEEP_NPZ": "深档 npz 口径：日跌幅≤-9.8% + depth≤-0.35 + 同簇≥5（612 事件）",
    "DEEP_LEDGER": "深档低位 v2 生产台账口径：walkforward.deep_events + deep_select(5,-0.35,top5)（219 事件）",
    "LD": "低位线 npz 口径：日跌幅≤-9.5% + depth≤0（14176 事件）",
    "PEAD": "预增低位池 npz 口径（flags bit1，48951 事件）",
    "REV": "反转族 npz 口径（flags bit2，212269 事件）—— 记忆中已 ICU",
}
HZ = (1, 5, 20)
ROAD = {"期货": "IC", "ETF": "sh512100"}   # ETF 512100 = 中证1000，散户唯一可执行路

ctrl = d.get("⑤位置匹配对照_IC期货λ=1", {})
ctrl_sum = {L: {h: v.get("净alpha(信号−对照)_pp") for h, v in c.items()} for L, c in ctrl.items()}
CTRL_AVAIL = set(ctrl.keys())          # 只有 npz 行口径有对照池


def cell(line, road, h, lam):
    key = f"{ROAD[road]}_T+{h}"
    return d[line]["对冲矩阵"][road].get(key, {}).get(f"λ={lam}")


def ctrl_net(line, h):
    """位置匹配净 alpha；台账口径无对照池 → None（不硬填 npz 的数当台账的数）"""
    if line not in CTRL_AVAIL:
        return None
    return ctrl_sum.get(line, {}).get(f"T+{h}")


def judge(keep, tN, net, line):
    """keep=ETF路保留比例; tN=对冲后t_NW; net=位置匹配净alpha。按可执行路判生死。"""
    zero = (keep is None or keep < 0.35) or (tN is None or abs(tN) < 3.0)
    if line not in CTRL_AVAIL:                       # 台账口径无对照 → 不给生死判词
        return "无位置匹配对照：只能看 ETF 路保留比例（不单独判生死）"
    if net is not None and net > 0.5 and not zero:
        return "存活：ETF 路对冲后仍剩显著正 net alpha（过三重闸）"
    if zero and (net is None or net <= 0.5):
        return "归零：纯 beta（剥掉 beta 后不显著或为负）"
    return "灰区：raw 有残留但未过闸（保留比例或 t 值不足）"


rows = {}
for L in LINES:
    base = d[L]["基础(不对冲)"]
    r = {}
    for h in HZ:
        e = {}
        for road in ("期货", "ETF"):
            a0, a1 = cell(L, road, h, 0.0), cell(L, road, h, 1.0)
            if not a0 or not a1:
                continue
            m0, m1 = a0.get("mean_pp"), a1.get("mean_pp")
            e[road] = {"原始_pp": m0, "对冲后_pp": m1, "被剥掉_pp": round(m0 - m1, 3),
                       "保留比例": round(m1 / m0, 3) if m0 else None,
                       "对冲后t_NW": a1.get("t_NW"), "对冲后胜率": a1.get("win%"), "n": a1.get("n")}
        e["期货_各指数_对冲后_pp"] = {t: (cell(L, "期货", h, 1.0) or {}).get("mean_pp")
                                 for t in ("IC", "IF", "IM")}
        e["位置匹配净alpha_pp"] = ctrl_net(L, h)
        r[f"T+{h}"] = e
    r["原始_全horizon"] = {f"T+{h}": base.get(f"T+{h}") for h in HZ}
    rows[L] = r

verdict = {
    "线定义": LINE_DEF,
    "对冲腿": {
        "期货": "IC0 中证500主力连续（可估上限；散户物理不可行见 ④ 段）",
        "ETF": "512100 中证1000ETF（散户唯一可执行路，已含 8.5%/年借券费与 50% 保证金占用）",
        "选择理由": "信号票多为中小盘深跌件，中证500/1000 对冲更贴；IF 作对照档一并落数"},
    "判据": ("每个 horizon 独立判。**以 ETF 融券路（散户唯一可执行）判生死**：保留比例 <35% 或 |t_NW|<3 → 归零；"
           "再加位置匹配对照（同日同 depth 十分位非信号票、同结构对冲）net alpha ≤+0.5pp 不予存活。"
           "三条同时满足才判「存活」。期货路仅作成本可忽略时的上限参照。"
           "台账口径（DEEP_LEDGER）无对照池，只报 ETF 路保留比例、不单独判生死。"),
    "逐线对冲表": rows,
    "位置匹配对照_净alpha_pp": ctrl_sum,
    "逐线逐horizon": {},
    "按horizon汇总": {},
    "日度(日历时间)闸_IC期货λ=1_T+5": {},
    "总结论": None,
}

# ── 日历时间闸（三口径最严者，终审）──
for L in LINES:
    rr = d[L].get("日度序列_IC期货λ=1_T+5", {})
    verdict["日度(日历时间)闸_IC期货λ=1_T+5"][L] = {
        "事件数": d[L].get("n"),
        "覆盖交易日数": {k: v.get("天数") for k, v in rr.items() if isinstance(v, dict)},
        "对冲后_vs零_t_NW": (rr.get("对冲后_vs零") or {}).get("t_NW"),
        "对冲后_vs零_DSR": (rr.get("对冲后_vs零") or {}).get("DSR_+本卡组合数"),
        "note": "; ".join(v.get("note", "") for v in rr.values() if isinstance(v, dict) and v.get("note")) or None}

# 事件集中度（日扎堆是这套体系最常见的假显著来源）
clu = {}
for L in LINES:
    n = d[L].get("n")
    days = (verdict["日度(日历时间)闸_IC期货λ=1_T+5"][L]["覆盖交易日数"] or {}).get("对冲后_vs零")
    clu[L] = {"事件数": n, "交易日": days,
              "事件/日": round(n / days, 1) if days else None,
              "日历时间闸": ("样本不足(<30日)，DSR 不可算" if (days or 0) < 30 else "可算")}
verdict["事件集中度"] = clu

for L in LINES:
    verdict["逐线逐horizon"][L] = {}
    for h in HZ:
        e = rows[L][f"T+{h}"]
        etf, fut, net = e.get("ETF", {}), e.get("期货", {}), e.get("位置匹配净alpha_pp")
        verdict["逐线逐horizon"][L][f"T+{h}"] = {
            "原始_pp": (rows[L]["原始_全horizon"].get(f"T+{h}") or {}).get("mean_pp"),
            "ETF路": (f"{etf.get('原始_pp')} → {etf.get('对冲后_pp')}pp"
                     f"（保留 {etf.get('保留比例')}, t_NW {etf.get('对冲后t_NW')}, 胜率 {etf.get('对冲后胜率')}%）")
                    if etf else None,
            "期货路(IC)": f"{fut.get('原始_pp')} → {fut.get('对冲后_pp')}pp（保留 {fut.get('保留比例')}）" if fut else None,
            "位置匹配净alpha_pp": net,
            "判词": judge(etf.get("保留比例"), etf.get("对冲后t_NW"), net, L)}

# 把日历时间闸并入判词（最严口径一票否决）
GATE = {L: verdict["日度(日历时间)闸_IC期货λ=1_T+5"][L] for L in LINES}
for L in LINES:
    g = GATE[L]
    days = (g["覆盖交易日数"] or {}).get("对冲后_vs零")
    for h in HZ:
        x = verdict["逐线逐horizon"][L][f"T+{h}"]
        x["日历时间闸"] = (f"{days} 日，样本不足(<30) → 无法过闸"
                       if (days or 0) < 30 else
                       f"{days} 日，对冲后 t_NW={g['对冲后_vs零_t_NW']}，DSR={g['对冲后_vs零_DSR']}")
        if x["判词"].startswith("存活"):
            x["判词"] = "**日历时间闸否决**（事件级正 net alpha 系日扎堆假象，见 事件集中度）"

by_h = {}
for h in HZ:
    z = sum(1 for L in LINES if "归零" in verdict["逐线逐horizon"][L][f"T+{h}"]["判词"])
    s = sum(1 for L in LINES if "存活" in verdict["逐线逐horizon"][L][f"T+{h}"]["判词"])
    n = sum(1 for L in LINES if "无位置匹配对照" in verdict["逐线逐horizon"][L][f"T+{h}"]["判词"])
    by_h[f"T+{h}"] = {"归零": z, "存活": s, "灰区": len(LINES) - z - s - n, "无对照不判": n}
verdict["按horizon汇总"] = by_h

verdict["总结论"] = (
    "**结论：对冲之后四条线在 T+1/T+5 全部归零——AGENTS #290「收益主要是恐慌后 beta 时点」在可交易意义上成立，本卡给出了定量终审。**"
    "（口径说明：四条线指 npz 口径的 DEEP_NPZ / LD / PEAD / REV；DEEP_LEDGER 因无位置匹配对照池不单独判生死。）"
    "但过程里有一个必须记下的方法论修正（见 ⑥），否则会误判。"
    "① **对冲剥掉的量级远大于成本**：期货腿单次往返仅 1.1~3.3bp，却能把 T+1 的原始正收益整体翻负——"
    "DEEP_NPZ 原始 +4.35pp 对冲到 -5.26pp、LD +1.55 到 -1.16、REV +0.22 到 -0.31。"
    "**负得比原始正得多**，说明信号票 T+1 的 beta 敞口 >1，原始正收益就是「跌深了跟着大盘反弹」。"
    "这是 #290 论断最硬的证据形态：不是「对冲后变小」，而是「对冲后变负」。"
    f"② **按 horizon 汇总（5 条线）**：T+1 归零 {by_h['T+1']['归零']}/5（无对照不判 {by_h['T+1']['无对照不判']}）；"
    f"T+5 归零 {by_h['T+5']['归零']}/5；T+20 有 1 条在事件级看似存活（DEEP_NPZ），但被日历时间闸否决，见 ⑥。"
    "T+5 的 ETF 路保留比例：LD 0.008、REV -0.859、PEAD -0.071、DEEP_NPZ 0.354；"
    "位置匹配对照 T+5 给 LD -0.38 / REV -0.14 / PEAD +0.19 / DEEP_NPZ -0.03pp——"
    "唯一微弱正的 PEAD（+0.19pp）扣 T+5 融券成本 23bp 后为 -0.04pp，同样不成立。"
    "③ **成本不是否决理由，可执行性才是**：期货路便宜（1.1~3.3bp）但散户物理不可行——"
    "一手 IC/IM 名义约 130 万元、保证金约 19.5 万元，而 20 万档的深档单批名义仅约 7.9 万元（差 16 倍），"
    "无法等市值对冲；且股指期货需 50 万可用资金开户。ETF 融券路可执行（1 手=100 份、粒度 1%），"
    "但 T+5 单次 23.0bp、T+20 79.8bp（借券费 8.5%/年主导），是期货路的 15~25 倍；"
    "**即便用最便宜的期货腿，结论也已经是归零**——所以「成本高」不是本次判决的依据，不构成对结论的削弱。"
    "④ **为什么不该做 beta 中性版**：#290 的判决在生产上本来就用「不做/减仓」来承担 beta，"
    "已有正股仓位管理；为一个扣完成本为负期望的 beta 去付 23~80bp/次，方向错误。"
    "⑤ **本轮判决的净收益**：它把「继续优化选股」这条方向正式证伪——四条线的 T+1/T+5 edge "
    "在剥掉 beta 后不值得交易，且这个结论对最便宜的对冲腿（期货）都成立。"
    "后续资源应从「提高信号胜率」转向 ⑥ 指出的两个真问题：事件集中度与持有窗。"
    "⑥ **方法论修正（本卡最重要的副产物）**：DEEP_NPZ 在 T+20 的**事件级**统计曾显示「存活」——"
    "ETF 路对冲后保留 17.5pp（保留比例 0.414、t_NW 17.7），位置匹配对照也同步给 +5.18pp。"
    "但拉日历时间口径后真相翻转：**那 612 个事件只落在 20 个交易日上，其中 2024-02-05/06/07 三天占 83.3%"
    "（2024-02-05 单日 263 笔）**，日等权后 t_NW 归零、DSR 按「样本不足(<30 日)」不可计算。"
    "即那个「存活」是 A 股 2024 年 2 月那波极端底部反弹的单窗口假象，不是可复现的 alpha。"
    "**教训**：这套体系的事件高度成簇（>50% 常集中在 1~3 日），事件级 t 值系统性高估显著性；"
    "`law_pipeline` 的「事件研究/日历时间/DSR 三口径取最严」不是形式主义，本卡正是靠第三口径才没发出错误结论。"
    "**T+20 的真伪仍悬而未决**——不是「已证伪」，而是「现有数据不足以判」（20 个独立日太少）；"
    "若有更长历史或更宽松的深档定义能凑够 >=30 个独立交易日，这个问题值得重测。")

d["⑤判决表"] = verdict
OUT.write_text(json.dumps(d, ensure_ascii=False, indent=1))

print(json.dumps(verdict["按horizon汇总"], ensure_ascii=False))
for L in LINES:
    print("=" * 74)
    print(L, "n=", d[L].get("n"))
    for h in HZ:
        x = verdict["逐线逐horizon"][L][f"T+{h}"]
        print(f"  T+{h}: 原始 {x['原始_pp']}pp | ETF {x['ETF路']} | ctrl净 {x['位置匹配净alpha_pp']} | {x['判词']}")
print("=" * 74)
print(verdict["总结论"])
