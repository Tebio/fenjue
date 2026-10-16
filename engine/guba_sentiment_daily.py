#!/usr/bin/env python3
# engine/guba_sentiment_daily.py — 股吧人气前瞻每日采集器（RES-09 前瞻观察层）
# 每日采集: ①人气榜 top100 快照 ②自选股池(watchlist positions) hisList 增量
# 落盘: data/private/guba_sentiment/top100_YYYY-MM-DD.json + his_<code>.json (幂等: 同日重跑零新增)
# 说明: 东财 hisList 公开端点本身带 366 历日历史, 本采集器的价值=①top100 快照无历史(翻页为空)必须自攒
#       ②hisList 超过 366 天的部分只能靠每日续命 ③粉丝画像 getHisProfileList 同样只给 365 天
# 用法: python engine/guba_sentiment_daily.py   (盘后/盘中均可, 幂等)
import json, sys, time
from pathlib import Path
from datetime import datetime, timezone, timedelta

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "private" / "guba_sentiment"
OUT.mkdir(parents=True, exist_ok=True)
BJ = timezone(timedelta(hours=8))
NOW = datetime.now(BJ)
TODAY = NOW.strftime("%Y-%m-%d")
BASE = {"appId": "appId01", "globalId": "786e4c21-70dc-435a-93bb-38", "marketType": ""}


def meta(owner="engine.guba_sentiment_daily"):
    return {"generated_at": NOW.isoformat(timespec="seconds"),
            "data_snapshot": TODAY, "owner": owner}


def fetch_json(sess, url, payload):
    r = sess.post(url, json=payload, timeout=15)
    d = r.json()
    if d.get("status") not in (0, None) and not d.get("data"):
        raise RuntimeError(f"bad response: {str(d)[:120]}")
    return d.get("data") or []


def main():
    sess = requests.Session()

    # ① top100 快照 (官方无历史 — 此文件即历史)
    # 注意: 盘中读到的当日排名是「临时值」，23:00 定稿会变（2026-10-16 实测同日两次读 2499→2575），
    #       因此本文件每次运行都覆盖为最新值，并把每次读数追加进 top100_intraday_<date>.jsonl
    #       —— 收盘后 (≥23:00) 的运行才把当日值钉死；盘中的中间态留在 intraday 文件里当研究资产。
    fp_top = OUT / f"top100_{TODAY}.json"
    rows = fetch_json(sess, "https://emappdata.eastmoney.com/stockrank/getAllCurrentList",
                      dict(BASE, pageNo=1, pageSize=100))
    top100 = [{"sc": x["sc"], "rk": x["rk"], "rc": x.get("rc"), "his_rc": x.get("hisRc")}
              for x in rows]
    if not top100 and fp_top.exists():
        n_top = f"keep(exists,{len(json.loads(fp_top.read_text())['rows'])},empty_response)"
    elif not top100:
        raise RuntimeError("top100 端点返回空且无历史文件 — 不写坏数据")
    else:
        meta_now = meta()
        meta_now["captured_at"] = NOW.isoformat(timespec="seconds")
        fp_top.write_text(json.dumps({"_meta": meta_now, "rows": top100}, ensure_ascii=False))
        with open(OUT / f"top100_intraday_{TODAY}.jsonl", "a") as fh:
            fh.write(json.dumps({"captured_at": NOW.isoformat(timespec="seconds"),
                                 "rows": top100}, ensure_ascii=False) + "\n")
        n_top = f"new({len(top100)})"

    # ② 自选股池 hisList 增量 (watchlist positions；同日值以最新一次抓取为准)
    wl = json.loads((ROOT / "config" / "watchlist.json").read_text())
    codes = sorted({p["code"] for p in wl.get("positions", [])})
    added = {}
    for code in codes:
        sc = ("SH" if code.startswith("6") else "SZ") + code
        fp = OUT / f"his_{code}.json"
        old = {"rows": []}
        if fp.exists():
            old = json.loads(fp.read_text())
        rows = fetch_json(sess, "https://emappdata.eastmoney.com/stockrank/getHisList",
                          dict(BASE, srcSecurityCode=sc, yearType="5"))
        if rows:
            m = {r[0]: r[1] for r in old["rows"]}
            before = dict(m)
            m.update({r[0]: int(x["rank"]) for x in rows})
            merged = sorted([d, v] for d, v in m.items())
            changed = sum(1 for d, v in m.items() if before.get(d) != v)
            fp.write_text(json.dumps({"_meta": meta(), "code": code, "rows": merged}))
            added[code] = f"{len(merged)}(+{changed})"
        else:
            added[code] = f"{len(old['rows'])}(no-response)"
        time.sleep(0.05)

    print(f"[guba_sentiment] {TODAY} top100={n_top} watchlist={added}")


if __name__ == "__main__":
    main()
