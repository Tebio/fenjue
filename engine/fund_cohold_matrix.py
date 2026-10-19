#!/usr/bin/env python3
"""季度基金×股票矩阵（主动偏股宇宙，份额去重，top10 重仓）。
输入: data/fund_cohold/positions/<Q>.jsonl + data/fund_cohold/fundcode_search.js
输出: data/fund_cohold/matrix/<Q>.json  {pkey: {stock: NETASSET_RATIO}}（top10）+ ledger.json 对账表
口径（写死，如实披露）:
  - 主动偏股 = 股票型 + 混合型-偏股（剔指数型-股票/灵活配置/QDII/债券）
  - 份额去重 = 规范名（去尾部单字母份额与「(后端)」）同组取持股行数最多的份额
  - top10 = 每组合按 NETASSET_RATIO 降序前 10（季报只披露前十大；中报/年报有全量明细，
    统一截断到 10 保证各季可比）
  - 幸存者偏差诚实标注: fundcode_search 为当前快照，历史已清盘基金映射不到类型 → 剔除，
    每季报 drop_unknown 行占比（即为估下界）。
用法: .venv/bin/python engine/fund_cohold_matrix.py
"""
import json, os, re
from collections import defaultdict

ROOT = "/opt/data/fenjue"
POS = f"{ROOT}/data/fund_cohold/positions"
MAT = f"{ROOT}/data/fund_cohold/matrix"
FUNDCODE = f"{ROOT}/data/fund_cohold/fundcode_search.js"
ACTIVE_TYPES = {"股票型", "混合型-偏股"}


def norm_name(name):
    n = re.sub(r"（后端）$|\(后端\)$", "", name)
    return re.sub(r"\s?[（(]?[ABCDEHIOYRZ][）)]?$", "", n)


def load_type_map():
    raw = open(FUNDCODE, encoding="utf-8-sig").read()
    funds = json.loads(re.search(r"\[\[.*\]\]", raw, re.S).group(0))
    return {f[0]: f[3] for f in funds}


def build(q, type_map):
    fp = f"{POS}/{q}.jsonl"
    if not os.path.exists(fp + ".done"):
        return None
    rows_by_code = defaultdict(list)
    n_rows = 0
    with open(fp) as f:
        for line in f:
            r = json.loads(line); n_rows += 1
            if r["nr"] is not None:
                rows_by_code[r["f"]].append(r)
    drop_unknown = drop_type = kept = 0
    groups = defaultdict(list)
    for code, rows in rows_by_code.items():
        t = type_map.get(code)
        if t is None:
            drop_unknown += len(rows); continue
        if t not in ACTIVE_TYPES:
            drop_type += len(rows); continue
        kept += len(rows)
        groups[norm_name(rows[0]["fn"] or code)].append((code, rows))
    portfolios = {}
    for pkey, lst in groups.items():
        _, rows = max(lst, key=lambda x: len(x[1]))
        rows = [r for r in rows if r["nr"] and r["nr"] > 0]
        rows.sort(key=lambda r: -r["nr"])
        portfolios[pkey] = {r["s"]: round(r["nr"], 4) for r in rows[:10]}
    stocks = {s for p in portfolios.values() for s in p}
    mb = {s for s in stocks if s[:2] in ("60", "00")}
    os.makedirs(MAT, exist_ok=True)
    json.dump(portfolios, open(f"{MAT}/{q}.json", "w"), ensure_ascii=False)
    return {"rows_raw": n_rows, "holder_codes": len(rows_by_code),
            "dropped_rows_unknown_code": drop_unknown,
            "dropped_rows_non_active_type": drop_type, "kept_rows": kept,
            "active_portfolios": len(portfolios), "distinct_stocks_top10": len(stocks),
            "mainboard_stocks_top10": len(mb),
            "drop_unknown_pct": round(drop_unknown / max(n_rows, 1), 4)}


def main():
    type_map = load_type_map()
    ledger = {}
    for fn in sorted(os.listdir(POS)):
        if not fn.endswith(".jsonl"):
            continue
        q = fn[:-6]
        r = build(q, type_map)
        if r is None:
            print(f"[WAIT] {q}", flush=True); continue
        ledger[q] = r
        print(f"[{q}] portfolios={r['active_portfolios']} 主板股票={r['mainboard_stocks_top10']} "
              f"rows={r['rows_raw']} drop_unknown={r['dropped_rows_unknown_code']} "
              f"({r['drop_unknown_pct']:.1%}) drop_type={r['dropped_rows_non_active_type']}", flush=True)
    os.makedirs(MAT, exist_ok=True)
    json.dump(ledger, open(f"{MAT}/ledger.json", "w"), ensure_ascii=False, indent=1)
    print("MATRIX_DONE", len(ledger), flush=True)


if __name__ == "__main__":
    main()
