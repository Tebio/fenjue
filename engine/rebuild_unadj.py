#!/usr/bin/env python3
"""engine/rebuild_unadj.py — 重建不复权日线库 → data/big_kcache_unadj_v2/（baostock adjustflag=3）

阶段（--phase）：
  plan    建清单：big_kcache 3377 只为主集，核对 delisted/main_board 有无额外票，落 data/unadj_rebuild_plan.json
  fetch   抓取：已有 2877 只按各自最后日期+1 增量补齐（merge 旧行），缺失票 2019-01-02 全量抓；
          顺手缓存交易日历 data/trade_calendar.json
  factor  复权因子表：后复权(adjustflag=1)收盘/不复权收盘，分段常数压缩 → data/adj_factor.json
  verify  抽样 20 只口径核对（重叠区 close+volume 与旧库一致，容差 0.001）+ 因子 round-trip + ST ±5% 健全性
  all     以上顺序全跑（默认先调 wait_baostock_free.py 守门，--no-wait 跳过）

日更模式 --daily：对 v2（或 --dir 指定库）做增量补齐 + 因子表增量延伸。复用本脚本，不另起炉灶。

纪律：baostock 单进程独占；原子写（tmp+os.replace）；失败逐票记账（不许再出空 failed.json）；
限流 0.12s/只；连续 20 只查询失败判会话级故障退出码 1。
"""
import json
import os
import random
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path

# 与 fetch_m5_sample.py 同款：baostock 直连，剥掉 shell 继承的代理（本机 Clash 代理在 192.168.2.15）
for _k in list(os.environ):
    if "proxy" in _k.lower():
        os.environ.pop(_k, None)

ROOT = Path("/opt/data/fenjue")
KC = ROOT / "data/big_kcache"                 # 前复权（好库，参照基准）
OLD = ROOT / "data/big_kcache_unadj"          # 旧不复权（坏库，只读不碰）
NEW = ROOT / "data/big_kcache_unadj_v2"       # 新库输出（晋级前）；--out 可覆盖
OUT_DIR = NEW                                 # 运行期实际输出目录
PLAN_FP = ROOT / "data/unadj_rebuild_plan.json"
PROG_FP = ROOT / "engine/unadj_rebuild_progress.json"
SUM_FP = ROOT / "engine/unadj_rebuild_summary.json"
FACTOR_FP = ROOT / "data/adj_factor.json"
CAL_FP = ROOT / "data/trade_calendar.json"
MAIN_BOARD_FP = ROOT / "data/main_board_codes.json"
DELISTED_FP = ROOT / "data/delisted_codes.json"

FIELDS = "date,open,high,low,close,volume,amount"
FULL_START = "2019-01-02"
SLEEP_S = 0.12

_bs = None  # 惰性登录


def code_to_bs(code: str) -> str:
    if code.startswith(("4", "8")):
        return "bj." + code
    return ("sh." if code.startswith("6") else "sz.") + code


def login():
    global _bs
    sys.path.insert(0, "/opt/data/python-libs")
    import baostock as bs
    _bs = bs
    lg = bs.login()
    assert lg.error_code == "0", f"baostock login 失败: {lg.error_msg}"
    return bs


def query(bs_code, start, end, adjust="3", fields=FIELDS):
    """掉线重连版查询（抄 update_kcache.py 的实战模式）。None=查询失败；[]=区间无数据。"""
    bs = _bs
    for attempt in range(3):
        rs = bs.query_history_k_data_plus(bs_code, fields, start_date=start, end_date=end,
                                          frequency="d", adjustflag=adjust)
        if rs.error_code == "0":
            rows = []
            while rs.error_code == "0" and rs.next():
                r = rs.get_row_data()
                if r[1] and r[4] and float(r[4]) > 0:  # 停牌/空行/零价过滤
                    row = {"date": r[0], "open": float(r[1]), "high": float(r[2]),
                           "low": float(r[3]), "close": float(r[4]), "volume": float(r[5] or 0)}
                    if len(r) > 6:
                        row["amount"] = float(r[6] or 0)
                    rows.append(row)
            return rows
        print(f"bs query {bs_code} err={rs.error_code}/{rs.error_msg}，重登({attempt + 1}/3)", flush=True)
        try:
            bs.logout()
        except Exception:
            pass
        time.sleep(2 * (attempt + 1))
        lg = bs.login()
        if lg.error_code != "0":
            time.sleep(5)
    return None


