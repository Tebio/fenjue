"""券商金股回测（2026-09-26 凌晨，BACKLOG#14，iwencai hithink-insresearch-query 通道）。

①按月拉金股名单（2020-01~2026-09，缓存 data/gold_stock_cache/<YYYY-MM>.json，翻页 limit=50）
②事件研究：公告月首个交易日次日开盘入（近似：金股多在月初发布），T+5/20/60 收盘出，费 0.15%
③对照：同期全市场等权收益（同窗口）
④分层：分年/regime/是否重复入选（连续多月金股=机构抱团）
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
CACHE = ROOT / "data" / "gold_stock_cache"
CACHE.mkdir(exist_ok=True)
CLI = ROOT.parent / ".iwencai-skillhub/skills/hithink-insresearch-query/scripts/cli.py"

# ① 拉名单
months = []
y, m = 2020, 1
while (y, m) <= (2026, 9):
    months.append(f"{y}-{m:02d}")
    m += 1
    if m == 13:
        y, m = y + 1, 1

env = dict(os.environ)
for line in Path("/opt/data/.env").read_text().splitlines():
    if line.startswith("IWENCAI"):
        k, v = line.split("=", 1)
        env[k] = v

def fetch_month(mo):
    fp = CACHE / f"{mo}.json"
    if fp.exists():
        return json.loads(fp.read_text())
    y, m = mo.split("-")
    out, page = [], 1
    while True:
        r = subprocess.run(
            ["python3", str(CLI), "--query", f"{y}年{int(m)}月 券商金股", "--page", str(page), "--limit", "50"],
            capture_output=True, text=True, env=env, timeout=60)
        try:
            d = json.loads(r.stdout)
        except Exception:
            break
        rows = d.get("datas") or []
        for row in rows:
            code = str(row.get("股票代码") or "").split(".")[0].zfill(6)
            if code[:2] in ("60", "00"):
                out.append({"code": code, "name": row.get("股票简称", "")})
        if not d.get("has_more") or not rows:
            break
        page += 1
        if page > 12:
            break
        time.sleep(2.5)
    fp.write_text(json.dumps(out, ensure_ascii=False))
    return out

all_picks = {}
for k, mo in enumerate(months):
    rows = fetch_month(mo)
    if rows:
        all_picks[mo] = rows
    if k % 12 == 0:
        print(f"进度 {mo}，累计 {sum(len(v) for v in all_picks.values())} 条", flush=True)
    time.sleep(3.0)
print(f"金股总记录 {sum(len(v) for v in all_picks.values())} 条，覆盖 {len(all_picks)} 个月", flush=True)
json.dump(all_picks, open(ROOT / "data/gold_stock_picks_20260926.json", "w"), ensure_ascii=False)

# ② 事件研究
sys.path.insert(0, str(ROOT / "engine"))
import law_pipeline as lp
import statistics as st
import collections
import bisect

stocks = lp.load_universe()
idx_data = json.loads(open(ROOT / "data/index_sh000001.json").read())
cal = [k["date"] for k in idx_data]
idx_map = {k["date"]: float(k["close"]) for k in idx_data}
FEE = 0.0015

events = []
for mo, rows in all_picks.items():
    first_td = next((d for d in cal if d[:7] == mo), None)
    if not first_td:
        continue
    i0 = cal.index(first_td)
    if i0 + 61 >= len(cal):
        continue
    for r in rows:
        d = stocks.get(r["code"])
        if not d or first_td not in d["date"]:
            continue
        i = d["date"].index(first_td)
        if i + 61 >= d["n"] or d["o"][i + 1] <= 0:
            continue
        entry = d["o"][i + 1]
        events.append({"mo": mo, "code": r["code"],
                       "t5": d["c"][i + 5] / entry - 1 - FEE,
                       "t20": d["c"][i + 20] / entry - 1 - FEE,
                       "t60": d["c"][i + 60] / entry - 1 - FEE,
                       "i0": i0})
# 对照：同月全市场等权
for e in events:
    i0 = e["i0"]
    e["mkt20"] = idx_map[cal[i0 + 21]] / idx_map[cal[i0 + 1]] - 1 if i0 + 21 < len(cal) else None

print(f"\n可计算事件 {len(events)}")
def blk(rows, lb):
    if len(rows) < 20:
        return
    line = f"{lb:<16} n={len(rows):>5}"
    for h in ("t5", "t20", "t60"):
        xs = [r[h] for r in rows]
        wr = sum(1 for x in xs if x > 0) / len(xs)
        line += f" | {h.upper()} {wr * 100:5.1f}%/{st.mean(xs) * 100:+5.2f}%"
    xs = [r["t20"] - r["mkt20"] for r in rows if r["mkt20"] is not None]
    line += f" | T20超额 {st.mean(xs) * 100:+.2f}%"
    print(line)

blk(events, "全部金股")
for y in ("2020", "2021", "2022", "2023", "2024", "2025", "2026"):
    blk([e for e in events if e["mo"][:4] == y], f"{y}年")
# 重复入选（连续 2 月以上入选=抱团）
cnt = collections.Counter(e["code"] for e in events)
blk([e for e in events if cnt[e["code"]] >= 3], "年内入选≥3次(抱团)")
blk([e for e in events if cnt[e["code"]] == 1], "仅入选1次")
