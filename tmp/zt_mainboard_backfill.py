# -*- coding: utf-8 -*-
import json, urllib.request, csv, time, re, os, random, datetime
from concurrent.futures import ThreadPoolExecutor

UA_TH = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
         "Referer": "http://data.10jqka.com.cn/"}
UA_EM = {"User-Agent": "Mozilla/5.0", "Referer": "http://quote.eastmoney.com/"}
BEG, END = "2025-09-08", "2026-09-22"
CST = datetime.timezone(datetime.timedelta(hours=8))
BASE = r"C:\Users\Tebio Zack"
CKPT = os.path.join(BASE, "zt_ckpt.jsonl")
OUT = os.path.join(BASE, "limit_up_mainboard_20250908_20260922.csv")

def get(url, headers, retries=10):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            return json.loads(urllib.request.urlopen(req, timeout=30).read())
        except Exception:
            time.sleep(min(2 ** i, 30) + random.random())
    raise RuntimeError("fail: " + url[:100])

# 1. trading calendar
cal = get("https://web.ifzq.gtimg.cn/appstock/app/kline/kline?param=sh000001,day,%s,%s,300" % (BEG, END), UA_EM)
days = [b[0] for b in cal["data"]["sh000001"]["day"]]
print("trading days:", len(days), days[0], "->", days[-1], flush=True)

done_days = set()
if os.path.exists(CKPT):
    with open(CKPT, encoding="utf-8") as f:
        for line in f:
            done_days.add(json.loads(line)["日期"])
    print("resume, days done:", len(done_days), flush=True)

def bucket(fbt):
    if fbt <= "09:25:00": return "竞价板"
    if fbt < "10:30:00": return "早盘板(<10:30)"
    if fbt < "14:00:00": return "午盘板(10:30-14:00)"
    return "尾盘板(>=14:00)"

def lianban(hd):
    if not hd or "首板" in hd: return 1
    m = re.search(r"(\d+)", hd)
    return int(m.group(1)) if m else 1

def mainboard(code):
    return code.startswith(("60", "00"))

# 2. THS pool per day, checkpoint per day
ck = open(CKPT, "a", encoding="utf-8")
n_rec, n_st = 0, 0
for d in days:
    if d in done_days:
        continue
    ymd = d.replace('-', '')
    info = []
    page = 1
    while True:
        u = ("http://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool?page=%d&limit=200"
             "&field=199112,10,9001,330323,330324,330325,9002,330329,133971,133970,1968584,3475914,9003,9004"
             "&filter=HS,GEM2STAR&date=%s&order_field=330324&order_type=0" % (page, ymd))
        # retry until valid data (anti-bot returns status -1 / missing data)
        for attempt in range(20):
            r = get(u, UA_TH)
            dd = r.get("data")
            if dd and "info" in dd:
                break
            wait = min(10 * (attempt + 1), 90) + random.random() * 5
            print(d, "retry", attempt + 1, "wait", round(wait), flush=True)
            time.sleep(wait)
        else:
            raise SystemExit("blocked at " + d)
        info.extend(dd.get("info") or [])
        total = dd.get("page", {}).get("total", 0)
        if len(info) >= total or not dd.get("info"):
            break
        page += 1
        time.sleep(2 + random.random())
    day_rows = []
    for x in info:
        code, name = x.get("code", ""), x.get("name", "")
        if not mainboard(code):
            continue
        if "ST" in name.upper() or "退" in name:
            n_st += 1
            continue
        fbt = datetime.datetime.fromtimestamp(int(x["first_limit_up_time"]), CST).strftime("%H:%M:%S")
        lbt = datetime.datetime.fromtimestamp(int(x["last_limit_up_time"]), CST).strftime("%H:%M:%S")
        fund = float(x.get("order_amount") or 0)
        cv = float(x.get("currency_value") or 0)
        day_rows.append({
            "日期": d, "代码": code, "名称": name,
            "首次封板时间": fbt, "最后封板时间": lbt,
            "炸板次数": x.get("open_num", 0),
            "封单额(元)": round(fund, 0),
            "连板数": lianban(x.get("high_days", "")),
            "涨停价": x.get("latest", ""),
            "涨跌幅(%)": round(float(x.get("change_rate") or 0), 2),
            "换手率(%)": round(float(x.get("turnover_rate") or 0), 2),
            "成交额(亿元)": "",
            "所属行业": "",
            "封板时段": bucket(fbt),
            "流通市值(亿元)": round(cv / 1e8, 2),
            "封单额/流通市值(%)": round(fund / cv * 100, 3) if cv else "",
            "涨停原因(同花顺)": x.get("reason_type", ""),
        })
    for r0 in day_rows:
        ck.write(json.dumps(r0, ensure_ascii=False) + "\n")
    ck.flush()
    n_rec += len(day_rows)
    print(d, "THS total:", dd.get("page", {}).get("total"), "mainboard kept:", len(day_rows), flush=True)
    time.sleep(3.5 + random.random() * 1.5)
