#!/usr/bin/env python3
"""深档低位（跌停+MA60下）影子对账 v2：用修好的 kcache 重算每日应筛名单 + T+1 收益，
并与 HiThink 官方跌停池交叉验证名单完整性。

口径（与 skill / ops_briefing 一致）：
  信号日 si = 当日收盘跌幅 <= -9.5% 且 收盘 < MA60
  入场 = 次日 open；出场 = 再下一交易日 close（持有 1 日，含费 -0.15%）
  剔除：次日一字跌停锁死（gap<=-9.5% 且振幅<1%）、次日一字涨停（gap>=+9.5%）
"""
import json, glob, os, statistics as st

KC = "/opt/data/fenjue/data/big_kcache"
HI = "/opt/data/fenjue/data/hithink"
FEE = 0.0015
SIGNAL_DAYS = ["2026-09-11", "2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17"]


def load():
    out = {}
    for fp in glob.glob(KC + "/*.json"):
        code = fp.rsplit("/", 1)[-1][:-5]
        if code[:2] not in ("60", "00"):
            continue
        try:
            ks = json.load(open(fp))
        except Exception:
            continue
        if len(ks) >= 65:
            out[code] = ks
    return out


def hithink_down(d):
    f = "%s/%s/limit_down_pool.json" % (HI, d)
    if not os.path.exists(f):
        return None
    try:
        data = json.load(open(f))
        items = data.get("data", {}).get("item") or []
        return {str(i["ticker"]).zfill(6): i.get("name", "") for i in items}
    except Exception:
        return None


def main():
    stocks = load()
    last = max(ks[-1]["date"] for ks in stocks.values())
    fresh = sum(1 for ks in stocks.values() if ks[-1]["date"] >= "2026-09-17")
    print("宇宙 %d 只主板票；kcache 最新 %s；已更新到 9/17 的 %d 只" % (len(stocks), last, fresh))
    if fresh < len(stocks):
        print("⚠️ 缓存尚未全量刷新，下面结果只覆盖已刷新的票（等跑完再终判）\n")

    grand = []
    for sd in SIGNAL_DAYS:
        picks = []
        for code, ks in stocks.items():
            idx = {k["date"]: j for j, k in enumerate(ks)}
            si = idx.get(sd)
            if si is None or si < 60 or si + 2 >= len(ks):
                continue
            pc = ks[si - 1]["close"]
            if pc <= 0:
                continue
            chg = ks[si]["close"] / pc - 1
            ma60 = sum(k["close"] for k in ks[si - 59:si + 1]) / 60
            if not (chg <= -0.095 and ks[si]["close"] < ma60):
                continue
            e = ks[si + 1]["open"]
            if e <= 0:
                continue
            gap = e / ks[si]["close"] - 1
            amp = (ks[si + 1]["high"] - ks[si + 1]["low"]) / ks[si]["close"]
            if gap >= 0.095 or (gap <= -0.095 and amp < 0.01):
                picks.append({"code": code, "chg": chg * 100, "r": None, "why": "不可成交"})
                continue
            x = ks[si + 2]["close"]
            picks.append({"code": code, "chg": chg * 100, "e": e, "x": x,
                          "r": (x / e - 1) * 100 - FEE * 100, "why": ""})
        ok = [p for p in picks if p["r"] is not None]
        hit = hithink_down(sd)
        print("信号日 %s：深档合格 %d 只（可成交 %d）%s"
              % (sd, len(picks), len(ok),
                 "" if hit is None else " · HiThink 跌停池 %d 只" % len(hit)))
        if hit is not None:
            mine = {p["code"] for p in picks}
            miss = sorted(set(hit) - mine)
            extra = sorted(mine - set(hit))
            if miss:
                print("     跌停池有、我名单没有（%d 只，看是否被 MA60 过滤）: %s"
                      % (len(miss), "、".join(miss[:12])))
            if extra:
                print("     我名单有、跌停池没有（%d 只，收盘 -9.5%% ~ -9.99%% 非封死跌停）: %s"
                      % (len(extra), "、".join(extra[:12])))
        for p in sorted(picks, key=lambda z: (z["r"] is None, z["r"] if z["r"] is not None else 0)):
            if p["r"] is None:
                print("     %-7s 信号日 %+6.2f%%   %s" % (p["code"], p["chg"], p["why"]))
            else:
                print("     %-7s 信号日 %+6.2f%%   买 %.2f → 卖 %.2f   %+.2f%%"
                      % (p["code"], p["chg"], p["e"], p["x"], p["r"]))
        if ok:
            rs = [p["r"] for p in ok]
            m = st.mean(rs)
            print("   └ 等权 %+.2f%%  胜率 %.1f%%  n=%d\n"
                  % (m, 100 * sum(1 for x in rs if x > 0) / len(rs), len(rs)))
            grand.append((sd, m, len(ok), 100 * sum(1 for x in rs if x > 0) / len(rs)))
        else:
            print("   └ 无可成交样本\n")

    if grand:
        cum = 1.0
        for _, m, _, _ in grand:
            cum *= (1 + m / 100)
        print("=== 汇总（等权、扣费 0.15%/单）===")
        for sd, m, n, w in grand:
            print("  %s  %+6.2f%%  胜率 %3.0f%%  n=%d" % (sd, m, w, n))
        print("  逐日平均 %+.2f%%   滚动复利 %+.2f%%"
              % (st.mean([m for _, m, _, _ in grand]), (cum - 1) * 100))


if __name__ == "__main__":
    main()
