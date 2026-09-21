"""深档低位生产规则终审（2026-09-22 凌晨夜班）。

背景：ops_briefing 每天 9:25 向用户推「深档低位」名单，口径=当日 ≤-9.5% 且收<MA60（剔ST/退），
闸门=成簇日≥5只才出手，引用数字 T+1 57.8%/赔率1.34、T+5 69.7%/赔率1.56（来源=早期研究）。
但 2026-09-19 周审计其底座主张 LIMITDOWN_LOW_MA60 T+5 滚动边际 -1.57pp → DECAYING。
生产规则与审计状态打架，今晚用刚补全的 big_kcache（至 2026-09-21）做终审：

  A. 全 8 年逐事件重算：n/胜率/均值/赔率/中位，T+1/3/5/10/20 衰减曲线（入场=次日开盘，净-0.15%）
  B. 成簇≥5 闸门消融：全部事件 vs 成簇日事件 vs 零星日事件——验证闸门到底加分还是减分
  C. 逐年（2019-2026）× 四 regime 分桶——近一年是否已死（对齐审计 DECAYING）
  D. 双面板：生产镜像（60/00 现存主板剔ST/退）vs 含退市股（幸存者偏差校正）
  E. 位置匹配随机对照（同票 MA60下 随机日，同入出场口径，2 万样本）

判决标准：成簇日 T+5 胜率≥55% 且均值>随机对照+0.5pp 且近一年不转负 → 生产规则维持；
否则 ops_briefing 引用数字撤下/降级。
"""
import collections
import glob
import json
import math
import random
import statistics

import sys
sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

ROOT = "/opt/data/fenjue"
FEE = 0.0015  # 往返净口径
HORIZONS = [1, 3, 5, 10, 20]

# ---------- 名称/宇宙 ----------
names = {str(s["code"]).zfill(6): s.get("name", "")
         for s in json.loads(open(f"{ROOT}/data/main_board_codes.json").read())["stocks"]}
delisted = set(json.loads(open(f"{ROOT}/data/delisted_codes.json").read())) \
    if glob.glob(f"{ROOT}/data/delisted_codes.json") else set()

# regime 轴
tl = json.loads(open(f"{ROOT}/data/regime_timeline_hcap.json").read())
REGIME = {t["date"]: t["regime"] for t in tl}


def odds_ratio(rs):
    w = [r for r in rs if r > 0]
    l = [r for r in rs if r <= 0]
    if not w or not l:
        return None
    return (statistics.mean(w)) / abs(statistics.mean(l))


def stat_block(rs):
    if not rs:
        return {"n": 0}
    out = {"n": len(rs)}
    for h in HORIZONS:
        xs = [r[h] for r in rs if r.get(h) is not None]
        if xs:
            m = statistics.mean(xs)
            sd = statistics.stdev(xs) if len(xs) > 1 else 0
            out[f"T+{h}"] = {"wr": round(sum(1 for x in xs if x > 0) / len(xs), 4),
                             "mean": round(m, 5), "med": round(statistics.median(xs), 5),
                             "odds": (round(odds_ratio(xs), 3) if odds_ratio(xs) else None),
                             "t": round(m / (sd / math.sqrt(len(xs))), 1) if sd > 0 else None,
                             "n": len(xs)}
    return out


