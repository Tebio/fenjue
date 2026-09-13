#!/usr/bin/env python3
"""engine/zhaban_daily.py — 任务D：炸板「浅炸」规则影子盘日更基建

口径
----
信号（完全复用 engine/zhaban_features.py / engine/zhaban_m60_fill.py 的日K重判，
      m60 聚合不复权日K）：
    昨日 收/前收-1 >= +9.8%（涨停）
    且 今日 开/昨收-1 >= +5%
    且 今开幅度 ∈ [6%, 7%)
    且 首30分钟量能比 < 1.0（今日 <=10:30 的那根 60min bar 量 / 昨日 <=10:30 的那根 bar 量）
挂单 / 成交（挂 +7% 限价，逐今日 60min bar 顺序判定）：
    限价 = 昨收 × 1.07；bar.open <= 限价 → 按 bar.open 成交；
    bar.low <= 限价 → 按限价成交；今日全部 bar 未触价 → 未成交（fill_px=null，标 unfilled，不再追踪）
出场：T+1 收盘 / 成交价 - 1 - 0.0015（手续费 0.0015，单边一次性扣）
回填：以 big_kcache 前复权日K 的「登记日之后第一根日K」close 计 t1_close_ret。
      ★ fill_px 来自 m60（不复权）而回填 close 来自 big_kcache（前复权），跨分红期存在口径差——
      接受并在文件头注记（与任务B/B5 影子同口径）。

数据源（只读）
--------------
    /opt/data/fenjue/data/m60_cache/<code>.json   不复权 60min bar [{"day":"YYYY-MM-DD HH:MM", open/high/low/close/volume}]
    /opt/data/fenjue/data/big_kcache/<code>.json  前复权日K（仅取比率，绝对价不可跨分红期比）
    /opt/data/fenjue/data/industry_map.json       名称映射（宽松解析，失败 name=None）

输出
----
    /opt/data/fenjue/data/zhaban_shadow.jsonl         影子账本（每行一条登记，整文件原子重写）
    /opt/data/fenjue/data/zhaban_shadow_summary.json  汇总
    stdout                                            紧凑汇报

随机对照
--------
    每笔已回填登记配 1 只随机对照（big_kcache 全量 code 池随机抽，seed 固定 SEED=20260913，
    以 "SEED|date|code" 派生 RNG 保证确定性），口径 = 同一交易日开盘买 → 次交易日收盘卖 - 0.0015。
    对照仅作同期市场基线，非同规则同价位对照。

已知限制
--------
    L1 前复权（回填 close）/ 不复权（成交价）跨分红口径差，与 B5 影子一致。
    L2 60min 粒度：秒级触碰 / 薄队列不可成交无法识别，成交判定偏乐观。
    L3 首30分钟量能比取「今日 <=10:30 的最晚一根 bar」与「昨日同口径 bar」之比（与 B 一致）。
    L4 尾部快速预筛假设 m60 文件按时间升序追加；若数据源乱序请加 --full-scan。
    L5 影子盘为前向证据，样本小，不做显著性结论。
    L6 随机对照只对齐「开盘买→次交易日收盘卖」，未对齐 +7% 限价挂单机制。
"""
import argparse
import bisect
import json
import random
import re
import statistics as st
from collections import defaultdict
from datetime import date as _date, datetime
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
DATA = ROOT / "data"
M60 = DATA / "m60_cache"
BIGK = DATA / "big_kcache"
LEDGER = DATA / "zhaban_shadow.jsonl"
SUMMARY = DATA / "zhaban_shadow_summary.json"
IMAP = DATA / "industry_map.json"

FEE = 0.0015
SEED = 20260913
LIMIT_PCT = 7.0
GAP_LO, GAP_HI = 6.0, 7.0
V30_MAX = 1.0
LAST_BAR_MIN = "14:30"          # 当日最后一根 bar 早于此时刻 → 视为盘中/数据未就绪，不登记
TAIL_BYTES = 16384
CODE_RE = re.compile(r"^\d{6}(\.(SH|SZ|BJ))?$")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")