def query_close(bs_code, start, end, adjust="1"):
    """只取 date,close（后复权因子用）。返回 [(date, close)] / None。"""
    bs = _bs
    for attempt in range(3):
        rs = bs.query_history_k_data_plus(bs_code, "date,close", start_date=start, end_date=end,
                                          frequency="d", adjustflag=adjust)
        if rs.error_code == "0":
            rows = []
            while rs.error_code == "0" and rs.next():
                r = rs.get_row_data()
                if r[1] and float(r[1]) > 0:
                    rows.append((r[0], float(r[1])))
            return rows
        print(f"bs close-query {bs_code} err={rs.error_code}/{rs.error_msg}，重登({attempt + 1}/3)", flush=True)
        try:
            bs.logout()
        except Exception:
            pass
        time.sleep(2 * (attempt + 1))
        lg = bs.login()
        if lg.error_code != "0":
            time.sleep(5)
    return None


def atomic_write(fp: Path, rows: list):
    tmp = fp.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rows, separators=(",", ":")))
    os.replace(tmp, fp)


def save_progress(state: dict):
    state["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    PROG_FP.write_text(json.dumps(state, ensure_ascii=False))


# ---------- phase: plan ----------

def load_json(fp: Path):
    return json.loads(fp.read_text(encoding="utf-8-sig"))


def phase_plan():
    kc_codes = {p.stem for p in KC.glob("*.json") if len(p.stem) == 6}
    old_codes = {p.stem for p in OLD.glob("*.json") if len(p.stem) == 6}
    delisted = set(load_json(DELISTED_FP)["codes"])
    mb = load_json(MAIN_BOARD_FP)
    mb_stocks = mb["stocks"]
    mb_codes = {s["code"] for s in mb_stocks}
    st_codes = {s["code"] for s in mb_stocks if "ST" in s["name"]}

    extra_delisted = sorted(delisted - kc_codes)
    extra_mb = sorted(mb_codes - kc_codes)
    targets = sorted(kc_codes | set(extra_delisted) | set(extra_mb))
    missing = [c for c in targets if c not in old_codes]       # 要全量抓
    incr = [c for c in targets if c in old_codes]              # 要增量补
    plan = {
        "built": time.strftime("%Y-%m-%d %H:%M:%S"),
        "big_kcache": len(kc_codes),
        "old_unadj": len(old_codes),
        "delisted_file": len(delisted),
        "main_board": len(mb_codes),
        "st_in_main_board": len(st_codes),
        "st_in_old_unadj": len(st_codes & old_codes),
        "extra_delisted_not_in_kcache": extra_delisted,
        "extra_mainboard_not_in_kcache": extra_mb,
        "targets": targets,
        "full_fetch": sorted(missing),
        "incremental": sorted(incr),
        "st_codes": sorted(st_codes),
    }
    PLAN_FP.write_text(json.dumps(plan, ensure_ascii=False, indent=1))
    print(f"[plan] big_kcache={len(kc_codes)} old_unadj={len(old_codes)} "
          f"targets={len(targets)} (full={len(missing)} incr={len(incr)})", flush=True)
    print(f"[plan] 主板名单={len(mb_codes)} ST={len(st_codes)} (旧库已有ST={len(st_codes & old_codes)})", flush=True)
    print(f"[plan] 前复权库之外的票: 退市表+{len(extra_delisted)} 主板名单+{len(extra_mb)}", flush=True)
    if extra_delisted:
        print(f"[plan] extra_delisted: {extra_delisted}", flush=True)
    if extra_mb:
        print(f"[plan] extra_mainboard: {extra_mb}", flush=True)
    return plan


# ---------- phase: fetch ----------

def fetch_one(code: str, end: str, daily_base: Path = None):
    """抓一只并写盘。返回 (status, n_new_rows, reason)。
    status: full/incr/skip_current/no_new_data/failed/empty"""
    bs_code = code_to_bs(code)
    base = daily_base or OLD
    old_fp = base / f"{code}.json"
    new_fp = OUT_DIR / f"{code}.json"
    if old_fp.exists():
        try:
            rows = json.loads(old_fp.read_text())
        except Exception as e:
            return "failed", 0, f"old_file_unreadable:{e}"
        # 断点续跑：v2 已有进度优先（否则重跑会把整段再抓一遍）
        if new_fp.exists():
            try:
                v2 = json.loads(new_fp.read_text())
                if v2 and (not rows or v2[-1]["date"] >= rows[-1]["date"]):
                    rows = v2
            except Exception:
                pass  # v2 坏了就退回旧库，原子写会重建
        last = rows[-1]["date"] if rows else None
        if not last:
            start = FULL_START
        else:
            if last >= end:
                if not new_fp.exists():
                    atomic_write(new_fp, rows)
                return "skip_current", 0, ""
            start = (date.fromisoformat(last) + timedelta(days=1)).isoformat()
        new_rows = query(bs_code, start, end)
        if new_rows is None:
            return "failed", 0, "query_failed_after_3_retries"
        if not new_rows:
            if not new_fp.exists():
                atomic_write(new_fp, rows)
            return "no_new_data", 0, f"无新增行(旧末日期={last}，或停牌/退市)"
        seen = {r["date"] for r in rows}
        add = [r for r in new_rows if r["date"] not in seen]
        rows = rows + add
        rows.sort(key=lambda r: r["date"])
        atomic_write(new_fp, rows)
        return "incr", len(add), ""
    # 全量
    new_rows = query(bs_code, FULL_START, end)
    if new_rows is None:
        return "failed", 0, "query_failed_after_3_retries"
    if not new_rows:
        return "empty", 0, "baostock 全区间无数据(可能2019前已退市/北交所不支持)"
    atomic_write(new_fp, new_rows)
    return "full", len(new_rows), ""


def phase_fetch(end: str, limit: int = 0, daily: bool = False, base_dir: str = "", shard: str = ""):
    plan = json.loads(PLAN_FP.read_text())
    targets = plan["targets"]
    if shard:
        si, sn = (int(x) for x in shard.split("/"))
        targets = [c for idx, c in enumerate(targets) if idx % sn == si]
    if limit:
        targets = targets[:limit]
    NEW.mkdir(exist_ok=True)
    OUT_DIR.mkdir(exist_ok=True)
    login()
    # 交易日历缓存（供 check 脚本与报告用，一次调用）
    try:
        rs = _bs.query_trade_dates(start_date="2019-01-01", end_date=end)
        cal = []
        while rs.error_code == "0" and rs.next():
            r = rs.get_row_data()
            if r[1] == "1":
                cal.append(r[0])
        CAL_FP.write_text(json.dumps(cal))
        print(f"[fetch] 交易日历缓存 {len(cal)} 天 → {CAL_FP.name}", flush=True)
    except Exception as e:
        print(f"[fetch] 交易日历缓存失败(不阻断): {e}", flush=True)

    stats = {"full": 0, "incr": 0, "skip_current": 0, "no_new_data": 0, "failed": 0, "empty": 0}
    failed = {}
    rows_added = 0
    fail_streak = 0
    t0 = time.time()
    base = Path(base_dir) if base_dir else OLD
    for idx, code in enumerate(targets):
        try:
            status, n, reason = fetch_one(code, end, daily_base=base)
        except Exception as e:
            status, n, reason = "failed", 0, f"exception:{e}"
        stats[status] = stats.get(status, 0) + 1
        rows_added += n
        if status in ("failed", "empty"):
            failed[code] = reason
        fail_streak = fail_streak + 1 if status == "failed" and "query_failed" in reason else 0
        if fail_streak > 20:
            print(f"FATAL 连续 {fail_streak} 只查询失败（会话级故障），中止待重跑", flush=True)
            save_progress({"phase": "fetch_aborted", "stats": stats, "failed": failed})
            _bs.logout()
            sys.exit(1)
        if idx % 200 == 0 or status in ("failed", "empty"):
            print(f"[fetch {idx}/{len(targets)}] {stats} +rows={rows_added} {time.time()-t0:.0f}s"
                  + (f" | {code} {reason}" if status in ("failed", "empty") else ""), flush=True)
            save_progress({"phase": "fetch", "idx": idx, "stats": stats,
                           "rows_added": rows_added, "failed": failed})
        time.sleep(SLEEP_S)
    _bs.logout()
    save_progress({"phase": "fetch_done", "stats": stats, "rows_added": rows_added,
                   "failed": failed, "elapsed_s": round(time.time() - t0)})
    print(f"[fetch] DONE {stats} rows_added={rows_added} failed={len(failed)} "
          f"elapsed={time.time()-t0:.0f}s", flush=True)
    return stats, failed


# ---------- phase: factor ----------

def compress_segments(pairs):
    """[(date, factor), ...] → [[start_date, factor], ...]，相邻同值合并。
    阈值 1e-6 相对差：高于 baostock 8 位小数舍入噪声，远低于任何真实分红跳变。"""
    segs = []
    for d, f in pairs:
        if segs and abs(segs[-1][1] - f) <= 1e-6 * max(1.0, abs(f)):
            continue
        segs.append([d, round(f, 8)])
    return segs


def _factor_payload(factors):
    return {
        "_meta": {
            "built": time.strftime("%Y-%m-%d %H:%M:%S"),
            "factor_type": "qfq_ratio",
            "source": "f = big_kcache 前复权收盘 ÷ 不复权收盘（逐日比例压段）；"
                      "K = baostock 后复权收盘 ÷ 不复权收盘（不复权库最后交易日）",
            "semantics": "segments: [[起始日, f], ...]，f 自该日恒定至下一段。"
                         "qfq_t = unadj_t × f_t；hfq_t = unadj_t × f_t × K；unadj_t = qfq_t / f_t。"
                         "K=null 表示当日后复权查询失败，仅影响⇄后复权换算。",
            "coverage": "segments 起点为首个前复权交易日（通常 2019-01）；更早的不复权行按首段外推。",
            "stocks": len(factors),
        },
        **factors,
    }


def _load_qfq_map(code):
    fp = KC / f"{code}.json"
    if not fp.exists():
        return None
    try:
        rows = json.loads(fp.read_text())
    except Exception:
        return None
    return {r["date"]: r["close"] for r in rows if r.get("close")}


def _hfq_k(bs_code, last_date, last_close):
    """K = 后复权收盘 / 不复权收盘（不复权库最后交易日）。失败返回 None。"""
    q = query_close(bs_code, last_date, last_date, adjust="1")
    if not q:
        return None
    return round(q[-1][1] / last_close, 8)


def phase_factor(end: str, limit: int = 0, daily: bool = False):
    """f 来自「前复权/不复权」逐日比例；日更时分段未变则零查询复用。"""
    plan = json.loads(PLAN_FP.read_text())
    codes = [c for c in plan["targets"] if (OUT_DIR / f"{c}.json").exists()]
    if limit:
        codes = codes[:limit]
    factors = {}
    if FACTOR_FP.exists():
        old = json.loads(FACTOR_FP.read_text())
        if old.get("_meta", {}).get("factor_type") == "qfq_ratio":
            factors = {k: v for k, v in old.items() if not k.startswith("_")}
            if not daily and factors:
                print(f"[factor] 断点续跑：复用已有 {len(factors)} 只", flush=True)
        else:
            print("[factor] 旧因子表类型不匹配（hfq 口径），全量重建", flush=True)
    login()
    failed, k_missing, reused = {}, [], 0
    t0 = time.time()
    for idx, code in enumerate(codes):
        if not daily and code in factors:
            continue
        unadj = json.loads((OUT_DIR / f"{code}.json").read_text())
        if not unadj:
            failed[code] = "empty_unadj_file"
            continue
        qfq = _load_qfq_map(code)
        bs_code = code_to_bs(code)
        if qfq:
            pairs = [(r["date"], qfq[r["date"]] / r["close"])
                     for r in unadj if r["date"] in qfq and r["close"] > 0]
            if not pairs:
                failed[code] = "no_qfq_overlap"
                time.sleep(SLEEP_S)
                continue
            segs = compress_segments(pairs)
            anchor = pairs[-1][0]
            prev = factors.get(code)
            if daily and prev and prev.get("segments") == segs and prev.get("k"):
                factors[code] = prev          # 无除权事件，零查询复用
                reused += 1
                continue
        else:
            # 无前复权参照（2026 年新上市、前复权库也没有的 4 只）：hfq 全历史归一化到末日
            hfq = query_close(bs_code, unadj[0]["date"], end, adjust="1")
            if not hfq:
                failed[code] = "no_qfq_and_hfq_empty"
                time.sleep(SLEEP_S)
                continue
            hm = dict(hfq)
            pairs = [(r["date"], hm[r["date"]] / r["close"])
                     for r in unadj if r["date"] in hm and r["close"] > 0]
            if not pairs:
                failed[code] = "hfq_no_overlap"
                continue
            base = pairs[-1][1]
            segs = compress_segments([(d, f / base) for d, f in pairs])
            anchor = pairs[-1][0]
        k = _hfq_k(bs_code, unadj[-1]["date"], unadj[-1]["close"])
        if k is None:
            k_missing.append(code)
        factors[code] = {"segments": segs, "k": k, "anchor": anchor, "last": unadj[-1]["date"]}
        if idx % 200 == 0:
            print(f"[factor {idx}/{len(codes)}] failed={len(failed)} "
                  f"k_missing={len(k_missing)} {time.time()-t0:.0f}s", flush=True)
        if idx and idx % 300 == 0:
            tmp = FACTOR_FP.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(_factor_payload(factors), separators=(",", ":")))
            os.replace(tmp, FACTOR_FP)
        time.sleep(SLEEP_S)
    _bs.logout()
    FACTOR_FP.write_text(json.dumps(_factor_payload(factors), separators=(",", ":")))
    n_segs = sum(len(v["segments"]) for v in factors.values() if isinstance(v, dict))
    print(f"[factor] DONE stocks={len(factors)} segments={n_segs} failed={len(failed)} "
          f"k_missing={len(k_missing)} reused={reused} elapsed={time.time()-t0:.0f}s", flush=True)
    return factors, failed


