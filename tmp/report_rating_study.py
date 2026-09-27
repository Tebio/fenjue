"""券商研报评级事件研究（2026-09-27 深夜，金股最近亲，东财 reportapi 免费无配额）。

拉 2021-01→2026-05 全量个股研报（约 6-7 万份），按评级数值比对分出：
  首次覆盖（无上次评级）/ 评级上调（emRatingValue > last）/ 下调 / 维持
  目标价空间档（目标价上限/发布日收盘 - 1：>30% / 10-30% / <10%）
前向 T+20/60 超额 vs 沪深300（次日开盘入，费0.15%）。
"""
import bisect
import collections
import json
import statistics as st
import sys
import time
import urllib.request

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

from pathlib import Path

ROOT = "/opt/data/fenjue"
FEE = 0.0015
UA = {"User-Agent": "Mozilla/5.0"}

# ── 拉取（断点续传） ──
CACHE = Path(ROOT) / "data/research_reports_20260927.json"
rows = []
if CACHE.exists():
    rows = json.loads(CACHE.read_text())
    print(f"缓存已有 {len(rows)} 条", flush=True)
months = []
for y in range(2021, 2027):
    for m in range(1, 13):
        mo = f"{y}-{m:02d}"
        if "2021-01" <= mo <= "2026-05":
            months.append(mo)
done_months = {r["_mo"] for r in rows}
for mo in months:
    if mo in done_months:
        continue
    y, m = mo.split("-")
    import calendar
    last_d = calendar.monthrange(int(y), int(m))[1]
    rng = f"beginTime={y}-{m}-01&endTime={y}-{m}-{last_d}"
    page = 1
    got = 0
    while True:
        url = f"https://reportapi.eastmoney.com/report/list?industryCode=*&pageSize=100&pageNo={page}&qType=0&{rng}"
        try:
            req = urllib.request.Request(url, headers=UA)
            d = json.loads(urllib.request.urlopen(req, timeout=20).read())
        except Exception as e:
            print(f"{mo} p{page} 网络错误 {e}，重试", flush=True)
            time.sleep(5)
            continue
        batch = d.get("data") or []
        for r in batch:
            r["_mo"] = mo
        rows.extend(batch)
        got += len(batch)
        if len(batch) < 100 or page >= d.get("TotalPage", 1):
            break
        page += 1
        time.sleep(0.9)
    print(f"{mo}: {got} 条（累计 {len(rows)}）", flush=True)
    CACHE.write_text(json.dumps(rows, ensure_ascii=False))
    time.sleep(1.0)
print(f"研报总量 {len(rows)}", flush=True)

# ── 事件研究 ──
stocks = lp.load_universe()
idx = json.load(open(f"{ROOT}/data/index_sh000001.json"))
idays = [r["date"] for r in idx]
iclose = {r["date"]: r["close"] for r in idx}
cells = collections.defaultdict(list)
n_used = 0
for r in rows:
    code = str(r.get("stockCode") or "").zfill(6)
    if code[:2] not in ("60", "00"):
        continue
    pub = str(r.get("publishDate") or "")[:10]
    d = stocks.get(code)
    if not d:
        continue
    i = bisect.bisect_left(d["date"], pub)
    if i >= d["n"] - 61:
        continue
    if d["o"][i + 1] <= 0:
        continue
    # 评级事件分类
    def rv(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return None
    cur, last = rv(r.get("emRatingValue")), rv(r.get("lastEmRatingValue"))
    if cur is None:
        continue
    if last is None:
        kind = "首次覆盖"
    elif cur > last:
        kind = "评级上调"
    elif cur < last:
        kind = "评级下调"
    else:
        kind = "维持"
    # 目标价空间
    aim = rv(r.get("indvAimPriceT"))
    px0 = d["c"][i]
    aim_gap = (aim / px0 - 1) if aim and px0 > 0 else None
    i0 = bisect.bisect_left(idays, d["date"][i + 1])
    if i0 + 61 >= len(idays):
        continue
    n_used += 1
    for h in (20, 60):
        t = d["c"][i + 1 + h] / d["o"][i + 1] - 1 - FEE
        ir = iclose[idays[i0 + h]] / iclose[idays[i0]] - 1
        cells[(kind, h)].append(t - ir)
        if aim_gap is not None:
            ag = "空间>30%" if aim_gap > 0.3 else ("10-30%" if aim_gap > 0.1 else "<10%")
            cells[(f"目标价{ag}", h)].append(t - ir)
print(f"可用事件 {n_used}")
print("═══ 评级事件 × 目标价空间（超额 vs 300） ═══")
for kind in ("首次覆盖", "评级上调", "维持", "评级下调", "目标价空间>30%", "目标价10-30%", "目标价<10%"):
    row = f"  {kind:<12}"
    for h in (20, 60):
        xs = cells.get((kind, h), [])
        if len(xs) < 50:
            row += f" | T{h} n薄({len(xs)})"
            continue
        wr = sum(1 for x in xs if x > 0) / len(xs)
        row += f" | T{h} {wr * 100:.0f}%/{st.mean(xs) * 100:+.2f}pp"
    print(row)
