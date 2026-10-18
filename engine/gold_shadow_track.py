#!/usr/bin/env python3
"""金股影子记账：把出票榜按「建仓参考价」入账，逐日结 T+1/T+5/T+20（看门狗式输出）。

为什么要有它：官方入场日（月第 6 交易日）过了才发现名单=不能追；但排名对不对可以立刻用前向数据检验。
所以每期榜单以「可得收盘」记影子价（不是建议买入价），按 T+1/5/20 结算，结果进 data/gold_shadow_ledger.json。

用法：
  .venv/bin/python engine/gold_shadow_track.py --init   # 用 gold_rank_<date>.json 建/补当期 cohort
  .venv/bin/python engine/gold_shadow_track.py          # 每日结算，仅在有结算或到期时打印（cron 用）
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, "/opt/data/fenjue/engine")
sys.path.insert(0, "/opt/data/python-libs")
import law_pipeline as lp
import trade_calendar as tc

ROOT = Path("/opt/data/fenjue")
LEDGER = ROOT / "data/gold_shadow_ledger.json"
FEE = 0.0015
HOLDS = (1, 5, 20)


def load_ledger():
    if LEDGER.exists():
        return json.loads(LEDGER.read_text())
    return {"cohorts": []}


def save(led):
    LEDGER.write_text(json.dumps(led, ensure_ascii=False, indent=1))


def init_from_rank(rank_path: Path, U):
    led = load_ledger()
    rk = json.loads(rank_path.read_text())
    month = rk["entry_day"][:7]
    basis = None
    items = []
    for r in rk["rows"]:
        d = U.get(r["code"])
        if not d:
            continue
        i = d["n"] - 1
        last_day, ref = d["date"][i], d["c"][i]
        basis = last_day if basis is None or last_day > basis else basis
        items.append({"code": r["code"], "name": r["name"], "rank": len(items) + 1,
                      "expect_t20": round(r["expect"], 4), "knn_r20": round(r["knn_r20"], 4),
                      "dhigh60": None if r["dhigh60"] is None else round(r["dhigh60"], 4),
                      "ref_day": last_day, "ref_price": ref, "settled": {}})
    cohort = {"cohort": month, "kind": "金股独家+年内首入·排行影子",
              "official_entry_day": rk["entry_day"],
              "basis_note": f"官方入场日 {rk['entry_day']} 已过，按最近收盘 {basis} 记参考价（研究口径，非买入建议）",
              "exit_days": {}, "items": items}
    # 到期日（T+20）按官方日历推
    try:
        y = int(basis[:4])
        days = (tc.trading_days(y) or []) + (tc.trading_days(y + 1) or [])
        if basis in days:
            i = days.index(basis)
            for h in HOLDS:
                cohort["exit_days"][str(h)] = days[i + h] if i + h < len(days) else None
    except Exception:
        pass
    led["cohorts"] = [c for c in led["cohorts"] if c["cohort"] != month] + [cohort]
    save(led)
    print(f"cohort {month} 建账 {len(items)} 只，参考日 {basis}，T+20 到期 {cohort['exit_days'].get('20')}")
    return led


def settle(U):
    led = load_ledger()
    out = []
    for c in led["cohorts"]:
        for it in c["items"]:
            d = U.get(it["code"])
            if not d or it["ref_day"] not in d["date"]:
                continue
            i0 = d["date"].index(it["ref_day"])
            for h in HOLDS:
                k = str(h)
                if k in it["settled"] or i0 + h >= d["n"]:
                    continue
                r = d["c"][i0 + h] / it["ref_price"] - 1 - FEE
                it["settled"][k] = {"day": d["date"][i0 + h], "r": round(r, 4)}
                out.append(f"{c['cohort']} {it['name']}({it['code']}) ≥T+{h} {d['date'][i0 + h]} r={r*100:+.2f}% 期望{it['expect_t20']*100:+.1f}%")
    save(led)
    # 汇总（每期 T+20 全结或未结都报一行进度）
    lines = []
    for c in led["cohorts"]:
        for h in HOLDS:
            xs = [it["settled"][str(h)]["r"] for it in c["items"] if str(h) in it["settled"]]
            if len(xs) == len(c["items"]) and len(xs) >= 5:
                win = sum(1 for x in xs if x > 0) / len(xs)
                lines.append(f"{c['cohort']} T+{h} 全结 n={len(xs)} 胜率{win*100:.1f}% 均值{sum(xs)/len(xs)*100:+.2f}%")
    if out or lines:
        print("\n".join(lines + out))
    return len(out)


if __name__ == "__main__":
    U = lp.load_universe()
    if "--init" in sys.argv:
        cand = sorted(ROOT.glob("data/gold_rank_*.json"))
        if not cand:
            print("没有 gold_rank_*.json，先跑 engine/gold_rank.py")
            sys.exit(1)
        init_from_rank(cand[-1], U)
    n = settle(U)
    sys.exit(0)
