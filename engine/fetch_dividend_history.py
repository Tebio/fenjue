#!/usr/bin/env python3
"""engine/fetch_dividend_history.py — 全主板分红历史拉取 (2026-09-06)

销 AGENTS.md 欠账 #6 的数据底座：中证红利宇宙是当期名单（存活者偏差）。
拉全主板每只股票的分红明细（除权除息日 + 派息/10股），存
data/dividend_history.json {code: [[ex_date, dps_per_share], ...]}。
之后用「时点 TTM 股息率」重建历史宇宙，彻底绕开指数名单。
断点续跑；akshare 东财 datacenter 接口（容器实测可用）。
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "/opt/data/python-libs")

ROOT = Path("/opt/data/fenjue")
KC = ROOT / "data" / "big_kcache"
OUT = ROOT / "data" / "dividend_history.json"


def main() -> None:
    import akshare as ak
    done = json.loads(OUT.read_text()) if OUT.exists() else {}
    codes = [f.stem for f in sorted(KC.glob("*.json")) if f.stem != "000001"]
    todo = [c for c in codes if c not in done]
    print(f"已有 {len(done)}，待拉 {len(todo)}", flush=True)
    t0 = time.time()
    fails = 0
    failed: list[str] = []
    for i, code in enumerate(todo):
        for attempt in range(2):
            try:
                df = ak.stock_history_dividend_detail(symbol=code, indicator="分红")
                rows = []
                for _, r in df.iterrows():
                    ex = str(r.get("除权除息日", ""))[:10]
                    pay = r.get("派息", 0)
                    try:
                        pay = float(pay)
                    except (TypeError, ValueError):
                        pay = 0.0
                    if ex and ex != "NaT" and pay > 0:
                        rows.append([ex, round(pay / 10.0, 4)])  # 派息/10股 → 每股
                done[code] = rows
                break
            except Exception as e:
                if attempt == 0:
                    time.sleep(5)
                else:
                    fails += 1
                    # 失败 ≠ 无分红：不写入 done（断点续跑会重试），单独记失败队列
                    # （2026-09-06 外部审查发现#2修复：旧版写 done[code]=[] 永久标记无分红）
                    failed.append(code)
                    print(f"{code} 两次失败 {str(e)[:60]}", flush=True)
        time.sleep(0.4)
        if i % 100 == 99:
            OUT.write_text(json.dumps(done, ensure_ascii=False))
            print(f"  {i+1}/{len(todo)} {(time.time()-t0)/60:.0f}min 失败{fails}", flush=True)
    OUT.write_text(json.dumps(done, ensure_ascii=False))
    if failed:
        (ROOT / "data" / "dividend_failed.json").write_text(json.dumps(failed))
    ndiv = sum(1 for v in done.values() if v)
    print(f"完成 {(time.time()-t0)/60:.0f}min 失败{fails} 有分红记录 {ndiv}/{len(done)}", flush=True)


if __name__ == "__main__":
    main()
