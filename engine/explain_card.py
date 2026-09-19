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
