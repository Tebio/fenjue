#!/usr/bin/env python3
"""今日（9/18）影子单盘中对账：9/17 信号批 = 今日开盘入场，出场日 9/21 尾盘。

入场价用今日实际开盘（Sina 实时字段），现价用当前价 → 盘中浮动（未结）。
"""
import json, os, re, subprocess, collections

SHADOW = "/opt/data/fenjue/data/claims_shadow.jsonl"
NAMES = "/opt/data/fenjue/data/main_board_codes.json"

rows = []
for line in open(SHADOW, encoding="utf-8"):
    r = json.loads(line)
    if r["signal_date"] == "2026-09-17":
        rows.append(r)
print("9/17 信号批登记：%d 单" % len(rows))

try:
    nm = {str(s["code"]).zfill(6): s.get("name", "") for s in json.load(open(NAMES))["stocks"]}
except Exception:
    nm = {}

codes = sorted({r["code"] for r in rows})
env = dict(os.environ)
for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
    env.pop(k, None)

q = {}
for i in range(0, len(codes), 60):
    chunk = codes[i:i + 60]
    url = "http://hq.sinajs.cn/list=" + ",".join(("sh" if c.startswith("6") else "sz") + c for c in chunk)
    p = subprocess.run(["curl", "-s", "--max-time", "20", "-H", "Referer: https://finance.sina.com.cn/", url],
                       capture_output=True, env=env)
    for line in p.stdout.decode("gb18030", "replace").splitlines():
        m = re.match(r'var hq_str_(?:sh|sz)(\d{6})="(.*)";', line.strip())
        if not m:
            continue
        f = m.group(2).split(",")
        if len(f) > 5:
            q[m.group(1)] = {"name": f[0], "open": float(f[1]), "prev": float(f[2]),
                             "now": float(f[3]), "date": f[30] if len(f) > 30 else "", "time": f[31] if len(f) > 31 else ""}
print("实时行情 %d 只，时间 %s" % (len(q), next(iter(q.values()))["date"] + " " + next(iter(q.values()))["time"]))
print("（今日开盘入场 → 出场日 9/21 尾盘；下面为盘中浮动，未扣费未结）\n")

by_claim = collections.defaultdict(list)
detail = []
for r in rows:
    c = r["code"]
    g = q.get(c)
    if not g or g["open"] <= 0:
        continue
    ret = (g["now"] / g["open"] - 1) * 100
    by_claim[(r["claim"], r["tier"] or "-")].append(ret)
    detail.append((ret, c, nm.get(c, g["name"]), r["claim"], r["tier"] or "-", g["open"], g["now"]))

for (claim, tier), rs in sorted(by_claim.items(), key=lambda kv: -len(kv[1])):
    wins = sum(1 for x in rs if x > 0)
    print("  %-22s %-9s n=%4d  盘中均值 %+6.2f%%  胜率 %.1f%%" % (claim, tier, len(rs), sum(rs) / len(rs), 100 * wins / len(rs)))

allr = [d[0] for d in detail]
print("\n  全部 %d 单：盘中均值 %+.2f%%  胜率 %.1f%%" % (len(allr), sum(allr) / len(allr), 100 * sum(1 for x in allr if x > 0) / len(allr)))

print("\n=== 最好的 10 单 ===")
for x in sorted(detail, reverse=True)[:10]:
    print("  %-8s %-7s %-22s 开%.2f → 现%.2f  %+.2f%%" % (x[2], x[1], x[3], x[5], x[6], x[0]))
print("=== 最差的 10 单 ===")
for x in sorted(detail)[:10]:
    print("  %-8s %-7s %-22s 开%.2f → 现%.2f  %+.2f%%" % (x[2], x[1], x[3], x[5], x[6], x[0]))

# 深档低位（跌停+MA60下）子集：只有海南发展
print("\n=== 深档低位（跌停+MA60下）今日唯一标的 ===")
for c in ["002163"]:
    g = q.get(c)
    if g:
        print("  %s %s  今开 %.2f  昨收 %.2f  现价 %.2f  %+.2f%%" %
              (nm.get(c, ""), c, g["open"], g["prev"], g["now"], (g["now"] / g["open"] - 1) * 100))

# 对比：今天实际推给你的 5 只
print("\n=== 对比：作战单今天实际推的 5 只（脏数据产物）===")
tot = []
for c in ["600712", "002059", "000759", "003002", "003004"]:
    g = q.get(c)
    if g:
        r = (g["now"] / g["open"] - 1) * 100
        tot.append(r)
        print("  %-8s %s  今开 %.2f → 现 %.2f  %+.2f%%" % (nm.get(c, ""), c, g["open"], g["now"], r))
if tot:
    print("  等权 %+.2f%%" % (sum(tot) / len(tot)))
