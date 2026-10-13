#!/usr/bin/env python3
"""watchlist 关键位刷新（config/watchlist.json，哨兵数据源）。

背景：watchlist 的 levels 是手工设的，会随行情失真（实测 2026-10-08：601137 的
「19.00 短线防线」在 9/30 收盘 18.91 就已破，几天没人动）。本脚本按当日行情重算。

**positions.levels**：从 big_kcache 前复权序列算 MA5/10/20/60/120 + 近20/60日高 +
持仓成本，取现价 ±15% 带内、按「离现价的远近」排序去重（两条位相距 <1% 视为一条，
保留优先级高的），最多 6 条。标签决定雷达报警方向：含「防线/低点/止损/作废」= 跌破报警，
其余 = 突破报警；均线按与现价的位置关系定方向（价上方=修复确认，价下方=支撑防线）。

**anchors.buy**：股息锚买入线 = 每股分红 / 4.5%。分红口径取「防过渡年双计」的保守值：
近 12 个月实施派息现金流 vs 再前 12 个月现金流，取**较小者**。
为什么不用纯 TTM：公司从「一年一派」转「中期+年度」的过渡年，365 天窗会同时装进
上一年度派息和本年度中期派息 —— 实锤 2026-10-08：成都银行窗内 9.21+4.89=14.1 元/10股
（旧线 20.47 隐含 9.21），杭州银行窗内装进 3 期 11.2 元/10股（实际 run-rate 7.4）。
纯 TTM 会把买入线抬到 31.33 / 16.44，制造永远在买入区的假信号。

用法：python3 engine/watchlist_refresh.py          # dry-run 打印 before/after
      python3 engine/watchlist_refresh.py --write  # 落盘（备份 .json.bak-YYYYMMDD）
"""
import json
import re
import shutil
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
sys.path.insert(0, str(ROOT / "engine"))
sys.path.insert(0, "/opt/data/python-libs")

WATCH = ROOT / "config/watchlist.json"
DIV_CACHE = ROOT / "data/dividend_annual_cache.json"
BAND = 0.20          # 现价 ±20% 才进哨兵（保留下方深支撑与上方突破位）
DEDUP = 0.010        # 两条位相距 <1% 视为同一条
MAX_LEVELS = 6
PRIORITY = ["MA60", "MA20", "MA10", "MA5", "MA120", "20日低点", "60日低点",
            "20日高点", "60日高点", "成本位"]


def quotes(codes: list[str]) -> dict[str, dict]:
    """新浪批量快照。"""
    syms = ",".join(("sh" if c.startswith("6") else "sz") + c for c in codes)
    req = urllib.request.Request(f"https://hq.sinajs.cn/list={syms}",
                                 headers={"Referer": "https://finance.sina.com.cn"})
    raw = urllib.request.urlopen(req, timeout=12).read().decode("gbk", "ignore")
    out = {}
    for line in raw.splitlines():
        if '="' not in line:
            continue
        code = line.split("=")[0].split("_")[-1][2:]
        p = line.split('"')[1].split(",")
        if len(p) < 10 or not p[0]:
            continue
        out[code] = {"name": p[0], "open": float(p[1]), "prev": float(p[2]),
                     "price": float(p[3]), "high": float(p[4]), "low": float(p[5])}
    return out


def klines(code: str) -> list[dict]:
    fp = ROOT / "data/big_kcache" / f"{code}.json"
    return json.loads(fp.read_text()) if fp.exists() else []


def ma(closes: list[float], n: int) -> float | None:
    return sum(closes[-n:]) / n if len(closes) >= n else None


