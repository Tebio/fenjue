"""转债数据底座（2026-09-25）：全列表3页 + 全部日K（sina），落盘 data/cb_list.json + data/cb_klines.json。
"""
import json
import time
from pathlib import Path

import requests

ROOT = Path("/opt/data/fenjue")
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn/"}

# ① 全列表 3 页
all_rows = []
for page in (1, 2, 3):
    params = {"reportName": "RPT_BOND_CB_LIST", "columns": "ALL", "pageSize": "600",
              "pageNumber": str(page), "sortColumns": "PUBLIC_START_DATE", "sortTypes": "-1",
              "source": "WEB", "client": "WEB"}
    d = requests.get("https://datacenter-web.eastmoney.com/api/data/v1/get",
                     params=params, headers=HEADERS, timeout=20).json()
    all_rows.extend((d.get("result") or {}).get("data") or [])
    time.sleep(0.5)
json.dump(all_rows, open(ROOT / "data/cb_list.json", "w"), ensure_ascii=False)
active = [r for r in all_rows if not r.get("DELIST_DATE") and r.get("SECURITY_CODE")]
print(f"转债总数 {len(all_rows)}，未退市 {len(active)}")

# ② 日K（sina，转债代码 sh110/113/118、sz123/127/128）
def mkt(code):
    return ("sh" if code[:2] in ("11", "13") else "sz") + code

klines, fails = {}, 0
for k, r in enumerate(active):
    code = r["SECURITY_CODE"]
    try:
        resp = requests.get(
            f"https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData"
            f"?symbol={mkt(code)}&scale=240&ma=no&datalen=900",
            headers=HEADERS, timeout=10)
        rows = resp.json()
        if rows:
            klines[code] = [{"date": x["day"], "open": float(x["open"]), "close": float(x["close"]),
                             "high": float(x["high"]), "low": float(x["low"]), "volume": float(x["volume"])}
                            for x in rows]
    except Exception:
        fails += 1
    if k % 100 == 0:
        print(f"进度 {k}/{len(active)}", flush=True)
    time.sleep(0.15)
json.dump(klines, open(ROOT / "data/cb_klines.json", "w"), ensure_ascii=False)
print(f"日K 拉到 {len(klines)} 只，失败 {fails}")