def main():
    stocks = lp.load_universe()
    print(f"universe {len(stocks)}", flush=True)

    # ---------- 事件收集（生产口径：pct<=-9.5 且 c<ma60）----------
    # 先按日聚合簇数（簇判定用全库全部主板票，与生产 deep_low_scan 一致：60/00 剔 ST/退）
    cluster = collections.Counter()
    events_all = []
    for code, d in stocks.items():
        if code[:2] not in ("60", "00"):
            continue
        is_delist = code in delisted
        nm = names.get(code, "")
        st_excl = ("ST" in nm or "退" in nm)  # 生产口径（当前名）
        for i in range(60, d["n"] - 1):
            ma = d["ma60"][i]
            if ma is None or d["c"][i - 1] <= 0:
                continue
            p0 = d["c"][i] / d["c"][i - 1] - 1
            if p0 <= -0.095 and d["c"][i] < ma:
                date = d["date"][i]
                if not st_excl:
                    cluster[date] += 1
                events_all.append((code, i, date, is_delist, st_excl))
    print(f"raw events {len(events_all)}, cluster days {len(cluster)}", flush=True)

    # ---------- 收益计算 ----------
    def compute(evs):
        out = []
        for code, i, date, _, _ in evs:
            d = stocks[code]
            if i + 1 >= d["n"]:
                continue
            entry = d["o"][i + 1]
            if entry <= 0:
                continue
            rec = {"code": code, "date": date, "regime": REGIME.get(date, "?"),
                   "year": date[:4], "cluster": cluster.get(date, 0)}
            for h in HORIZONS:
                j = i + h
                rec[h] = (d["c"][j] / entry - 1 - FEE) if j < d["n"] else None
            out.append(rec)
        return out

    ev_prod = [e for e in events_all if e[0] in names and not e[4]]  # 生产镜像：现存主板且剔 ST/退
    ev_full = list(events_all)  # 含退市面板：全部 60/00（退市票无现行名，无法剔 ST——口径注记）

    r_prod = compute(ev_prod)
    r_full = compute(ev_full)
    print(f"computed prod={len(r_prod)} full={len(r_full)}", flush=True)

    # ---------- 对照：位置匹配随机（同票 MA60下 随机日）----------
    rnd = random.Random(7)
    ctrl = []
    pool = [(c, i) for c, d in stocks.items() if c[:2] in ("60", "00")
            for i in range(60, d["n"] - 21)
            if d["ma60"][i] is not None and d["c"][i] < d["ma60"][i]]
    for _ in range(20000):
        c, i = pool[rnd.randrange(len(pool))]
        d = stocks[c]
        entry = d["o"][i + 1]
        if entry <= 0:
            continue
        ctrl.append({h: (d["c"][i + h] / entry - 1 - FEE) for h in HORIZONS})
    print(f"control {len(ctrl)}", flush=True)

    # ---------- 分桶 ----------
    def bucket(recs, key):
        g = collections.defaultdict(list)
        for r in recs:
            g[key(r)].append(r)
        return {k: stat_block(v) for k, v in sorted(g.items())}

    result = {
        "口径": "信号日 pct<=-9.5% 且 c<MA60（生产 deep_low_scan 同口径），入场次日开盘，净-0.15%",
        "cluster≥5闸门定义": "当日全库同信号票数（剔ST/退）≥5",
        "生产镜像面板": {
            "全部事件": stat_block(r_prod),
            "成簇日(≥5)": stat_block([r for r in r_prod if r["cluster"] >= 5]),
            "零星日(<5)": stat_block([r for r in r_prod if 0 < r["cluster"] < 5]),
            "逐年": bucket(r_prod, lambda r: r["year"]),
            "regime": bucket(r_prod, lambda r: r["regime"]),
            "逐年_仅成簇日": bucket([r for r in r_prod if r["cluster"] >= 5], lambda r: r["year"]),
        },
        "含退市面板": {
            "全部事件": stat_block(r_full),
            "成簇日(≥5)": stat_block([r for r in r_full if r["cluster"] >= 5]),
        },
        "位置匹配随机对照(MA60下)": stat_block(ctrl),
    }
    out = f"{ROOT}/data/deep_low_production_audit_20260922.json"
    json.dump(result, open(out, "w"), ensure_ascii=False, indent=1)
    print("saved", out)

    # ---------- 终端摘要 ----------
    for panel in ("生产镜像面板", "含退市面板"):
        print(f"\n═══ {panel} ═══")
        for grp, blk in result[panel].items():
            if isinstance(blk, dict) and "T+5" in blk:
                t1, t5 = blk.get("T+1", {}), blk["T+5"]
                print(f"  {grp:<12} n={blk['n']:>6}  T+1 {t1.get('wr', 0) * 100:.1f}%/{t1.get('mean', 0) * 100:+.2f}% 赔率{t1.get('odds')}  "
                      f"T+5 {t5['wr'] * 100:.1f}%/{t5['mean'] * 100:+.2f}% 赔率{t5.get('odds')} t={t5.get('t')}")
    cb = result["位置匹配随机对照(MA60下)"]
    print(f"\n对照: T+1 {cb['T+1']['wr'] * 100:.1f}%/{cb['T+1']['mean'] * 100:+.2f}%  T+5 {cb['T+5']['wr'] * 100:.1f}%/{cb['T+5']['mean'] * 100:+.2f}%")
    print("\n逐年(生产镜像,全部事件) T+5:")
    for y, blk in result["生产镜像面板"]["逐年"].items():
        if "T+5" in blk:
            print(f"  {y}: n={blk['n']:>5} {blk['T+5']['wr'] * 100:.1f}%/{blk['T+5']['mean'] * 100:+.2f}%")
    print("\nregime(生产镜像) T+5:")
    for g, blk in result["生产镜像面板"]["regime"].items():
        if "T+5" in blk:
            print(f"  {g}: n={blk['n']:>5} {blk['T+5']['wr'] * 100:.1f}%/{blk['T+5']['mean'] * 100:+.2f}%")


if __name__ == "__main__":
    main()