# ---------- phase: verify ----------

def phase_verify(end: str):
    plan = json.loads(PLAN_FP.read_text())
    res = {"sample_overlap": [], "factor_roundtrip": [], "st_sanity": {}, "verdict": "PASS"}
    login()

    # 1) 抽样 20 只旧库票：重叠区 close+volume 与旧库逐日比对（独立重查，不读 v2）
    old_incr = [c for c in plan["incremental"] if (OUT_DIR / f"{c}.json").exists()]
    random.seed(20261019)
    sample = random.sample(old_incr, min(20, len(old_incr)))
    for code in sample:
        old_rows = json.loads((OLD / f"{code}.json").read_text())
        ov_start = old_rows[-30]["date"] if len(old_rows) > 30 else old_rows[0]["date"]
        ov_end = old_rows[-1]["date"]
        new_rows = query(code_to_bs(code), ov_start, ov_end)
        if new_rows is None:
            res["sample_overlap"].append({"code": code, "error": "query_failed"})
            res["verdict"] = "FAIL"
            continue
        new_map = {r["date"]: r for r in new_rows}
        max_close_diff = 0.0
        max_vol_reldiff = 0.0
        n_cmp = 0
        for r in old_rows:
            if r["date"] < ov_start or r["date"] not in new_map:
                continue
            n_cmp += 1
            d = abs(new_map[r["date"]]["close"] - r["close"])
            max_close_diff = max(max_close_diff, d)
            if r["volume"] > 0:
                vd = abs(new_map[r["date"]]["volume"] - r["volume"]) / r["volume"]
                max_vol_reldiff = max(max_vol_reldiff, vd)
        ok = max_close_diff <= 0.001 and max_vol_reldiff <= 1e-6
        if not ok:
            res["verdict"] = "FAIL"
        res["sample_overlap"].append({"code": code, "n_days": n_cmp,
                                      "max_close_diff": round(max_close_diff, 6),
                                      "max_vol_reldiff": f"{max_vol_reldiff:.2e}",
                                      "ok": ok})
        time.sleep(SLEEP_S)

    # 2) 因子 round-trip：抽 20 只，用 adj_factor 把不复权换算成前复权，与 big_kcache 比
    factors = json.loads(FACTOR_FP.read_text())
    rt_sample = random.sample([c for c in plan["targets"]
                               if c in factors and (KC / f"{c}.json").exists()], 20)

    def factor_at(segs, d):
        f = segs[0][1]
        for s in segs:
            if s[0] <= d:
                f = s[1]
            else:
                break
        return f

    for code in rt_sample:
        unadj = json.loads((OUT_DIR / f"{code}.json").read_text())
        qfq = {r["date"]: r["close"] for r in json.loads((KC / f"{code}.json").read_text())}
        entry = factors[code]
        segs = entry["segments"]
        diffs = []
        for r in unadj:
            if r["date"] in qfq and qfq[r["date"]] > 0 and r["close"] > 0:
                recon = r["close"] * factor_at(segs, r["date"])
                diffs.append(abs(recon - qfq[r["date"]]) / qfq[r["date"]])
        mx = max(diffs) if diffs else 0.0
        ok = bool(diffs) and mx <= 1e-4   # 压段阈值 1e-6，留两个量级余量
        if not ok:
            res["verdict"] = "FAIL"
        res["factor_roundtrip"].append({"code": code, "n_days": len(diffs),
                                        "max_rel_diff": f"{mx:.2e}", "ok": ok})

    # 2b) K 的核对：近 250 个交易日 后复权重建 = 不复权 × f × K，看与 baostock 后复权是否吻合
    #     （baostock 后复权历史偶有毛刺，故只作质量观测，不作为硬失败条件）
    hfq_sample = random.sample(rt_sample, min(5, len(rt_sample)))
    for code in hfq_sample:
        entry = factors[code]
        if not entry.get("k"):
            res.setdefault("hfq_check", []).append({"code": code, "error": "k_missing"})
            continue
        unadj = json.loads((OUT_DIR / f"{code}.json").read_text())
        rows = unadj[-250:]
        hfq = query_close(code_to_bs(code), rows[0]["date"], rows[-1]["date"], adjust="1") or []
        hm = dict(hfq)
        rels = [abs(r["close"] * factor_at(entry["segments"], r["date"]) * entry["k"] - hm[r["date"]])
                / hm[r["date"]] for r in rows if r["date"] in hm and hm[r["date"]] > 0]
        good = sum(1 for x in rels if x <= 2e-3)
        res.setdefault("hfq_check", []).append({
            "code": code, "n_days": len(rels),
            "within_0.2pct": f"{good}/{len(rels)}",
            "max_rel_diff": f"{max(rels):.2e}" if rels else None})
        time.sleep(SLEEP_S)

    # 3) ST 健全性：新抓的 ST 票日涨跌幅应绝大多数在 ±5.5% 内（验证没抓错口径/名单）
    st_new = [c for c in plan["st_codes"] if c in plan["full_fetch"] and (OUT_DIR / f"{c}.json").exists()]
    within = total = 0
    for code in st_new:
        rows = json.loads((OUT_DIR / f"{code}.json").read_text())
        for a, b in zip(rows, rows[1:]):
            if a["close"] > 0:
                total += 1
                if abs(b["close"] / a["close"] - 1) <= 0.056:
                    within += 1
    res["st_sanity"] = {"st_new_stocks": len(st_new), "days": total,
                        "within_5.6pct": within,
                        "ratio": round(within / total, 4) if total else None}
    _bs.logout()

    overlap_ok = sum(1 for r in res["sample_overlap"] if r.get("ok"))
    rt_ok = sum(1 for r in res["factor_roundtrip"] if r.get("ok"))
    print(f"[verify] 重叠口径 {overlap_ok}/{len(res['sample_overlap'])} 只一致；"
          f"因子round-trip {rt_ok}/{len(res['factor_roundtrip'])} 只一致；"
          f"ST±5.6%占比={res['st_sanity']['ratio']}", flush=True)
    print(f"[verify] verdict={res['verdict']}", flush=True)
    return res


