#!/usr/bin/env python3
"""engine/theme_study.py — 题材结构解剖（回答「最近在炒什么/为什么是这些票」的复跑脚本）

口径（2026-10-12 立）：
  数据源 = data/hithink/<date>/limit_up_pool.json（HiThink 涨停池，含 limit_up_reason/continue_day_cnt/seal_money）
  窗口默认 2026-09-23 起（可传参）；题材词 = limit_up_reason 按 '+' 切分
  画像 = 腾讯实时（PE f[39]/PB f[46]/换手 f[38]/流通市值 f[44]）+ big_kcache 近250日（年涨停次数/距250日高）

用法：
  .venv/bin/python engine/theme_study.py                 # 默认窗口 2026-09-23..
  .venv/bin/python engine/theme_study.py 2026-09-01      # 指定起日
输出：题材关键词频次 / 每日涨停数 / 反复涨停载体 Top / 指定标的画像表
不落盘、不写生产状态，纯只读解剖。
"""
import collections, glob, json, os, re, sys, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
SINCE = sys.argv[1] if len(sys.argv) > 1 else "2026-09-23"

# 画像标的（近期题材核心 + 各分支代表；按需要改）
WATCH = {
    "601929": "吉视传媒", "000892": "欢瑞世纪", "605577": "龙版传媒", "600127": "金健米业",
    "600825": "新华传媒", "601811": "新华文轩", "603230": "内蒙新华", "600371": "万向德农",
    "002343": "慈文传媒", "603096": "新经典", "600831": "广电网络", "001330": "博纳影业",
    "300510": "金冠电气", "601052": "果麦文化",
}


def days():
    return sorted(d for d in glob.glob("data/hithink/2026-*")
                  if os.path.isdir(d) and d[-10:] >= SINCE)


def pools():
    for d in days():
        p = f"{d}/limit_up_pool.json"
        if not os.path.exists(p):
            continue
        j = json.load(open(p))
        for r in ((j.get("data") or {}).get("item") or []):
            yield d[-10:], r


def main():
    rows = list(pools())
    print(f"[窗口 {SINCE} .. 最新] 涨停条目 {len(rows)}")
    daily = collections.Counter(d for d, _ in rows)
    print("每日涨停数:", " ".join(f"{k}:{v}" for k, v in sorted(daily.items())))

    kw, stocks = collections.Counter(), collections.Counter()
    for _, r in rows:
        stocks[r["name"]] += 1
        for t in (r.get("limit_up_reason") or "").split("+"):
            if t.strip():
                kw[t.strip()] += 1
    print("\n题材关键词 Top30:")
    for k, v in kw.most_common(30):
        print(f"  {v:4d}  {k}")

    print("\n反复涨停载体 Top15（已被资金认熟的票）:")
    for k, v in stocks.most_common(15):
        cd = max((r.get("continue_day_cnt") or 1) for _, r in rows if r["name"] == k)
        last = [r for _, r in rows if r["name"] == k][-1].get("limit_up_reason") or ""
        print(f"  {v:2d}次 {k:8s} 最高{cd}板  {last[:38]}")

    guo = [r for _, r in rows if re.search("国资|国企", r.get("limit_up_reason") or "")]
    print(f"\n带国资/国企标签: {len(guo)}/{len(rows)} = {len(guo)/max(1,len(rows))*100:.0f}%")

    # ---- 画像 ----
    pre = {c: ("sh" + c if c[0] in "56" else "sz" + c) for c in WATCH}
    url = "https://qt.gtimg.cn/q=" + ",".join(pre.values())
    txt = urllib.request.urlopen(urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"}), timeout=20
    ).read().decode("gbk", "ignore")
    q = {}
    for line in txt.strip().split("\n"):
        m = re.match(r'v_(\w+)="(.*)";', line.strip())
        if not m:
            continue
        f = m.group(2).split("~")
        if len(f) > 46:
            q[m.group(1)[2:]] = f
    print(f"\n{'名称':9s}{'代码':8s}{'现价':>7s}{'今日%':>7s}{'PE':>9s}{'PB':>7s}{'流通亿':>9s}{'换手%':>7s}{'年涨停':>6s}{'距250高%':>9s}")
    for c, n in WATCH.items():
        f = q.get(c)
        if not f:
            continue
        now, pc = float(f[3]), float(f[32])
        zn = ""
        zp = f"data/big_kcache/{c}.json"
        if os.path.exists(zp):
            cl = [b["close"] for b in json.load(open(zp))[-250:]]
            zn = sum(1 for i in range(1, len(cl)) if cl[i] / cl[i - 1] - 1 > 0.095)
            zn = f"{zn}/{ (now/max(cl)-1)*100:.0f}"
        print(f"{n:9s}{c:8s}{now:7.2f}{pc:7.2f}{f[39][:8]:>9s}{f[46][:6]:>7s}{f[44][:8]:>9s}{f[38][:5]:>7s}{zn:>6s}")


if __name__ == "__main__":
    main()
