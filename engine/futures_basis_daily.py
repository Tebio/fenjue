"""股指期货基差采集器（2026-09-29 立）。

源：新浪 InnerFuturesNewService.getDailyKLine（CFFEX 品种同样走内盘通道，2026-09-29 实测到当日；
    注意 stock2 的 CffexFuturesService 专用端点已停更于 2024-12-10，勿用）。
现货：新浪 CN_MarketDataService.getKLineData（指数日K）。

口径与坑：
- 期货用主力连续（IF0/IH0/IC0/IM0）——换月接缝会制造假基差跳变，研究时按「贴水分位」用，
  别拿绝对点位跨月比较（已记录的口径边界）。
- 期货 15:00 收盘 vs 现货 15:00 收盘，同日对齐；期货有夜盘无（期指无夜盘），日期天然对齐。
- 贴水=(期货-现货)/现货×100%，负值=贴水（恐慌对冲盘拥挤的标志）。
产物 data/futures_basis.json（全量覆盖写，幂等）。cron 每交易日 16:20 BJT。
"""
import json
import re
import time
from pathlib import Path

import requests

ROOT = Path("/opt/data/fenjue")
OUT = ROOT / "data" / "futures_basis.json"

FUT = {  # 品种 -> (期货代码, 现货指数代码, 中文名)
    "IF": ("IF0", "sh000300", "沪深300"),
    "IH": ("IH0", "sh000016", "上证50"),
    "IC": ("IC0", "sh000905", "中证500"),
    "IM": ("IM0", "sh000852", "中证1000"),
}

FUT_URL = ("https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20_{code}="
           "/InnerFuturesNewService.getDailyKLine?symbol={code}")
SPOT_URL = ("https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
            "?symbol={code}&scale=240&ma=no&datalen=2500")
HEADERS = {"Referer": "https://finance.sina.com.cn/", "User-Agent": "Mozilla/5.0"}


def fetch_fut(sym: str) -> dict:
    r = requests.get(FUT_URL.format(code=sym), headers=HEADERS, timeout=20)
    text = r.content.decode("gbk", "replace")
    m = re.search(rf"var _{re.escape(sym)}=\((\[.*?\])\)", text, re.S)
    if not m or m.group(1).strip() == "null":
        raise RuntimeError(f"{sym} 期货数据异常")
    out = {}
    for it in json.loads(m.group(1)):
        out[str(it["d"]).replace("/", "-")] = float(it["c"])
    return out


def fetch_spot(code: str) -> dict:
    r = requests.get(SPOT_URL.format(code=code), headers=HEADERS, timeout=20)
    rows = json.loads(r.text)
    if not rows:
        raise RuntimeError(f"{code} 现货指数无数据")
    return {it["day"][:10]: float(it["close"]) for it in rows}


def main():
    result, fails = {}, []
    for key, (fsym, scode, cname) in FUT.items():
        try:
            fut = fetch_fut(fsym)
            time.sleep(1.2)
            spot = fetch_spot(scode)
            time.sleep(1.2)
            rows = []
            for day in sorted(fut):
                if day in spot and spot[day] > 0:
                    f, s = fut[day], spot[day]
                    rows.append({"date": day, "fut": f, "spot": s,
                                 "basis": round(f - s, 2),
                                 "basis_pct": round((f - s) / s * 100, 3)})
            result[key] = {"name": cname, "fut_sym": fsym, "spot_sym": scode, "rows": rows}
            print(f"{key}({cname}): {len(rows)} 天, 最新 {rows[-1]['date']} "
                  f"基差 {rows[-1]['basis']:+.1f} ({rows[-1]['basis_pct']:+.2f}%)")
        except Exception as e:
            fails.append(f"{key}: {e}")
            print(f"[WARN] {key} 失败: {e}")
    if result:
        OUT.write_text(json.dumps(result, ensure_ascii=False))
        print(f"已落盘 {OUT} ({len(result)} 个品种)")
    if fails:
        raise SystemExit("部分失败: " + "; ".join(fails))


if __name__ == "__main__":
    main()
