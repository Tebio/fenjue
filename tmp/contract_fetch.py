"""重大合同/中标公告事件研究（2026-09-22 深夜，用户问超预期策略——洛阳钼业型之外的另一条线）。

数据源：东财公告 API（2023 年数据实测可取）。拉全主板 2024-01~2026-09 公告，标题过滤
中标/合同/订单/签约类，次日开盘入场，T+1/5/10/20 收盘出，费 0.15%，含退市股。
对照：位置匹配随机（同股 MA60 下同位置随机日）。
缓存 data/ann_cache/<batch>_<year>.json 断点续跑。
"""
import json
import math
import re
import statistics as st
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

ROOT = Path("/opt/data/fenjue")
CACHE = ROOT / "data" / "ann_cache"
CACHE.mkdir(exist_ok=True)
LIST_URL = "https://np-anotice-stock.eastmoney.com/api/security/ann"
FEE = 0.0015
YEARS = ["2024", "2025", "2026"]
KW = re.compile(r"中标|签订.*合同|重大合同|订单|签约|中标候选")

codes = [str(s["code"]).zfill(6) for s in json.loads((ROOT / "data/main_board_codes.json").read_text())["stocks"]]
codes = [c for c in codes if c[:2] in ("60", "00")]
print(f"宇宙 {len(codes)}", flush=True)

sess = requests.Session()
sess.headers.update({"User-Agent": "Mozilla/5.0"})
events = []
for bi in range(0, len(codes), 40):
    batch = codes[bi:bi + 40]
    for year in YEARS:
        fp = CACHE / f"b{bi}_{year}.json"
        if fp.exists():
            events.extend(json.loads(fp.read_text()))
            continue
        rows_all = []
        page = 1
        try:
            while page <= 12:
                params = {"sr": "-1", "page_size": "100", "page_index": str(page), "ann_type": "A",
                          "client_source": "web", "f_node": "0", "s_node": "0",
                          "stock_list": ",".join(batch),
                          "begin_time": f"{year}-01-01", "end_time": f"{year}-12-31"}
                r = sess.get(LIST_URL, params=params, timeout=18)
                data = r.json().get("data") or {}
                rows = data.get("list") or []
                if not rows:
                    break
                for row in rows:
                    title = str(row.get("title") or "")
                    if not KW.search(title):
                        continue
                    nd = str(row.get("notice_date") or "")[:10]
                    row_codes = {str(cr.get("stock_code", "")).zfill(6) for cr in row.get("codes") or []}
                    for code in row_codes & set(batch):
                        rows_all.append({"code": code, "title": title, "date": nd})
                if len(rows) < 100:
                    break
                page += 1
                time.sleep(0.15)
        except Exception as e:
            print(f"batch {bi} {year} ERR {str(e)[:80]}", flush=True)
        fp.write_text(json.dumps(rows_all, ensure_ascii=False))
        events.extend(rows_all)
    if bi % 400 == 0:
        print(f"进度 {bi}/{len(codes)} 事件累计 {len(events)}", flush=True)
    time.sleep(0.3)

print(f"合同类公告事件 {len(events)}", flush=True)
json.dump(events, open(ROOT / "data/contract_events_raw_20260922.json", "w"), ensure_ascii=False)
