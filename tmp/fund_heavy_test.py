"""基金重仓线测试（2026-09-27 傍晚，BACKLOG#28，类金股组合）。

公募基金季报季末+~45 天才发完 → 入场=季末+45 日（保守防前视），持一季度（~60 交易日）出。
三组对照：
  重仓组：持股市值 top100（公募抱团核心）
  加仓组：持股变动数值 top100（freshness 类比=公募在加码的票）
  减仓组：变动数值 bottom100（对照，公募在跑的票）
口径：次日开盘入（入场日后的第一个交易日），T+60 出，费 0.15%，超额 vs 沪深300。
"""
import bisect
import collections
import glob
import json
import os
import statistics as st
import sys
from datetime import date, timedelta

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

ROOT = "/opt/data/fenjue"
FEE = 0.0015
stocks = lp.load_universe()
idx = json.load(open(f"{ROOT}/data/index_sh000001.json"))
idays = [r["date"] for r in idx]
iclose = {r["date"]: r["close"] for r in idx}

def entry_day_after(qd):
    """季末日 + 45 天后的首个交易日"""
    y, m, d = int(qd[:4]), int(qd[4:6]), int(qd[6:])
    target = (date(y, m, d) + timedelta(days=45)).isoformat()
    i = bisect.bisect_left(idays, target)
    return idays[i] if i < len(idays) else None

cells = collections.defaultdict(list)
for fp in sorted(glob.glob(f"{ROOT}/data/fund_hold_cache/*.json")):
    qd = os.path.basename(fp)[:-5]
    rows = json.load(open(fp))
    ed = entry_day_after(qd)
    if not ed or ed > "2026-07-01":
        continue
    by_cap = sorted(rows, key=lambda r: -r["mktcap"])[:100]
    by_add = sorted(rows, key=lambda r: -float(r.get("add", 0) or 0))[:100] if "add" in rows[0] else None
    # 缓存里没有 add 字段（拉的时候没存）——用 funds 家数做第二维度
    by_funds = sorted(rows, key=lambda r: -r["funds"])[:100]
    for tag, group in (("重仓top100(市值)", by_cap), ("重仓top100(家数)", by_funds)):
        for r in group:
            code = r["code"]
            if code[:2] not in ("60", "00"):
                continue
            d = stocks.get(code)
            if not d:
                continue
            i = bisect.bisect_left(d["date"], ed)
            if i >= d["n"] or d["date"][i] != ed or d["o"][i] <= 0 or i + 61 >= d["n"]:
                continue
            t60 = d["c"][i + 60] / d["o"][i] - 1 - FEE
            i0 = bisect.bisect_left(idays, ed)
            ir = iclose[idays[i0 + 60]] / iclose[idays[i0]] - 1 if i0 + 60 < len(idays) else None
            if ir is not None:
                cells[tag].append((qd[:4], t60, t60 - ir))

print("═══ 基金重仓线（季末+45日入，T+60，超额 vs 300） ═══")
for tag, rows in cells.items():
    xs = [r[2] for r in rows]
    wr = sum(1 for x in xs if x > 0) / len(xs)
    print(f"  {tag}: n={len(xs)} 超额 {wr * 100:.0f}%/{st.mean(xs) * 100:+.2f}pp")
    by_y = collections.defaultdict(list)
    for y, _, ex in rows:
        by_y[y].append(ex)
    line = "    分年: "
    for y in sorted(by_y):
        ys = by_y[y]
        line += f"{y} {st.mean(ys) * 100:+.1f}pp(n{len(ys)}) "
    print(line)
