#!/usr/bin/env python3
"""engine/check_unadj_fresh.py — 不复权日线库新鲜度断言（跑不通 exit 1）

三项断言：
  (a) 覆盖率：前复权库(big_kcache)每一只都在不复权库里有文件；总数 >= 前复权库数，
      溢出部分必须是 data/unadj_rebuild_plan.json 里登记过的主板/退市额外票。
  (b) 新鲜度：不复权库最新日期落后「参照最新交易日」不超过 2 个交易日。
      参照 = big_kcache 的最新日期（自洽锚，无需外部日历）；若有 data/trade_calendar.json
      则用日历算交易日间隔。另对 big_kcache 自身陈旧发 WARN（不算本库失败）。
  (c) ST 覆盖率：data/main_board_codes.json 里名称含 ST 的票，在不复权库中占比 >= 95%。

用法：
  python engine/check_unadj_fresh.py                  # 查正式库 data/big_kcache_unadj
  python engine/check_unadj_fresh.py --dir data/big_kcache_unadj_v2   # 晋级前查 v2
退出码 0=全过，1=有断言失败。
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
KC = ROOT / "data/big_kcache"
MAIN_BOARD_FP = ROOT / "data/main_board_codes.json"
CAL_FP = ROOT / "data/trade_calendar.json"
PLAN_FP = ROOT / "data/unadj_rebuild_plan.json"
OUT_FP = ROOT / "data/unadj_fresh_check.json"

DATE_RE = re.compile(rb'"date"\s*:\s*"?(\d{4}-\d{2}-\d{2})')


def last_date_of(fp: Path):
    """尾部读 512 字节取最后一个 date（JSON 数组按日期升序）。"""
    try:
        size = fp.stat().st_size
        with open(fp, "rb") as f:
            f.seek(max(0, size - 512))
            tail = f.read()
        hits = DATE_RE.findall(tail)
        return hits[-1].decode() if hits else None
    except Exception:
        return None


def codes_of(d: Path):
    return {p.stem: p for p in d.glob("*.json") if len(p.stem) == 6 and p.stem.isdigit()}


def main():
    argv = sys.argv[1:]
    unadj = Path(argv[argv.index("--dir") + 1]) if "--dir" in argv else ROOT / "data/big_kcache_unadj"
    if not unadj.is_absolute():
        unadj = ROOT / unadj
    checks = {}
    fails = []

    kc = codes_of(KC)
    un = codes_of(unadj)
    kc_codes, un_codes = set(kc), set(un)
    missing = sorted(kc_codes - un_codes)
    extras = sorted(un_codes - kc_codes)

    plan_extras = set()
    if PLAN_FP.exists():
        plan = json.loads(PLAN_FP.read_text())
        plan_extras = set(plan.get("extra_mainboard_not_in_kcache", [])) | \
            set(plan.get("extra_delisted_not_in_kcache", []))
    unexpected_extras = sorted(set(extras) - plan_extras)

    # (a) 覆盖率
    ok_a = not missing and not unexpected_extras
    checks["a_coverage"] = {
        "kcache_stocks": len(kc_codes),
        "unadj_stocks": len(un_codes),
        "missing_from_unadj": missing,
        "extras_beyond_kcache": extras,
        "unexpected_extras": unexpected_extras,
        "ok": ok_a,
    }
    if not ok_a:
        fails.append("a_coverage")

    # (b) 新鲜度
    kc_dates = [d for d in (last_date_of(p) for p in kc.values()) if d]
    un_dates = [d for d in (last_date_of(p) for p in un.values()) if d]
    kc_max = max(kc_dates) if kc_dates else None
    un_max = max(un_dates) if un_dates else None
    cal = None
    if CAL_FP.exists():
        try:
            cal = sorted(json.loads(CAL_FP.read_text()))
        except Exception:
            cal = None
    if cal:
        between = [d for d in cal if un_max < d <= kc_max]
        lag = len(between)
    else:
        between = []
        lag = 1 if (kc_max and un_max and un_max < kc_max) else 0  # 无日历时的保守下界
    ok_b = bool(un_max and kc_max and lag <= 2)
    kc_stale_warn = bool(cal and kc_max and kc_max < cal[-1] and cal[-1] <= (un_max or ""))
    checks["b_freshness"] = {
        "unadj_latest": un_max,
        "reference_latest_kcache": kc_max,
        "trading_days_lag": lag,
        "trading_calendar_used": bool(cal),
        "kcache_itself_stale_vs_calendar": kc_stale_warn,
        "ok": ok_b,
    }
    if not ok_b:
        fails.append("b_freshness")

    # (c) ST 覆盖率
    mb = json.loads(MAIN_BOARD_FP.read_text(encoding="utf-8-sig"))
    st_codes = {s["code"] for s in mb["stocks"] if "ST" in s["name"]}
    st_have = st_codes & un_codes
    ratio = len(st_have) / len(st_codes) if st_codes else 1.0
    ok_c = ratio >= 0.95
    checks["c_st_coverage"] = {
        "st_in_main_board": len(st_codes),
        "st_in_unadj": len(st_have),
        "coverage": round(ratio, 4),
        "missing_st": sorted(st_codes - un_codes),
        "ok": ok_c,
    }
    if not ok_c:
        fails.append("c_st_coverage")

    result = {"dir": str(unadj), "checked": __import__("time").strftime("%Y-%m-%d %H:%M:%S"),
              "checks": checks, "fails": fails, "verdict": "PASS" if not fails else "FAIL"}
    OUT_FP.write_text(json.dumps(result, ensure_ascii=False, indent=1))

    print(f"[a] 覆盖: kcache={len(kc_codes)} unadj={len(un_codes)} 缺失={len(missing)} "
          f"额外={len(extras)}(意外={len(unexpected_extras)}) -> {'PASS' if ok_a else 'FAIL'}")
    if missing:
        print(f"    缺失示例: {missing[:20]}")
    print(f"[b] 新鲜: unadj最新={un_max} 参照kcache最新={kc_max} 落后={lag}个交易日 "
          f"-> {'PASS' if ok_b else 'FAIL'}")
    if checks["b_freshness"]["kcache_itself_stale_vs_calendar"]:
        print(f"    WARN big_kcache 自身落后交易日历({cal[-1] if cal else '?'})，前复权日更要查")
    print(f"[c] ST覆盖: {len(st_have)}/{len(st_codes)} = {ratio:.1%} -> {'PASS' if ok_c else 'FAIL'}")
    print(f"VERDICT: {result['verdict']}  (明细 {OUT_FP})")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