ck.close()
print("records:", n_rec, "skipped ST/退:", n_st, flush=True)

# 3. reload all records
records = []
with open(CKPT, encoding="utf-8") as f:
    for line in f:
        records.append(json.loads(line))
print("total records loaded:", len(records), flush=True)

# 4. EM pool (recent days only) -> 所属行业
em_map = {}
for d in days:
    ymd = d.replace('-', '')
    u = ("http://push2ex.eastmoney.com/getTopicZTPool?ut=7eea3edcaed734bea9cbfc24409ed989"
         "&dpt=wz.ztzt&Pageindex=0&pagesize=500&sort=fbt:asc&date=%s" % ymd)
    r = get(u, UA_EM)
    dd = r.get("data") or {}
    for x in (dd.get("pool") or []):
        em_map[(d, x["c"])] = x.get("hybk", "")
    time.sleep(0.3)
hit = 0
for r in records:
    hy = em_map.get((r["日期"], r["代码"]))
    if hy:
        r["所属行业"] = hy
        hit += 1
print("EM industry filled:", hit, flush=True)

# 5. tencent kline per unique stock -> next-day prices
codes = sorted({r["代码"] for r in records})
print("unique stocks:", len(codes), flush=True)

def tx_sym(c):
    return "sh" + c if c.startswith("6") else "sz" + c

def fetch_kline(c):
    sym = tx_sym(c)
    u = "https://web.ifzq.gtimg.cn/appstock/app/kline/kline?param=%s,day,%s,2026-12-31,300" % (sym, BEG)
    try:
        d = get(u, UA_EM)
        bars = d["data"].get(sym, {}).get("day") or []
        return c, {b[0]: (float(b[1]), float(b[2]), float(b[3])) for b in bars}
    except Exception:
        return c, {}

kmap, done = {}, 0
with ThreadPoolExecutor(max_workers=6) as ex:
    for c, kl in ex.map(fetch_kline, codes):
        kmap[c] = kl
        done += 1
        if done % 300 == 0:
            print("kline", done, "/", len(codes), flush=True)

miss = 0
for r in records:
    kl = kmap.get(r["代码"], {})
    nxt = [d for d in sorted(kl) if d > r["日期"]]
    if nxt:
        nd = nxt[0]
        o, c, h = kl[nd]
        base = float(r["涨停价"])
        r["次日开盘涨幅(%)"] = round((o / base - 1) * 100, 2)
        r["次日收盘涨幅(%)"] = round((c / base - 1) * 100, 2)
        r["次日最高涨幅(%)"] = round((h / base - 1) * 100, 2)
    else:
        miss += 1
        r["次日开盘涨幅(%)"] = r["次日收盘涨幅(%)"] = r["次日最高涨幅(%)"] = ""

cols = ["日期", "代码", "名称", "首次封板时间", "最后封板时间", "炸板次数", "封单额(元)", "连板数",
        "涨停价", "涨跌幅(%)", "换手率(%)", "成交额(亿元)", "所属行业", "封板时段",
        "次日开盘涨幅(%)", "次日收盘涨幅(%)", "次日最高涨幅(%)",
        "流通市值(亿元)", "封单额/流通市值(%)", "涨停原因(同花顺)"]
with open(OUT, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=cols)
    w.writeheader()
    w.writerows(records)
print("saved:", OUT, len(records), "rows; next-day missing:", miss, flush=True)
