#!/usr/bin/env python3
"""金股 d7k2 择时变体影子账（2026-10-19 用户「跌几天就来买点，涨几天就跑」立项）。

背景：2026-05~09 五个月对「出票后第 d 个交易日收盘买、持 k 日卖」做全网格扫描，
**唯一 5/5 个月全正的格子是 d=7, k=2**（出票后第 7 个交易日收盘买入，第 9 个交易日收盘卖出）：
05 +0.31% / 06 +1.99% / 07 +1.64% / 08 +0.13% / 09 +1.69%，合并 +1.30%/胜 58%。
但对同窗口全市场等权的超额只有 3/5 月为正（均值 +0.89pp），且 90 格里挑 1 格≈随机期望。
→ 不进生产、不改口径，**只做前向影子**：每期金股名单按固定日历记 d7 收盘买入 / d9 收盘卖出。

用法：
  .venv/bin/python engine/gold_d7k2_shadow.py --init   # 按官方入场日推 d7/d9 并建 cohort
  .venv/bin/python engine/gold_d7k2_shadow.py          # 每日结算，仅在有结算时打印（看门狗）
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, "/opt/data/fenjue/engine")
sys.path.insert(0, "/opt/data/python-libs")
import law_pipeline as lp
import trade_calendar as tc

ROOT = Path("/opt/data/fenjue")
LEDGER = ROOT / "data/gold_d7k2_ledger.json"
FEE = 0.0015


def jload(p, d):
    return json.loads(p.read_text()) if p.exists() else d


def jdump(p, o):
    p.write_text(json.dumps(o, ensure_ascii=False, indent=1))


def tdays_after(day, n):
    """day 之后的第 n 个交易日（day 本身算第 0 天）。"""
    y = int(day[:4])
    days = (tc.trading_days(y) or []) + (tc.trading_days(y + 1) or [])
    days = [d for d in days if d > day]
    return days[n - 1] if len(days) >= n else None


def init(rank_path):
    rk = json.loads(rank_path.read_text())
    entry = rk["entry_day"]
    buy = tdays_after(entry, 7)
    sell = tdays_after(entry, 9)
    led = jload(LEDGER, {"cohorts": []})
    mo = entry[:7]
    if any(c["cohort"] == mo for c in led["cohorts"]):
        print(f"{mo} 已存在，跳过")
        return
    led["cohorts"].append({
        "cohort": mo, "kind": "金股 d7k2 择时变体（第7交易日收盘买→第9交易日收盘卖）",
        "official_entry_day": entry, "buy_day": buy, "sell_day": sell,
        "note": "网格寻优结果，5/5 月正但对全市场超额仅 3/5 月 → 只做前向检验，不进生产",
        "items": [{"code": r["code"], "name": r["name"], "rank": i + 1} for i, r in enumerate(rk["rows"])],
        "result": None})
    jdump(LEDGER, led)
    print(f"{mo} d7k2 cohort 建好：入场 {entry} → 买 {buy} 收盘 → 卖 {sell} 收盘，{len(rk['rows'])} 只")


def settle(U):
    led = jload(LEDGER, {"cohorts": []})
    out = []
    for c in led["cohorts"]:
        if c.get("result"):
            continue
        buy, sell = c["buy_day"], c["sell_day"]
        if not buy or not sell:
            continue
        rows, rows_top, miss = [], [], 0
        for it in c["items"]:
            d = U.get(it["code"])
            if not d or buy not in d["date"] or sell not in d["date"]:
                miss += 1
                continue
            jb = d["date"].index(buy)
            js = d["date"].index(sell)
            if jb >= d["n"] or js >= d["n"] or jb == 0:
                miss += 1
                continue
            r = d["c"][js] / d["c"][jb] - 1 - FEE
            rows.append(r)
            if it.get("rank_elastic") and it["rank_elastic"] <= max(1, len(c["items"]) // 3):
                rows_top.append(r)
        if not rows:
            continue
        win = sum(1 for x in rows if x > 0) / len(rows)
        c["result"] = {"n": len(rows), "miss": miss, "win": round(win, 4),
                       "mean": round(sum(rows) / len(rows), 4), "buy_day": buy, "sell_day": sell,
                       "elastic_top": {"n": len(rows_top),
                                       "mean": round(sum(rows_top) / len(rows_top), 4) if rows_top else None,
                                       "win": round(sum(1 for x in rows_top if x > 0) / len(rows_top), 4) if rows_top else None}}
        jdump(LEDGER, led)
        out.append(f"金股d7k2 {c['cohort']}：{buy}收盘买 → {sell}收盘卖，全池 n={len(rows)} "
                   f"均值 {sum(rows)/len(rows)*100:+.2f}% 胜率 {win*100:.0f}%（缺 {miss}）")
        if rows_top:
            out.append(f"   弹性top{len(rows_top)}：均值 {sum(rows_top)/len(rows_top)*100:+.2f}% "
                       f"胜率 {sum(1 for x in rows_top if x > 0)/len(rows_top)*100:.0f}%")
    return out


def main():
    U = lp.load_universe()
    if "--init" in sys.argv:
        cand = sorted(ROOT.glob("data/gold_rank_*.json"))
        if not cand:
            print("没有 gold_rank_*.json，先跑 engine/gold_rank.py")
            return
        init(cand[-1])
        return
    for line in settle(U):
        print(line)


if __name__ == "__main__":
    main()
