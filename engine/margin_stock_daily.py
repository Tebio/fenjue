"""个股两融明细管道（2026-09-29 立，源：东财 RPTA_WEB_RZRQ_GGMX，2010-03 起 ~690 万行）。

起因：横截面试点（tmp/margin_pilot.py，n=3.05 万）发现「融资余额占流通比」五分位单调
（Q1 47%/+1.11 → Q5 52%/+3.37，T+20）——单调性是真的，但混杂市值/流动性/时代窗，
正式研究需要全史逐日序列，故建库。

设计（长批纪律）：SQLite 单库 data/margin_stock.db，按日事务写入（一日要么全写要么不写），
断点=日期存在性，重跑自动 skip；1.1s/页+失败指数退避（东财阈值：1分钟>200 封 IP，我们 55/分 安全）。
只留研究字段，剔北证。
用法：
  --latest    日更：从库内最大日期补到最新（cron 每交易日 21:00 BJT）
  --backfill  全史回填：从最新往 2010 倒灌（一次性，断点续跑）
"""
import json
import sqlite3
import sys
import time
from pathlib import Path

import requests

ROOT = Path("/opt/data/fenjue")
DB = ROOT / "data" / "margin_stock.db"
H = {"User-Agent": "Mozilla/5.0"}
URL = ("https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPTA_WEB_RZRQ_GGMX"
       "&columns=SCODE,DATE,RZYE,RZYEZB,RZJME,SZ,RZMRE5D"
       "&pageSize=500&pageNumber={p}&sortColumns=DATE&sortTypes={st}"
       "&filter=(DATE='{d}')")
LATEST_URL = ("https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPTA_WEB_RZRQ_GGMX"
              "&columns=DATE&pageSize=1&pageNumber=1&sortColumns=DATE&sortTypes=-1")
KEEP_PREFIX = ("60", "00", "300", "301", "688")


def db():
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS m (
        date TEXT, code TEXT, rzye REAL, rzyezb REAL, rzjme REAL, sz REAL, rzmre5d REAL,
        PRIMARY KEY (date, code))""")
    con.execute("CREATE INDEX IF NOT EXISTS ix_m_code ON m(code, date)")
    return con


def get(url, retry=5):
    for k in range(retry):
        try:
            r = requests.get(url, headers=H, timeout=30)
            d = r.json()
            if d.get("success") is False and not d.get("result"):
                raise RuntimeError(d.get("message"))
            return d
        except Exception:
            if k == retry - 1:
                raise
            time.sleep(3 * (2 ** k))


def pull_date(day):
    """拉一日全量（沪深，剔北证），事务写入；返回行数"""
    rows, p = [], 1
    while True:
        d = get(URL.format(p=p, d=day, st=-1))
        items = (d.get("result") or {}).get("data") or []
        for x in items:
            code = x.get("SCODE") or x.get("SECURITY_CODE")
            if code and code.startswith(KEEP_PREFIX):
                rows.append((day, code, x.get("RZYE"), x.get("RZYEZB"), x.get("RZJME"),
                             x.get("SZ"), x.get("RZMRE5D")))
        pages = (d.get("result") or {}).get("pages") or 1
        if p >= pages or not items:
            break
        p += 1
        time.sleep(1.1)
    if rows:
        con = db()
        con.executemany("INSERT OR REPLACE INTO m VALUES (?,?,?,?,?,?,?)", rows)
        con.commit()
        con.close()
    return len(rows)


def have_date(day):
    con = db()
    n = con.execute("SELECT COUNT(*) FROM m WHERE date=?", (day,)).fetchone()[0]
    con.close()
    return n > 1000  # 一日正常 1900+ 行，<1000 视为未写/残


def latest_remote():
    d = get(LATEST_URL)
    return d["result"]["data"][0]["DATE"][:10]


def trading_dates(start, end):
    idx = json.loads((ROOT / "data/index_sh000001.json").read_text())
    return [r["date"] for r in idx if start <= r["date"] <= end]


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "--latest"
    con = db()
    local_max = con.execute("SELECT MAX(date) FROM m").fetchone()[0] or "2010-03-30"
    con.close()
    remote_max = latest_remote()
    print(f"库内最大 {local_max}，远端最大 {remote_max}", flush=True)

    if mode == "--latest":
        days = trading_dates(local_max, remote_max)[1:]  # 次日起到最新
        if not days:
            print("已最新，无增量")
            return
        for day in days:
            n = pull_date(day)
            print(f"{day}: {n} 行", flush=True)
        return

    if mode == "--backfill":
        days = [d for d in trading_dates("2010-03-31", remote_max) if not have_date(d)]
        print(f"待补 {len(days)} 个交易日（断点续跑）", flush=True)
        empty_streak = 0
        for i, day in enumerate(sorted(days, reverse=True)):
            try:
                n = pull_date(day)
                empty_streak = 0 if n else empty_streak + 1
            except Exception as e:
                # 单日失败不杀整批：睡60s补试一次，仍败则记洞跳过；连续3日空=IP封禁特征才中止
                print(f"[WARN] {day} 首试失败({e})，60s后补试", flush=True)
                time.sleep(60)
                try:
                    n = pull_date(day)
                    empty_streak = 0 if n else empty_streak + 1
                except Exception as e2:
                    print(f"[WARN] {day} 补试仍败({e2})，记洞跳过", flush=True)
                    empty_streak += 1
                    n = 0
            if empty_streak >= 3:
                raise SystemExit("连续3日空/失败——疑似IP被封，中止保护（断点已落库，解封后续跑）")
            if i % 20 == 0 or not n:
                print(f"[{i + 1}/{len(days)}] {day}: {n} 行", flush=True)
        print("BACKFILL DONE", flush=True)
        return
    raise SystemExit(f"未知模式 {mode}")


if __name__ == "__main__":
    main()
