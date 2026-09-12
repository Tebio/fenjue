#!/usr/bin/env python3
"""engine/fetch_pead_events.py — PEAD 业绩预告事件库（S4 数据底座，2026-09-12 立）

源：东财 datacenter RPT_PUBLIC_OP_PREDICT（2026-09-12 实测活，11 万条全历史）。
字段：NOTICE_DATE 公告日 / REPORTDATE 报告期 / FORECASTL,T 预测净利区间 /
      INCREASEL,T 同比% / FORECASTTYPE 预增/略增/扭亏等 / YEAREARLIER 上年同期 / ISLATEST。
落盘：data/pead_events.json（全量，增量跑只补新 NOTICE_DATE）。
"""
import json, subprocess, time
from pathlib import Path

OUT = Path("/opt/data/fenjue/data/pead_events.json")
URL = ("https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_PUBLIC_OP_PREDICT"
       "&columns=ALL&pageNumber={p}&pageSize=500&sortColumns=NOTICE_DATE&sortTypes=-1"
       "&filter=(NOTICE_DATE%3E%3D%272019-01-01%27)")


def fetch(p):
    r = subprocess.run(["curl", "-sL", "--max-time", "20", URL.format(p=p),
                        "-H", "Referer: https://data.eastmoney.com/", "-H", "User-Agent: Mozilla/5.0"],
                       capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"})
    return json.loads(r.stdout)


def main():
    old = json.loads(OUT.read_text()) if OUT.exists() else []
    seen = {(x["SECURITY_CODE"], x["NOTICE_DATE"], x["REPORTDATE"], x.get("FORECASTCONTENT")) for x in old}
    latest_old = max((x["NOTICE_DATE"] for x in old), default="")
    new = []
    p = 1
    while True:
        d = fetch(p)
        res = d.get("result") or {}
        items = res.get("data") or []
        if not items:
            break
        for x in items:
            key = (x["SECURITY_CODE"], x["NOTICE_DATE"], x["REPORTDATE"], x.get("FORECASTCONTENT"))
            if key not in seen:
                seen.add(key)
                new.append(x)
        # 增量模式：撞到旧数据边界即停
        if latest_old and items[-1]["NOTICE_DATE"] <= latest_old:
            break
        if p >= res.get("pages", 1):
            break
        p += 1
        if p % 20 == 0:
            print(f"page {p}, new={len(new)}", flush=True)
        time.sleep(0.25)
    all_ = new + old
    all_.sort(key=lambda x: x["NOTICE_DATE"])
    OUT.write_text(json.dumps(all_, ensure_ascii=False))
    print(f"DONE 新增 {len(new)}，总量 {len(all_)}，最新公告日 {all_[-1]['NOTICE_DATE'] if all_ else '-'}")


if __name__ == "__main__":
    main()
