"""转债日更+低价债池（2026-09-26 凌晨，BACKLOG#24）。

每交易日：拉东财转债列表首页（最新 500 含全部活跃债）+ 全部活跃债日K（sina 增量式全量重写，
312 只约 2 分钟），落盘 data/cb_list.json / data/cb_klines.json，
并产出土池 data/cb_low_price.json（收盘≤105 的债：代码/名称/价格/正股/评级/剩余年限）。
"""
import json
import time
from pathlib import Path

import requests

ROOT = Path("/opt/data/fenjue")
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn/"}

rows = []
for _page in (1, 2):  # 活跃债 ~320 只跨前两页（首页按发行日期排序漏尾部老债，实测 290/322）
    params = {"reportName": "RPT_BOND_CB_LIST", "columns": "ALL", "pageSize": "600",
              "pageNumber": str(_page), "sortColumns": "PUBLIC_START_DATE", "sortTypes": "-1",
              "source": "WEB", "client": "WEB"}
    d = requests.get("https://datacenter-web.eastmoney.com/api/data/v1/get",
                     params=params, headers=HEADERS, timeout=20).json()
    rows.extend((d.get("result") or {}).get("data") or [])
    time.sleep(0.5)
(ROOT / "data/cb_list.json").write_text(json.dumps(rows, ensure_ascii=False))
active = [r for r in rows if not r.get("DELIST_DATE") and r.get("SECURITY_CODE")]
print(f"活跃债 {len(active)}")


def mkt(code):
    return ("sh" if code[:2] in ("11", "13") else "sz") + code


klines = {}
for k, r in enumerate(active):
    code = r["SECURITY_CODE"]
    try:
        resp = requests.get(
            f"https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData"
            f"?symbol={mkt(code)}&scale=240&ma=no&datalen=900",
            headers=HEADERS, timeout=10)
        data = resp.json()
        if data:
            klines[code] = [{"date": x["day"], "open": float(x["open"]), "close": float(x["close"]),
                             "high": float(x["high"]), "low": float(x["low"]), "volume": float(x["volume"])}
                            for x in data]
    except Exception:
        pass
    time.sleep(0.12)
(ROOT / "data/cb_klines.json").write_text(json.dumps(klines, ensure_ascii=False))

meta = {r["SECURITY_CODE"]: r for r in active}
from datetime import date as _date, timedelta
_ref = max(ks[-1]["date"] for ks in klines.values() if ks)
_ref_dt = _date.fromisoformat(_ref)
_fresh_floor = (_ref_dt - timedelta(days=10)).isoformat()


def _alive(m, last):
    """活跃闸门（2026-10-12 加）：①已到期摘牌（CEASE_DATE < 池基准日）②近 10 自然日无成交
    ——缺这道闸，僵尸债会长期挂在「低价池」推给用户（实测 3 只池里 2 只是僵尸：
    东时转债 4/08 已到期、中装转2 自 2025-09 起无 K 线，价格被冻结在旧值上）。"""
    ce = str(m.get("CEASE_DATE") or "")[:10]
    if ce and ce < _ref:
        return False
    return last["date"] >= _fresh_floor


pool, dropped = [], []
for code, ks in klines.items():
    if not ks:
        continue
    last = ks[-1]
    if 80 < last["close"] <= 105:
        m = meta.get(code, {})
        if not _alive(m, last):
            dropped.append({"code": code, "name": m.get("SECURITY_NAME_ABBR", ""),
                            "price": last["close"], "last_bar": last["date"],
                            "expire": str(m.get("CEASE_DATE") or "")[:10]})
            continue
        pool.append({"code": code, "name": m.get("SECURITY_NAME_ABBR", ""),
                     "price": last["close"], "date": last["date"],
                     "stock": m.get("CONVERT_STOCK_CODE"), "rating": m.get("RATING"),
                     "expire": str(m.get("CEASE_DATE") or "")[:10]})
pool.sort(key=lambda x: x["price"])
# 强赎预警（近 3 天发强赎公告的债=持债者 T+1 内应走，#179 纪律）
from datetime import date, timedelta
cutoff = (date.today() - timedelta(days=3)).isoformat()
redeem_alerts = [{"code": m["SECURITY_CODE"], "name": m.get("SECURITY_NAME_ABBR", ""),
                  "notice": str(m.get("NOTICE_DATE_HS") or "")[:10]}
                 for m in active
                 if str(m.get("NOTICE_DATE_HS") or "")[:10] >= cutoff]
(ROOT / "data/cb_low_price.json").write_text(json.dumps(
    {"date": klines and max(ks[-1]["date"] for ks in klines.values() if ks) or "?",
     "n": len(pool), "pool": pool, "dropped_zombie": dropped, "redeem_alerts": redeem_alerts},
    ensure_ascii=False, indent=1))
print(f"日K {len(klines)} 只；低价池(≤105) {len(pool)} 只；剔除僵尸 {len(dropped)} 只；强赎预警 {len(redeem_alerts)} 只")
if dropped:
    print("  剔除明细: " + "; ".join(f"{d['name']}({d['code']}) 末bar{d['last_bar']} 到期{d['expire']}" for d in dropped))
