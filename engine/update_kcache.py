#!/usr/bin/env python3
"""engine/update_kcache.py — big_kcache 增量更新（baostock，单进程纪律）

对每只已缓存股票：拉 最后日期-7天 → 最新交易日，
- 重叠区与缓存一致 → 纯 append（快路径）
- 重叠区不一致（前复权锚漂移，分红送配所致）→ 全量重拉替换（接缝修复）
  ※ 2026-09-12 Sequoia-X hfq 洞察牵出：前复权锚定最新价，每次分红后旧行整体过期，
    纯 append 会在接缝处缓慢腐蚀缓存。重叠校验是唯一可靠检测。
新上市（本地缺失）的票交给 fetch_full_market.py 全量拉，本脚本不管。
用法：python3 engine/update_kcache.py [end_date]   # 默认今天
"""
import json, sys, time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, "/opt/data/python-libs")
import baostock as bs

KC = Path("/opt/data/fenjue/data/big_kcache")
FIELDS = "date,open,high,low,close,volume"
FULL_START = "2019-01-01"


def code_to_bs(code: str) -> str:
    return ("sh." if code.startswith("6") else "sz.") + code


def query(bs_code, start, end, adjust="2"):
    """带掉线重连：baostock 长会话会被服务端掐（2026-09-21 实锤：第328只后全空响应，
    3000只被静默跳过还报 ok）。返回 None=查询失败（调用方计入失败连击），[]=当日无数据。"""
    global _bs_fail
    for attempt in range(3):
        rs = bs.query_history_k_data_plus(bs_code, FIELDS, start_date=start, end_date=end,
                                          frequency="d", adjustflag=adjust)
        if rs.error_code == "0":
            rows = []
            while rs.error_code == "0" and rs.next():
                r = rs.get_row_data()
                if r[1]:
                    rows.append({"date": r[0], "open": float(r[1]), "high": float(r[2]),
                                 "low": float(r[3]), "close": float(r[4]), "volume": float(r[5] or 0)})
            return rows
        # 会话异常 → 重登重试
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


def update_index(end):
    """上证指数同步（2026-09-19 自查发现：index_sh000001.json 自 9/14 撞代码修复落盘后
    无人更新，dashboard 交易日历/regime idx 字段/大盘量能全部吃旧数据）。
    指数无复权问题（adjustflag=3），纯增量 append。"""
    fp = KC.parent / "index_sh000001.json"
    rows = json.loads(fp.read_text()) if fp.exists() else []
    last = rows[-1]["date"] if rows else FULL_START
    if last >= end:
        print(f"index: 已最新 {last}", flush=True)
        return
    rs = bs.query_history_k_data_plus("sh.000001", FIELDS, start_date=last, end_date=end,
                                      frequency="d", adjustflag="3")
    new = []
    while rs.error_code == "0" and rs.next():
        r = rs.get_row_data()
        if r[1]:
            new.append({"date": r[0], "open": float(r[1]), "high": float(r[2]),
                        "low": float(r[3]), "close": float(r[4]), "volume": float(r[5] or 0)})
    seen = {r["date"] for r in rows}
    rows.extend(r for r in new if r["date"] not in seen)
    rows.sort(key=lambda r: r["date"])
    fp.write_text(json.dumps(rows))
    print(f"index: {last} → {rows[-1]['date']}（+{len(new)} 行）", flush=True)


def main():
    end = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    files = sorted(KC.glob("*.json"))
    lg = bs.login()
    assert lg.error_code == "0", lg.error_msg
    updated = upto = seams = errors = 0
    fail_streak = 0  # 连续查询失败连击：>20 判定会话级故障，退出码1让 cron 报警（防静默"成功"）
    t0 = time.time()
    for idx, fp in enumerate(files):
        code = fp.stem
        try:
            rows = json.loads(fp.read_text())
            last = rows[-1]["date"]
            if last >= end:
                upto += 1
                continue
            # 重叠校验窗口：最后 7 天 → 今天
            ov_start = (date.fromisoformat(last) - timedelta(days=7)).isoformat()
            new = query(code_to_bs(code), ov_start, end)
            if new is None:
                fail_streak += 1
                errors += 1
                if fail_streak > 20:
                    print(f"FATAL 连续 {fail_streak} 只查询失败（会话级故障），中止待重跑", flush=True)
                    bs.logout()
                    sys.exit(1)
                continue
            fail_streak = 0
            if not new:
                continue
            old_by_date = {r["date"]: r for r in rows}
            drift = any(
                r["date"] in old_by_date and abs(old_by_date[r["date"]]["close"] - r["close"]) > 1e-6
                for r in new)
            # 哨兵校验：分红会让所有【分红前】旧行过期，7天重叠窗抓不住——
            # 单独重查首行（最老的一天），漂移=缓存整体过期（2026-09-12 自审补洞）
            if not drift:
                sentinel = query(code_to_bs(code), rows[0]["date"], rows[0]["date"])
                if sentinel and abs(sentinel[0]["close"] - rows[0]["close"]) > 1e-6:
                    drift = True
            if drift:
                full = query(code_to_bs(code), FULL_START, end)
                if full and len(full) >= len(rows):
                    fp.write_text(json.dumps(full))
                    seams += 1
                    print(f"SEAM-FIX {code}: 复权漂移，全量重拉 {len(rows)}→{len(full)} 行", flush=True)
                else:
                    errors += 1
                    print(f"SEAM-ERR {code}: 全量重拉行数异常 {len(full)}<{len(rows)}，保留旧文件", flush=True)
                time.sleep(0.12)
                continue
            seen = set(old_by_date)
            rows.extend(r for r in new if r["date"] not in seen)
            rows.sort(key=lambda r: r["date"])
            fp.write_text(json.dumps(rows))
            updated += 1
        except Exception as e:
            errors += 1
            print(f"ERR {code}: {e}", flush=True)
        if idx % 200 == 0:
            print(f"[{idx}/{len(files)}] updated={updated} upto={upto} seam={seams} err={errors} {time.time()-t0:.0f}s", flush=True)
        time.sleep(0.12)  # 限流纪律
    update_index(end)
    bs.logout()
    print(f"DONE updated={updated} already_current={upto} seam_fixed={seams} errors={errors} elapsed={time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