def build_levels(code: str, price: float, cost: float | None) -> dict:
    ks = klines(code)
    if not ks:
        return {}
    closes = [r["close"] for r in ks]
    cands: list[tuple[str, float, str]] = []
    for n in (5, 10, 20, 60, 120):
        v = ma(closes, n)
        if v:
            lab = f"MA{n}修复确认" if v > price else f"MA{n}支撑防线(收破走)"
            cands.append((f"MA{n}", v, lab))
    cands += [("20日低点", min(r["low"] for r in ks[-20:]), "20日低点防线"),
              ("20日高点", max(r["high"] for r in ks[-20:]), "20日高点(突破看多)")]
    if len(ks) >= 60:
        cands.append(("60日低点", min(r["low"] for r in ks[-60:]), "60日低点防线"))
        cands.append(("60日高点", max(r["high"] for r in ks[-60:]), "60日高点(突破看多)"))
    if cost:
        cands.append(("成本位", cost, "成本位防线(收破走)"))
    inband = [c for c in cands if price * (1 - BAND) <= c[1] <= price * (1 + BAND)]
    # 按离现价的远近排序（哨兵管近场），同位去重保留优先级高的
    keep: list[tuple[str, float, str]] = []
    for key, v, lab in sorted(inband, key=lambda x: abs(x[1] - price)):
        hit = next((k for k in keep if abs(v - k[1]) / v < DEDUP), None)
        if hit:
            if PRIORITY.index(key) < PRIORITY.index(hit[0]):
                keep[keep.index(hit)] = (key, round(v, 2), lab)
            continue
        keep.append((key, round(v, 2), lab))
    keep = sorted(keep, key=lambda x: x[1])[:MAX_LEVELS]
    return {f"{v:.2f}": lab for _, v, lab in keep}


def div_events(code: str) -> list[tuple[str, float]]:
    """实施派息明细 [(除权除息日, 元/10股)]，7 天磁盘缓存。"""
    cache = json.loads(DIV_CACHE.read_text()) if DIV_CACHE.exists() else {}
    ent = cache.get(code)
    if ent and time.time() - ent.get("ts", 0) < 7 * 86400:
        return [(d, v) for d, v in ent["events"]]
    try:
        import akshare as ak
        import pandas as pd
        df = ak.stock_history_dividend_detail(symbol=code, indicator="分红")
        df = df[df["进度"] == "实施"].copy()
        df["_d"] = pd.to_datetime(df["除权除息日"], errors="coerce")
        df = df[df["_d"].notna() & (df["派息"] > 0)].sort_values("_d")
        ev = [(r["_d"].date().isoformat(), float(r["派息"])) for _, r in df.iterrows()]
    except Exception:
        return [(d, v) for d, v in ent["events"]] if ent else []
    cache[code] = {"events": ev, "ts": time.time()}
    DIV_CACHE.write_text(json.dumps(cache))
    return ev


def div_annual(code: str) -> tuple[float | None, str]:
    """稳健年化每股分红。规则（2026-10-08 定）：

    1. 近 12 个月实施派息现金流 vs 再前 12 个月，**同量级（≤+15%）就用近 12 月**——
       正常年份的股息增长不该被当成异常去惩罚（江苏/上海/渝农/成都的季度节奏都属此类）。
    2. 明显偏高（>+15%）＝窗口被污染（一年一派转「中期+年度」的过渡年，或派息日逐年前移
       导致 365 天窗多装一期）→ 改用「按上一次年派息期数取最近 N 笔」的 run-rate，
       并加 +15% 上限防跳变。实锤：成都银行窗内装进 9.21(2025年度)+4.89(2026中期)，
       纯 TTM 1.41 元/股 = 7.3% 息率会把买入线抬到 31.33（永远在买入区）；
       杭州银行窗内装进 3 期 11.2 元/10股。

    口径目的＝阈值（现价≤线 ⇔ 息率≥4.5%），宁可严不可松。
    """
    ev = div_events(code)
    if not ev:
        return None, "无分红数据"
    now = datetime.now().date()
    y1 = [(d, v) for d, v in ev if (now - datetime.fromisoformat(d).date()).days <= 365]
    y2 = [(d, v) for d, v in ev if 365 < (now - datetime.fromisoformat(d).date()).days <= 730]
    ttm, prev = sum(v for _, v in y1) / 10, sum(v for _, v in y2) / 10
    n_prev = len(y2) or 1
    if prev and ttm <= prev * 1.15:
        return round(ttm, 4), (f"近12月现金流 {ttm:.4f}（{len(y1)} 笔，"
                               f"与再前12月 {prev:.4f} 同量级=口径干净）")
    recent = sorted(ev, key=lambda x: x[0])
    if n_prev == 1:
        # 历史是一年一派 → 窗口内两笔＝年度派息＋新中期，年度金额取较大那笔
        # （成都银行 9.21 年度 vs 4.89 中期；美的 38.0 年度 vs 5.0 中期）
        dps = max(v for _, v in y1 or recent[-1:]) / 10
        how = f"取窗口内年度笔（较大量，{len(y1)} 笔中）"
    else:
        dps = sum(v for _, v in recent[-n_prev:]) / 10
        how = f"最近 {n_prev} 笔之和"
    capped = ""
    if prev and dps > prev * 1.15:
        dps, capped = prev * 1.15, "（受再前12月+15%上限约束）"
    return round(dps, 4), (f"run-rate {dps:.4f}={how}{capped}"
                           f"（近12月 {ttm:.4f} 疑过渡年双计/派息日漂移，"
                           f"再前12月 {prev:.4f}）")


