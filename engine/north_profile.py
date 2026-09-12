#!/usr/bin/env python3
"""engine/north_profile.py — 北向偏好画像（轨二，2026-09-12）

背景：北向实时流向 2024-08 停止披露；东财 RPT_MUTUAL_HOLD_DET 逐股北向持仓
止于 2024-09-30（实测）。**唯一活口 = 季报十大流通股东里的「香港中央结算有限公司」**
（北向总账户），东财 F10 RPT_F10_EH_FREEHOLDERS 更新至最新季报（2026中报实测）。
流程：
  1. 全主板逐股拉最新 2 季十大流通股东（缓存 data/north_holders/<code>.json，幂等续跑）
  2. 提取港结算行：HOLD_RATIO、HOLD_NUM_CHANGE（增持/减持/新进/不变）、环比
  3. 聚合画像：覆盖率、增持/减持分布、行业分布、市值特征
     → data/north_profile_20260912.json
限速 0.25s/请求。失败记 failed 列表，下次重跑自动补。
"""
import json, subprocess, time, sys
from collections import defaultdict
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
CACHE = ROOT / "data/north_holders"
CACHE.mkdir(exist_ok=True)
URL = ("https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_F10_EH_FREEHOLDERS"
       "&columns=SECUCODE,END_DATE,HOLDER_NAME,HOLD_NUM,HOLD_RATIO,HOLD_NUM_CHANGE,HOLDER_RANK"
       "&sortColumns=END_DATE,HOLDER_RANK&sortTypes=-1,1&pageSize=25&pageNumber=1&source=WEB&client=WEB")
NORTH = "香港中央结算"


def secucode(code):
    return f"{code}.SH" if code.startswith("6") else f"{code}.SZ"


def fetch(code):
    f = CACHE / f"{code}.json"
    if f.exists():
        return json.loads(f.read_text())
    full = f"{URL}&filter=(SECUCODE%3D%22{secucode(code)}%22)"
    r = subprocess.run(["curl", "-sL", "--max-time", "20", full],
                       capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"})
    try:
        j = json.loads(r.stdout)
        rows = (j.get("result") or {}).get("data") or []
    except Exception:
        rows = None
    if rows is None:
        return None
    f.write_text(json.dumps(rows, ensure_ascii=False))
    return rows


def move_class(ch):
    """HOLD_NUM_CHANGE 既可能是标签（增持/减持/新进/不变）也可能是股数（自抓 B-N1）。"""
    if ch is None:
        return "flat"
    s = str(ch)
    if "新进" in s or "增持" in s:
        return "inc"
    if "减持" in s:
        return "dec"
    try:
        v = float(s)
        return "inc" if v > 0 else "dec" if v < 0 else "flat"
    except ValueError:
        return "flat"


def main():
    codes = sorted(p.stem for p in (ROOT/"data/big_kcache").glob("*.json"))
    delisted = set(json.loads((ROOT/"data/delisted_codes.json").read_text())) if (ROOT/"data/delisted_codes.json").exists() else set()
    codes = [c for c in codes if c not in delisted]
    print(f"universe={len(codes)}", flush=True)
    failed = []
    for k, code in enumerate(codes):
        cached = (CACHE / f"{code}.json").exists()
        if fetch(code) is None:
            failed.append(code)
        if k % 200 == 0:
            print(f"progress {k}/{len(codes)} failed={len(failed)}", flush=True)
        if not cached:
            time.sleep(0.25)
    # 聚合
    ind = json.loads((ROOT/"data/industry_map.json").read_text())
    stocks, no_north = [], 0
    for code in codes:
        f = CACHE / f"{code}.json"
        if not f.exists():
            continue
        rows = json.loads(f.read_text())
        # 精确匹配北向总账户；排除「香港中央结算(代理人)」(=H股 nominee，非北向，2026-09-12 自抓)
        north = [r for r in rows if (r.get("HOLDER_NAME") or "") == "香港中央结算有限公司"]
        if not north:
            no_north += 1
            continue
        latest = north[0]
        prev = next((r for r in north[1:] if r["END_DATE"] < latest["END_DATE"]), None)
        stocks.append({
            "code": code, "end": latest["END_DATE"][:10],
            "ratio": latest.get("HOLD_RATIO"),
            "change": latest.get("HOLD_NUM_CHANGE"),
            "move": move_class(latest.get("HOLD_NUM_CHANGE")),
            "prev_ratio": prev.get("HOLD_RATIO") if prev else None,
            "industry": ind.get(code, {}).get("industry") or "?",
        })
    inc = [s for s in stocks if s["move"] == "inc"]
    dec = [s for s in stocks if s["move"] == "dec"]
    by_ind_inc = defaultdict(int)
    for s in inc:
        by_ind_inc[s["industry"]] += 1
    by_ind_all = defaultdict(int)
    for s in stocks:
        by_ind_all[s["industry"]] += 1
    out = {
        "meta": {"built": "2026-09-12", "source": "东财F10十大流通股东-香港中央结算",
                 "note": "北向逐股持仓2024-09后停披露，此为季报分辨率代理"},
        "coverage": {"with_north": len(stocks), "without": no_north, "failed": failed},
        "latest_quarter": max((s["end"] for s in stocks), default=None),
        "moves": {"增持+新进": len(inc), "减持": len(dec),
                  "不变/其他": len(stocks) - len(inc) - len(dec)},
        "top_ratio": sorted(stocks, key=lambda s: -(s["ratio"] or 0))[:30],
        "top_increase_industries": sorted(by_ind_inc.items(), key=lambda x: -x[1])[:15],
        "coverage_by_industry": sorted(by_ind_all.items(), key=lambda x: -x[1])[:15],
        "increase_stocks": sorted(inc, key=lambda s: s["code"]),
        "decrease_stocks": sorted(dec, key=lambda s: s["code"]),
    }
    (ROOT/"data/north_profile_20260912.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(json.dumps({k: out[k] for k in ("coverage", "latest_quarter", "moves")}, ensure_ascii=False))
    print("增持行业Top:", out["top_increase_industries"][:8])
    print("SAVED data/north_profile_20260912.json")


if __name__ == "__main__":
    main()