_BK = {}                        # code -> (sorted dates, {date: {open, close}})


# ---------------------------------------------------------------- 基础工具
def load_json(fp):
    try:
        return json.loads(Path(fp).read_text(encoding="utf-8"))
    except Exception:
        return None


def hhmm(day_str):
    """'YYYY-MM-DD HH:MM' -> 'HH:MM'；无时间字段返回 None（拒绝全日数据）。"""
    if isinstance(day_str, str) and len(day_str) >= 16 and day_str[10] == " ":
        return day_str[11:16]
    return None


def daily_bars(rows):
    """m60 → 日K（不复权），bars 按时间升序。判定口径与 zhaban_features 完全一致。"""
    days = defaultdict(list)
    for r in rows:
        try:
            days[r["day"][:10]].append(r)
        except Exception:
            continue
    out = []
    for dt in sorted(days):
        bs = sorted(days[dt], key=lambda r: r["day"])
        try:
            out.append({"date": dt,
                        "open": float(bs[0]["open"]),
                        "high": max(float(b["high"]) for b in bs),
                        "low": min(float(b["low"]) for b in bs),
                        "close": float(bs[-1]["close"]),
                        "bars": bs})
        except Exception:
            continue
    return out


def first_bar(bars):
    """当日时间标签 <= 10:30 的最晚一根 bar（首 60 分钟）；无则 None。"""
    best, bt = None, None
    for b in bars:
        t = hhmm(b.get("day"))
        if t is None or t > "10:30":
            continue
        if bt is None or t > bt:
            bt, best = t, b
    return best


def tail_has_day(fp, day, nbytes=TAIL_BYTES):
    """尾部快速预筛：文件末尾 nbytes 内最后一个 YYYY-MM-DD 是否等于 day。"""
    try:
        sz = fp.stat().st_size
    except OSError:
        return False
    if sz <= 0:
        return False
    n = min(sz, nbytes)
    try:
        with open(fp, "rb") as f:
            f.seek(sz - n)
            blob = f.read(n).decode("utf-8", "ignore")
    except OSError:
        return False
    last = None
    for m in DATE_RE.finditer(blob):
        last = m.group(0)
    return last == day


def bk_load(code):
    """big_kcache 前复权日K -> (升序 dates, {date: {open, close}})，进程内缓存。"""
    if code in _BK:
        return _BK[code]
    rows = load_json(BIGK / (code + ".json"))
    ds, dd = [], {}
    if isinstance(rows, list):
        for r in rows:
            if not isinstance(r, dict):
                continue
            d = str(r.get("date") or "")[:10]
            if len(d) != 10 or d in dd:
                continue
            try:
                o = float(r["open"])
                c = float(r["close"])
            except Exception:
                continue
            dd[d] = {"open": o, "close": c}
            ds.append(d)
    ds.sort()
    _BK[code] = (ds, dd)
    return _BK[code]


