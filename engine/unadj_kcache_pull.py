#!/usr/bin/env python3
"""engine/unadj_kcache_pull.py — 不复权日K拉取（任务E1，2026-09-13）

【口径】
- 不复权原始成交价：baostock adjustflag="3"，含除权/除息当日价格跳空，
  绝对价位跨分红期可比，专用于做红利策略的「息率分母」。
- 与 data/big_kcache/（前复权，adjustflag="2"）严格区分：前复权序列把历史
  价格按累计分红/送转整体下调，拿它当分母会系统性偏小 → 历史时点息率被高估。

【数据源】
- 宇宙清单：data/dividend_history.json（≥3 个年度有分红）
            + data/industry_map.json（名称含 ST / 退 剔除）
- 行情：baostock query_history_k_data_plus，frequency="d"，adjustflag="3"，
        字段 date,open,high,low,close,volume,amount，区间 2018-01-01 ~ 今日

【输出】
- data/big_kcache_unadj/<code>.json
  schema 同 big_kcache：[{"date","open","high","low","close","volume","amount"}, ...]
- data/unadj_pull_failed.json  失败清单 [{"code","err"}]

【已知限制】
1) baostock 必须单进程串行（并发会被封号），每股 sleep 0.15s；
2) 断点判据「本地最后一行日期 >= 基准最近交易日」，基准默认取
   data/big_kcache/000001.json 的最后一根，可用 --last=YYYY-MM-DD 覆盖；
   基准取不到则退化为今日，会触发全量重拉；
3) 停牌/退市票的区间可能短于 [2018-01-01, 今日]；
4) 不复权价含除权跳空，本缓存只用于息率分母，收益计算仍走前复权；
5) 北交所代码（4/8 开头）用 bj. 前缀，baostock 若不支持会进失败清单。
"""
import os
import sys
import json
import time
import datetime

import sys as _sys
_sys.path.insert(0, "/opt/data/python-libs")  # baostock 在这里（对齐 update_kcache.py 惯例，K3审查修）
import baostock as bs

ROOT = "/opt/data/fenjue"
D = ROOT + "/data"
OUTDIR = D + "/big_kcache_unadj"
FAILD = D + "/unadj_pull_failed.json"
START_DATE = "2018-01-01"
SLEEP = 0.15
FIELDS = "date,open,high,low,close,volume,amount"


def y4(dt):
    return dt[:4]


def argv_get(prefix, default=""):
    for a in sys.argv:
        if a.startswith(prefix):
            return a.split("=", 1)[1]
    return default


def ref_last_trade_date():
    x = argv_get("--last=")
    if x:
        return x
    try:
        ks = json.load(open(f"{D}/big_kcache/000001.json"))
        if ks:
            return ks[-1]["date"]
    except Exception:
        pass
    return datetime.date.today().isoformat()


def bs_code(code):
    h = code[0]
    if h == "6":
        return "sh." + code
    if h in ("4", "8"):
        return "bj." + code
    return "sz." + code


def to_f(s):
    try:
        return float(s)
    except Exception:
        return None


def f0(s):
    v = to_f(s)
    return 0.0 if v is None else v


def pull(code, end_date):
    rs = bs.query_history_k_data_plus(
        bs_code(code), FIELDS,
        start_date=START_DATE, end_date=end_date,
        frequency="d", adjustflag="3")
    if rs.error_code != "0":
        raise RuntimeError("query_err %s %s" % (rs.error_code, rs.error_msg))
    bars = []
    while rs.next():
        r = rs.get_row_data()
        if len(r) < 7 or not r[0]:
            continue
        close = to_f(r[4])
        if close is None:
            continue
        bars.append({
            "date": r[0],
            "open": f0(r[1]),
            "high": f0(r[2]),
            "low": f0(r[3]),
            "close": close,
            "volume": f0(r[5]),
            "amount": f0(r[6]),
        })
    return bars


def build_universe():
    names = {c: v.get("name", "") for c, v in json.load(open(f"{D}/industry_map.json")).items()}
    divh = json.load(open(f"{D}/dividend_history.json"))
    uni = []
    for c, recs in divh.items():
        nm = names.get(c, "")
        if "ST" in nm or "退" in nm:
            continue
        try:
            if len({y4(dt) for dt, _ in recs}) >= 3:
                uni.append(c)
        except Exception:
            continue
    uni.sort()
    return uni


def main():
    os.makedirs(OUTDIR, exist_ok=True)
    uni = build_universe()
    ref = ref_last_trade_date()
    end_date = datetime.date.today().isoformat()
    print("宇宙: %d 只  断点基准=%s  请求区间=%s~%s" % (len(uni), ref, START_DATE, end_date),
          file=sys.stderr)

    lg = bs.login()
    if lg.error_code != "0":
        print("baostock login 失败: %s %s" % (lg.error_code, lg.error_msg), file=sys.stderr)
        sys.exit(1)

    ok = skip = fail = 0
    failed = []
    try:
        for i, code in enumerate(uni, 1):
            path = os.path.join(OUTDIR, code + ".json")
            if os.path.exists(path):
                try:
                    ks = json.load(open(path))
                    if ks and ks[-1].get("date", "") >= ref:
                        skip += 1
                        continue
                except Exception:
                    pass
            try:
                bars = pull(code, end_date)
                if not bars:
                    raise RuntimeError("empty_result")
                with open(path, "w") as f:
                    json.dump(bars, f, ensure_ascii=False, separators=(",", ":"))
                ok += 1
            except Exception as e:
                fail += 1
                failed.append({"code": code, "err": str(e)[:200]})
            time.sleep(SLEEP)
            if i % 200 == 0:
                print("[%d/%d] ok=%d skip=%d fail=%d" % (i, len(uni), ok, skip, fail),
                      file=sys.stderr)
    finally:
        bs.logout()

    with open(FAILD, "w") as f:
        json.dump(failed, f, ensure_ascii=False, indent=1)

    print("成功=%d 跳过=%d 失败=%d 宇宙=%d" % (ok, skip, fail, len(uni)))
    if failed:
        print("失败样例:", [x["code"] for x in failed[:10]], file=sys.stderr)


if __name__ == "__main__":
    main()
