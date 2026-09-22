"""云峰对账 v2：按发帖时刻的分钟级真实价格入场（回应「买不是10:30吗」）。

入场价三口径对比：
  A 他口径v1 = 入场日收盘（旧，偏高）
  B 发帖时刻口径 = 帖子时间所在 60m bar 的收盘（新浪 m60，datalen 拉满1970根覆盖3-7月）
  C 10:30口径 = 首根60m bar（9:30-10:30）收盘（用户指认的买点约定）
出场=出场帖当日收盘（不变）。粉丝口径=次日开盘（不变）。
"""
import json
import subprocess
import time

EPISODES = json.load(open("/opt/data/fenjue/tmp/yunfeng_accounting.json"))
POSTS = json.load(open("/opt/data/fenjue/tmp/yunfeng_posts.json"))
import re
STOCK_TAG = re.compile(r"\$([^$]{1,12})\((?:SH|SZ)?(\d{6})\)\$")

# 每只股票的发帖时刻表
post_times = {}
for p in POSTS:
    text = f"{p.get('post_title','')} {p.get('post_content','')} {p.get('source_post_title','')} {p.get('source_post_content','')}"
    ts = p.get('post_publish_time') or ''
    for name, code in STOCK_TAG.findall(text):
        post_times.setdefault(code, []).append(ts)

URL = ("https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
       "CN_MarketData.getKLineData?symbol={sym}&scale=60&ma=no&datalen=1970")


def fetch_m60(code):
    sym = ("sh" if code.startswith("6") else "sz") + code
    r = subprocess.run(["curl", "-sL", "--max-time", "20", "-H", "Referer: https://finance.sina.com.cn/", URL.format(sym=sym, n=1970)],
                       capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"})
    try:
        rows = json.loads(r.stdout)
        return rows or []
    except Exception:
        return []


KC = "/opt/data/fenjue/data/big_kcache"


def load_daily(code):
    ks = json.load(open(f"{KC}/{code}.json"))
    return {k["date"]: k for k in ks}, [k["date"] for k in ks]


def bar_close_at(bars_by_day, day, hhmm):
    """帖子时刻所在 bar 的收盘：找当天最后一个 bar_end <= hhmm+30min 的 bar；盘前帖用首根。"""
    day_bars = bars_by_day.get(day, [])
    if not day_bars:
        return None
    # bar 的 day 字段是 bar 结束时间（10:30/11:30/14:00/15:00）
    for b in day_bars:
        if b["day"][11:16] >= hhmm:
            return float(b["close"])
    return float(day_bars[-1]["close"])


results = []
for ep in EPISODES:
    code, d_in, d_out = ep["code"], ep["in"], ep["out"]
    ks, dates = load_daily(code)
    bars = fetch_m60(code)
    time.sleep(1.2)
    by_day = {}
    for b in bars:
        by_day.setdefault(b["day"][:10], []).append(b)
    # 发帖时刻：该票在入场日的最早一条帖
    pts = sorted(t for t in post_times.get(code, []) if t[:10] == d_in)
    t_post = (pts[0][11:16] if pts else "09:45")
    cB = bar_close_at(by_day, d_in, t_post)
    c1030 = (float(by_day[d_in][0]["close"]) if by_day.get(d_in) else None)
    cA = ks[d_in]["close"]
    c_out = ks[d_out]["close"]
    rA = c_out / cA - 1
    rB = (c_out / cB - 1) if cB else None
    rC = (c_out / c1030 - 1) if c1030 else None
    results.append({**ep, "post_time": t_post, "r_close": rA, "r_postbar": rB, "r_1030": rC})
    print(f"{ep['name']:<8} {d_in} {t_post}  收盘口径{rA * 100:+6.1f}%  发帖bar口径{(f'{rB * 100:+.1f}%' if rB is not None else '无数据'):>9}  10:30口径{(f'{rC * 100:+.1f}%' if rC is not None else '无数据'):>9}")

import math
for key, label in (("r_close", "收盘"), ("r_postbar", "发帖bar"), ("r_1030", "10:30")):
    chain = [r[key] for r in results if r[key] is not None and r["in"] < "2026-07"]
    comp = math.prod(1 + x for x in chain)
    wins = sum(1 for x in chain if x > 0)
    print(f"\n{label}口径: n={len(chain)} 复合 {comp:.2f}x 胜率 {wins}/{len(chain)}")
json.dump(results, open("/opt/data/fenjue/tmp/yunfeng_accounting_v2.json", "w"), ensure_ascii=False, indent=1)
