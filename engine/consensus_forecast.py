"""同花顺机构一致预期 EPS 采集器（2026-09-23，源：a-stock-data SKILL.md 抄录+实测校准）。

直连 basic.10jqka.com.cn/new/<code>/worth.html（GBK HTML 表解析），零 key。
实测（2026-09-23 美的）：2026 年 32 机构 均值 6.19（5.44~8.27）。
用途：真·PEAD 研究（预告 vs 一致预期差→漂移）——#168 缺的「一致预期」字段。
缓存 data/consensus/<code>.json。预测机构数 <3 的票结论不可靠（skill 原注）。
"""
import json
import re
import sys
import time
from io import StringIO
from pathlib import Path

import pandas as pd
import requests

ROOT = Path("/opt/data/fenjue")
OUT = ROOT / "data" / "consensus"
OUT.mkdir(exist_ok=True)

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
           "Referer": "https://basic.10jqka.com.cn/"}


def fetch(code: str) -> list[dict]:
    code = re.sub(r"\D", "", code)[-6:]
    r = requests.get(f"https://basic.10jqka.com.cn/new/{code}/worth.html",
                     headers=HEADERS, timeout=15)
    r.encoding = "gbk"
    for df in pd.read_html(StringIO(r.text)):
        cols = [str(c) for c in df.columns]
        if any("每股收益" in c or "均值" in c for c in cols):
            out = []
            for _, row in df.iterrows():
                try:
                    out.append({"year": str(row["年度"]), "n_org": int(row["预测机构数"]),
                                "eps_min": float(row["最小值"]), "eps_avg": float(row["均值"]),
                                "eps_max": float(row["最大值"])})
                except Exception:
                    continue
            return out
    raise ValueError(f"{code} 页面无预期表（可能无机构覆盖）")


def main():
    codes = sys.argv[1:]
    if not codes:
        print("用法: consensus_forecast.py <code> [code...]")
        return
    for code in codes:
        try:
            rows = fetch(code)
            (OUT / f"{code}.json").write_text(json.dumps(
                {"code": code, "fetched": time.strftime("%Y-%m-%d"), "rows": rows}, ensure_ascii=False))
            print(f"✅ {code}: " + " | ".join(f"{r['year']} {r['n_org']}家 均值{r['eps_avg']}" for r in rows))
        except Exception as e:
            print(f"❌ {code}: {str(e)[:100]}")
        time.sleep(1.2)  # 同花顺温和限流


if __name__ == "__main__":
    main()