# ---------- main ----------

def main():
    argv = sys.argv[1:]
    phase = "all"
    if "--phase" in argv:
        phase = argv[argv.index("--phase") + 1]
    no_wait = "--no-wait" in argv
    daily = "--daily" in argv
    shard = ""
    if "--shard" in argv:
        shard = argv[argv.index("--shard") + 1]
    limit = 0
    if "--limit" in argv:
        limit = int(argv[argv.index("--limit") + 1])
    end = date.today().isoformat()
    if "--end" in argv:
        end = argv[argv.index("--end") + 1]
    base_dir = ""
    if "--dir" in argv:
        base_dir = argv[argv.index("--dir") + 1]
    if "--base" in argv:
        base_dir = argv[argv.index("--base") + 1]
    global OUT_DIR
    if "--out" in argv:
        OUT_DIR = Path(argv[argv.index("--out") + 1])
        if not OUT_DIR.is_absolute():
            OUT_DIR = ROOT / OUT_DIR
    if daily:
        # 日更：默认对正式库原地增量（base=out=big_kcache_unadj），原子替换写盘
        if not base_dir:
            base_dir = str(ROOT / "data/big_kcache_unadj")
        if "--out" not in argv:
            OUT_DIR = ROOT / "data/big_kcache_unadj"

    if not no_wait and phase in ("all", "fetch"):
        rc = subprocess.run([sys.executable, str(ROOT / "engine/wait_baostock_free.py")]).returncode
        if rc != 0:
            print("baostock 等待超时/失败，按纪律不硬上，退出", flush=True)
            sys.exit(2)

    # 合并写：日更单 phase 运行不能把之前 verify/plan 的结论冲掉
    prev = {}
    if SUM_FP.exists():
        try:
            prev = json.loads(SUM_FP.read_text())
        except Exception:
            prev = {}
    summary = {**prev, "end_date": end, "last_phase": phase,
               "started": time.strftime("%Y-%m-%d %H:%M:%S")}
    if phase in ("all", "plan"):
        plan = phase_plan()
        summary["plan"] = {k: (len(v) if isinstance(v, list) else v)
                           for k, v in plan.items() if k != "targets"}
    if phase in ("all", "fetch"):
        stats, failed = phase_fetch(end, limit=limit, daily=daily, base_dir=base_dir, shard=shard)
        summary["fetch"] = {"stats": stats, "rows_added_file": str(PROG_FP),
                            "failed": failed}
        if failed:
            (ROOT / "data/unadj_rebuild_failed.json").write_text(
                json.dumps(failed, ensure_ascii=False, indent=1))
    if phase in ("all", "factor"):
        factors, ffail = phase_factor(end, limit=limit, daily=daily)
        summary["factor"] = {"stocks": len(factors), "failed": ffail}
    if phase in ("all", "verify"):
        summary["verify"] = phase_verify(end)
    summary["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
    SUM_FP.write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    print(f"[main] summary → {SUM_FP}", flush=True)


if __name__ == "__main__":
    main()