def main() -> int:
    write = "--write" in sys.argv
    write_anchors = "--write-anchors" in sys.argv
    w = json.loads(WATCH.read_text())
    codes = [p["code"] for p in w["positions"]] + [a["code"] for a in w["anchors"]]
    q = quotes(sorted(set(codes)))
    rows, changed = [], 0

    for p in w["positions"]:
        d = q.get(p["code"])
        if not d:
            rows.append(f"⚠️ {p['name']} 取价失败，跳过")
            continue
        m = re.search(r"成本([0-9.]+)", p.get("note", ""))
        new = build_levels(p["code"], d["price"], float(m.group(1)) if m else None)
        old = p["levels"]
        if new != old:
            changed += 1
        rows.append(f"\n▌{p['name']}({p['code']}) 现价 {d['price']}"
                    f"（昨收 {d['prev']}，{(d['price']/d['prev']-1)*100:+.2f}%）")
        for lv in sorted(set(list(old) + list(new)), key=float):
            o, n = old.get(lv, "—"), new.get(lv, "—")
            rows.append(f"   {'  ' if o == n else '→ '}{lv:>8}  旧 {o:<24} 新 {n}")
        if write:
            p["levels"] = new

    rows.append("\n▌股息锚买入线（= 稳健年化每股分红/4.5%；现价≤线=在买入区）")
    for a in w["anchors"]:
        d = q.get(a["code"])
        dps, why = div_annual(a["code"])
        if dps is None:
            rows.append(f"   ⚠️ {a['name']} 取数失败，保留旧线 {a['buy']}")
            continue
        buy = round(dps / 0.045, 2)
        diff = (buy / a["buy"] - 1) * 100
        tag = "同" if abs(diff) < 0.6 else f"变 {diff:+.1f}%"
        px = f"{d['price']:.2f}" if d else "?"
        rows.append(f"   {a['name']}({a['code']}) 现价{px:>7} 旧线{a['buy']:>7} 新线{buy:>7} {tag:<9} [{why}]")
        if write_anchors and abs(diff) >= 0.6:
            changed += 1
            a["buy"] = buy

    head = f"watchlist 刷新（{'落盘' if write else 'dry-run'}） {datetime.now():%Y-%m-%d %H:%M} | 变更 {changed} 项"
    print(head + "\n" + "=" * len(head))
    print("\n".join(rows))
    if write:
        # 备份名带时分秒：同日多次运行不能互相覆盖（2026-10-08 踩过：第二次运行
        # 把「改动前的原件」覆盖成了「中间态」，回滚点丢失）
        bak = WATCH.with_suffix(f".json.bak-{datetime.now():%Y%m%d-%H%M%S}")
        shutil.copy(WATCH, bak)
        WATCH.write_text(json.dumps(w, ensure_ascii=False, indent=1))
        print(f"\n✅ 已写入 {WATCH}（备份 {bak.name}）")
    else:
        print("\n（dry-run：加 --write 落盘）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