def load_name_map():
    """industry_map.json 宽松解析 → {code: name}；疑似行业映射（value 重复度高）时宁缺毋滥返回 {}。"""
    raw = load_json(IMAP)
    m = {}
    if not isinstance(raw, dict):
        return m
    for k, v in raw.items():
        ks = str(k).strip()
        if not CODE_RE.match(ks):
            continue
        if isinstance(v, str):
            m[ks] = v
        elif isinstance(v, dict):
            for key in ("name", "名称", "stock_name", "简称"):
                if isinstance(v.get(key), str):
                    m[ks] = v[key]
                    break
    if len(m) >= 200 and len(set(m.values())) <= max(30, len(m) // 20):
        return {}
    return m


def name_of(names, code):
    for k in (code, code[:6]):
        if k in names:
            return names[k]
    return None


# ---------------------------------------------------------------- 账本 IO
def load_ledger():
    if not LEDGER.exists():
        return []
    recs, bad = [], 0
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            bad += 1
            continue
        if not isinstance(r, dict) or not r.get("date") or not r.get("code"):
            bad += 1
            continue
        r["date"] = str(r["date"])[:10]
        r["code"] = str(r["code"])
        recs.append(r)
    if bad:
        print("[warn] ledger 跳过坏行 %d" % bad)
    seen, out = set(), []
    for r in recs:
        k = (r["date"], r["code"])
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


def write_ledger(recs):
    DATA.mkdir(parents=True, exist_ok=True)
    recs.sort(key=lambda r: (str(r.get("date")), str(r.get("code"))))
    tmp = Path(str(LEDGER) + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp.replace(LEDGER)


def sanity_check(recs):
    """T+1 硬断言：任何已记 t1_date 的登记，出场日必须严格晚于登记日。"""
    n = 0
    for r in recs:
        td = r.get("t1_date")
        if td:
            assert str(td) > str(r["date"]), "T+1 断言失败: %s" % json.dumps(r, ensure_ascii=False)
            n += 1
    return n


# ---------------------------------------------------------------- 当日信号登记
def scan_today(today, names, known, full_scan=False):
    files = sorted(M60.glob("*.json"))
    new, diag = [], defaultdict(int)
    n_ready = n_closed = 0
    for fp in files:
        code = fp.stem
        if (today, code) in known:
            diag["dup_skip"] += 1
            continue
        if not full_scan and not tail_has_day(fp, today):
            continue
        try:
            rows = load_json(fp)
            if not rows:
                diag["unreadable"] += 1
                continue
            dk = daily_bars(rows)
            if len(dk) < 3:
                diag["too_short"] += 1
                continue
            if dk[-1]["date"] != today:
                diag["no_today_bar"] += 1
                continue
            n_ready += 1
            bars = dk[-1]["bars"]
            if not bars:
                diag["no_bars"] += 1
                continue

            # 零未来函数守卫：必须有「当日收盘 bar」，否则视为盘中/数据未就绪
            t_last = hhmm(bars[-1].get("day"))
            if t_last is None or t_last < LAST_BAR_MIN:
                diag["day_not_closed"] += 1
                continue
            n_closed += 1

            i = len(dk) - 1
            pc = float(dk[i - 1]["close"])          # 昨收（不复权）
            ppc = float(dk[i - 2]["close"])         # 前收
            if pc <= 0 or ppc <= 0:
                continue
            if (pc / ppc - 1.0) * 100.0 < 9.8:      # 昨日未涨停
                continue
            o = float(dk[i]["open"])
            if o <= 0:
                continue
            gap = (o / pc - 1.0) * 100.0
            if gap < 5.0:
                diag["gap_lt5"] += 1
                continue
            if not (GAP_LO <= gap < GAP_HI):        # 今开幅度必须 ∈ [6%, 7%)
                diag["gap_out_band"] += 1
                continue

            fb = first_bar(bars)
            yfb = first_bar(dk[i - 1]["bars"])
            if fb is None or yfb is None:
                diag["no_first30"] += 1
                continue
            v_now = float(fb["volume"])
            v_y = float(yfb["volume"])
            if v_y <= 0:
                diag["v30_undef"] += 1
                continue
            v30 = v_now / v_y
            if not (v30 < V30_MAX):                 # 首30分钟量能比 < 1.0
                diag["v30_ge1"] += 1
                continue

            # 挂 +7% 限价成交模拟（逐今日 bar，bar 全部属于 today，无未来函数）
            lim = pc * (1.0 + LIMIT_PCT / 100.0)
            fill_px, fill_time = None, None
            for b in bars:
                bt = hhmm(b.get("day"))
                try:
                    bo = float(b["open"])
                    bl = float(b["low"])
                except Exception:
                    continue
                if bo <= lim:
                    fill_px, fill_time = bo, bt
                    break
                if bl <= lim:
                    fill_px, fill_time = lim, bt
                    break
            if fill_px is not None:
                assert fill_time is not None, "成交 bar 时间缺失"
                assert "09:30" <= fill_time <= "15:00", "成交 bar 时间越界: %s" % fill_time

            new.append({
                "date": today,
                "code": code,
                "name": name_of(names, code),
                "fill_px": (round(fill_px, 4) if fill_px is not None else None),
                "fill_time": fill_time,
                "limit_px": round(lim, 4),
                "y_close": round(pc, 4),
                "gap_pct": round(gap, 3),
                "v30": round(v30, 4),
                "t1_close_ret": None,
                "t1_date": None,
                "t1_close": None,
                "status": ("pending" if fill_px is not None else "unfilled"),
                "ctrl_code": None,
                "ctrl_t1_date": None,
                "ctrl_ret": None,
                "src": "m60_cache",
                "ts": datetime.now().isoformat(timespec="seconds"),
            })
        except AssertionError:
            raise
        except Exception:
            diag["error"] += 1
    return new, dict(diag), n_ready, n_closed


# ---------------------------------------------------------------- 回填
def backfill(recs):
    n = 0
    details = []
    for r in recs:
        if r.get("t1_close_ret") is not None:
            continue
        fp0 = r.get("fill_px")
        if fp0 is None:                              # 未成交 → 标 unfilled，不再追踪
            if r.get("status") != "unfilled":
                r["status"] = "unfilled"
                r["note"] = "未成交，不再追踪"
            continue
        try:
            fp0 = float(fp0)
        except Exception:
            continue
        code = str(r.get("code") or "")
        d0 = str(r.get("date") or "")
        if not code or not d0:
            continue
        ds, dd = bk_load(code)
        if not ds:
            continue
        i = bisect.bisect_right(ds, d0)              # 登记日之后第一根日K
        if i >= len(ds):
            continue                                 # 下一交易日数据未就绪
        t1 = ds[i]
        assert t1 > d0, "回填日必须严格晚于登记日: %s %s" % (t1, d0)
        px = dd[t1]["close"]
        if px <= 0 or fp0 <= 0:
            continue
        r["t1_date"] = t1
        r["t1_close"] = round(px, 4)
        r["t1_close_ret"] = round(px / fp0 - 1.0 - FEE, 6)
        r["status"] = "filled"
        n += 1
        details.append(r)
    return n, details


# ---------------------------------------------------------------- 随机对照（seed 固定）
def attach_ctrl(rec, pool):
    if rec.get("t1_close_ret") is None:
        return False
    if rec.get("ctrl_ret") is not None:
        return False
    d0 = str(rec.get("date") or "")
    code = str(rec.get("code") or "")
    if not d0 or not pool:
        return False

    def probe(c):
        ds, dd = bk_load(c)
        if d0 not in dd:
            return None
        i = bisect.bisect_right(ds, d0)
        if i >= len(ds):
            return None
        t1 = ds[i]
        if not (t1 > d0):
            raise AssertionError("对照出场日未晚于入场日: %s %s" % (t1, d0))
        o = dd[d0]["open"]
        c1 = dd[t1]["close"]
        if o <= 0 or c1 <= 0:
            return None
        return (c, t1, c1 / o - 1.0 - FEE)

    saved = rec.get("ctrl_code")
    if saved:                                        # 已抽过 → 只重试同一只，数据未到则等下次
        got = probe(saved)
        if got:
            rec["ctrl_code"], rec["ctrl_t1_date"], rec["ctrl_ret"] = got[0], got[1], round(got[2], 6)
            return True
        return False

    rng = random.Random("%d|%s|%s" % (SEED, d0, code))   # 确定性随机（与运行顺序无关）
    for _ in range(40):
        c = pool[rng.randrange(len(pool))]
        if c == code:
            continue
        got = probe(c)
        if got:
            rec["ctrl_code"], rec["ctrl_t1_date"], rec["ctrl_ret"] = got[0], got[1], round(got[2], 6)
            return True
    return False


# ---------------------------------------------------------------- 汇总
def build_summary(recs, today):
    filled = [r for r in recs if r.get("t1_close_ret") is not None]
    traded = [r for r in recs if r.get("fill_px") is not None]
    unfilled = [r for r in recs if r.get("fill_px") is None]
    pending = [r for r in recs if r.get("t1_close_ret") is None and r.get("fill_px") is not None]
    rets = [float(r["t1_close_ret"]) for r in filled]
    ctrl = [float(r["ctrl_ret"]) for r in recs if r.get("ctrl_ret") is not None]
    paired = [(float(r["t1_close_ret"]), float(r["ctrl_ret"])) for r in recs
              if r.get("t1_close_ret") is not None and r.get("ctrl_ret") is not None]

    def mean_pct(xs):
        return round(100.0 * st.mean(xs), 3) if xs else None

    def win_pct(xs):
        return round(100.0 * sum(1 for x in xs if x > 0) / len(xs), 1) if xs else None

    last10 = sorted(recs, key=lambda r: (str(r.get("date")), str(r.get("code"))))[-10:]
    last10_out = []
    for r in last10:
        last10_out.append({
            "date": r.get("date"),
            "code": r.get("code"),
            "name": r.get("name"),
            "fill_px": r.get("fill_px"),
            "t1_date": r.get("t1_date"),
            "t1_close_ret%": (round(100.0 * float(r["t1_close_ret"]), 3)
                              if r.get("t1_close_ret") is not None else None),
            "ctrl_code": r.get("ctrl_code"),
            "ctrl_ret%": (round(100.0 * float(r["ctrl_ret"]), 3)
                          if r.get("ctrl_ret") is not None else None),
            "status": r.get("status"),
        })

    excess = (round(100.0 * (st.mean([a for a, _ in paired]) - st.mean([b for _, b in paired])), 3)
              if paired else None)

    return {
        "更新时间": datetime.now().isoformat(timespec="seconds"),
        "登记日": today,
        "总登记": len(recs),
        "已回填": len(filled),
        "待回填": len(pending),
        "未成交": len(unfilled),
        "成交率%": (round(100.0 * len(traded) / len(recs), 1) if recs else None),
        "均笔%": mean_pct(rets),
        "胜率%": win_pct(rets),
        "累计收益%": (round(100.0 * sum(rets), 3) if rets else None),
        "随机对照": {
            "seed": SEED,
            "样本数": len(ctrl),
            "配对样本数": len(paired),
            "均笔%": mean_pct(ctrl),
            "胜率%": win_pct(ctrl),
            "超额均笔%": excess,
            "口径": "同登记日开盘买 → 次交易日收盘卖 - 0.0015（等权，随机抽 1 只）",
        },
        "最近10笔": last10_out,
        "口径": {
            "signal": "昨涨停(收/前收-1>=9.8%) 且 今开>=昨收*1.05 且 今开幅度∈[6%,7%) 且 首30分钟量能比<1.0",
            "fill": "限价=昨收*1.07；bar.open<=限价按open，bar.low<=限价按限价，否则未成交(unfilled不追踪)",
            "exit": "T+1 收盘，费 0.0015（单边一次性扣）",
            "backfill_price": "big_kcache 前复权 close（与 fill_px 不复权存在跨分红口径差，与 B5 影子一致）",
            "idempotent_key": "(date, code)",
        },
        "已知限制": [
            "L1 前复权/不复权跨分红口径差（回填段）",
            "L2 60min 粒度成交判定偏乐观",
            "L3 首30分钟量能比取 <=10:30 最晚一根 bar（与 B 一致）",
            "L4 尾部预筛假设 m60 升序追加，乱序需 --full-scan",
            "L5 前向样本小，不做显著性结论",
            "L6 随机对照未对齐 +7% 限价挂单机制",
        ],
    }


# ---------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser(description="炸板浅炸规则影子盘日更基建")
    ap.add_argument("--date", default=None, help="登记日 YYYY-MM-DD（默认本地今日）")
    ap.add_argument("--full-scan", action="store_true", help="m60 全量解析（默认尾部快速预筛）")
    args = ap.parse_args()
    today = args.date or _date.today().isoformat()

    names = load_name_map()
    recs = load_ledger()
    known = {(str(r.get("date")), str(r.get("code"))) for r in recs}
    n_all_before = len(recs)

    # 1) 当日信号登记（幂等）
    new_recs, diag, n_ready, n_closed = scan_today(today, names, known, args.full_scan)
    for r in new_recs:
        recs.append(r)
        known.add((r["date"], r["code"]))

    # 2) 回填（含 unfilled 标记）
    n_fill, fill_detail = backfill(recs)

    # 3) 随机对照（seed 固定）
    pool = sorted(p.stem for p in BIGK.glob("*.json"))
    n_ctrl = 0
    if pool:
        for r in recs:
            if attach_ctrl(r, pool):
                n_ctrl += 1

    # 4) 断言 + 落盘
    n_t1 = sanity_check(recs)
    write_ledger(recs)
    smy = build_summary(recs, today)
    SUMMARY.write_text(json.dumps(smy, ensure_ascii=False, indent=1), encoding="utf-8")

    # 5) 汇报
    if n_ready == 0:
        print("[shadow] date=%s 非交易日或 m60 数据未就绪，跳过当日登记（已登记存量 %d 条）"
              % (today, n_all_before), flush=True)
    else:
        print("[shadow] date=%s m60就绪=%d 收盘bar齐备=%d 新登记=%d diag=%s"
              % (today, n_ready, n_closed, len(new_recs), json.dumps(diag, ensure_ascii=False)),
              flush=True)

    if new_recs:
        parts = []
        for r in sorted(new_recs, key=lambda x: x["code"]):
            fp0 = r.get("fill_px")
            parts.append("%s%s %s@%s" % (
                r["code"], ("/" + r["name"]) if r.get("name") else "",
                ("fill=%.3f" % fp0) if fp0 is not None else "未成交",
                r.get("fill_time") or "-"))
        print("[new] %d 只: %s" % (len(new_recs), " | ".join(parts)), flush=True)
    else:
        print("[new] 0 只", flush=True)

    if n_fill:
        rr = [float(r["t1_close_ret"]) for r in fill_detail]
        print("[fill] 本次回填 %d 笔: 均笔 %+.2f%% 胜率 %.1f%%"
              % (n_fill, 100.0 * st.mean(rr),
                 100.0 * sum(1 for x in rr if x > 0) / len(rr)), flush=True)
    else:
        print("[fill] 本次回填 0 笔", flush=True)

    allr = [float(r["t1_close_ret"]) for r in recs if r.get("t1_close_ret") is not None]
    if allr:
        print("[cum] 累计已回填 %d 笔: 均笔 %+.2f%% 累计胜率 %.1f%% 累计均笔 %+.2f%%"
              % (len(allr), 100.0 * st.mean(allr),
                 100.0 * sum(1 for x in allr if x > 0) / len(allr),
                 100.0 * st.mean(allr)), flush=True)

    if smy["随机对照"]["样本数"]:
        c = smy["随机对照"]
        print("[ctrl] 随机对照 n=%d 均笔 %+.2f%% 胜率 %s%% 超额 %s%% (seed=%d)"
              % (c["样本数"], c["均笔%"], c["胜率%"], c["超额均笔%"], SEED), flush=True)

    print("[ledger] 总登记 %d 条 (本次新增 %d) T+1断言通过 %d" % (len(recs), len(new_recs), n_t1),
          flush=True)
    print("[out] %s" % LEDGER, flush=True)
    print("[out] %s" % SUMMARY, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
