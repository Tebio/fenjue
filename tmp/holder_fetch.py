"""增减持/回购公告事件研究（2026-09-26 深夜，新事件家族——公告基建复用 #168）。

三类：增持（含增持计划/增持完成）、回购（回购方案/回购进展）、减持（减持计划/减持完成）。
范围：全主板 2024-01~2026-09（东财公告 API，40只/批×3窗，缓存 data/ann_cache2/）。
事件研究：公告日次日开盘入，T+1/5/20/60，费 0.15%，含退市股；对照=同期全市场等权；
市场级：月度回购公告数 vs 指数前瞻（回购潮=底部先行指标验证）。
"""
import json
import re
import time
from pathlib import Path

import requests

ROOT = Path("/opt/data/fenjue")
CACHE = ROOT / "data" / "ann_cache2"
CACHE.mkdir(exist_ok=True)
LIST_URL = "https://np-anotice-stock.eastmoney.com/api/security/ann"
KW = {
    "增持": re.compile(r"增持"),
    "回购": re.compile(r"回购"),
    "减持": re.compile(r"减持"),
}
EXCLUDE = re.compile(r"可转债|债券|基金|质押|解除质押|回购股份注销的进展|回购报告书的修订")  # 噪声

codes = [str(s["code"]).zfill(6) for s in json.loads((ROOT / "data/main_board_codes.json").read_text())["stocks"]]
codes = [c for c in codes if c[:2] in ("60", "00")]
sess = requests.Session()
sess.headers.update({"User-Agent": "Mozilla/5.0"})

events = []
for bi in range(0, len(codes), 40):
    batch = codes[bi:bi + 40]
    fp = CACHE / f"b{bi}.json"
    if fp.exists():
        events.extend(json.loads(fp.read_text()))
        continue
    rows_all = []
    try:
        page = 1
        while page <= 10:
            params = {"sr": "-1", "page_size": "100", "page_index": str(page), "ann_type": "A",
                      "client_source": "web", "f_node": "0", "s_node": "0",
                      "stock_list": ",".join(batch),
                      "begin_time": "2024-01-01", "end_time": "2026-09-25"}
            r = sess.get(LIST_URL, params=params, timeout=18)
            data = r.json().get("data") or {}
            rows = data.get("list") or []
            if not rows:
                break
            for row in rows:
                title = str(row.get("title") or "")
                if EXCLUDE.search(title):
                    continue
                kind = next((k for k in KW if KW[k].search(title)), None)
                if not kind:
                    continue
                nd = str(row.get("notice_date") or "")[:10]
                for cr in row.get("codes") or []:
                    code = str(cr.get("stock_code", "")).zfill(6)
                    if code in set(batch):
                        rows_all.append({"code": code, "title": title, "date": nd, "kind": kind})
            if len(rows) < 100:
                break
            page += 1
            time.sleep(0.2)
    except Exception as e:
        print(f"batch {bi} ERR {str(e)[:60]}", flush=True)
    fp.write_text(json.dumps(rows_all, ensure_ascii=False))
    events.extend(rows_all)
    if bi % 400 == 0:
        print(f"进度 {bi}/{len(codes)} 事件 {len(events)}", flush=True)
    time.sleep(0.4)

print(f"增持/回购/减持事件 {len(events)}", flush=True)
json.dump(events, open(ROOT / "data/holder_events_raw_20260926.json", "w"), ensure_ascii=False)
