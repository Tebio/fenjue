"""金股月度管线（2026-09-27 深夜，用户质问「没有金股的买入建议吗」后立项）。

职责：
1. 每月 1-10 交易日窗口内每日尝试拉当月金股名单（iwencai，配额耗尽则记状态，不毒缓存）；
2. 拉到后算出「生产组合」：独家（同推1家）+年内首入（新鲜），第6交易日为入场日；
3. 落盘 data/gold_current.json 供作战单/面板消费：
   {month, status: ok/quota_dead/pending, entry_day, picks:[...], note}
4. 历史缺口（2022-11 起）由 gold_stock_backtest.py 断点续传补（每日 08:30 配额探测）。
"""
import datetime
import json
import subprocess
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))  # 同目录模块（trade_calendar）
import trade_calendar as tc

ROOT = Path("/opt/data/fenjue")
CACHE = ROOT / "data/gold_stock_cache"
CLI = ROOT.parent / ".iwencai-skillhub/skills/hithink-insresearch-query/scripts/cli.py"
OUT = ROOT / "data/gold_current.json"

env = dict()
for line in Path("/opt/data/.env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        env[k] = v


def _this_month():
    return datetime.datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m")


def fetch_month(mo):
    """拉一月名单；配额耗尽返回 None（不写缓存），成功写缓存返回列表。

    2026-10-18 修：本月名单是「逐日累加」的（各券商陆续发布），旧逻辑「缓存非空即永久复用」把
    2026-10 冻结在 10-09 拿到的 6 条 → 独家+年内首入恒为 0，整月谎报「空仓过月」（正常月份 125~241 条）。
    现规则：本月缓存在 6 小时内算新鲜，逾时重拉；历史月份永久复用。
    """
    fp = CACHE / f"{mo}.json"
    if fp.exists():
        cached = json.loads(fp.read_text())
        if cached:
            if mo != _this_month() or (time.time() - fp.stat().st_mtime) < 6 * 3600:
                return cached
        else:
            fp.unlink()
    y, m = mo.split("-")
    out, page = [], 1
    while True:
        r = subprocess.run(
            ["python3", str(CLI), "--query", f"{y}年{int(m)}月 券商金股", "--page", str(page), "--limit", "50"],
            capture_output=True, text=True, env=env, timeout=60)
        try:
            d = json.loads(r.stdout)
        except Exception:
            return None  # 配额耗尽/接口异常（纯文本）
        rows = d.get("datas") or []
        for row in rows:
            code = str(row.get("股票代码") or "").split(".")[0].zfill(6)
            if code[:2] in ("60", "00"):
                out.append({"code": code, "name": row.get("股票简称", "")})
        if not d.get("has_more") or not rows or page > 12:
            break
        page += 1
        time.sleep(2.5)
    fp.write_text(json.dumps(out, ensure_ascii=False))
    return out


def main():
    idx = json.loads((ROOT / "data/index_sh000001.json").read_text())
    idates = [r["date"] for r in idx]
    today = idates[-1]
    mo = today[:7]
    # 入场日走官方日历（含未来交易日）。2026-10-08 修：index_sh000001.json 由
    # update_kcache 末尾写、尾部滞后一天，会把当月入场日拖到次日才标出来（10/15 变 10/16）。
    # 日历不可用时退回旧口径（月内已知交易日够 6 个才算）。
    entry_day = tc.entry_day(mo)
    if entry_day is None:
        month_days = [d for d in idates if d.startswith(mo)]
        entry_day = month_days[5] if len(month_days) >= 6 else None

    rows = fetch_month(mo)
    if rows is None:
        state = {"month": mo, "status": "quota_dead", "entry_day": entry_day,
                 "note": "iwencai 配额耗尽，每日 08:30 自动重试；名单拿到前金股线不出票"}
        OUT.write_text(json.dumps(state, ensure_ascii=False, indent=1))
        print(f"{mo}: 配额耗尽（状态已落盘）")
        return
    if not rows:
        # 名单尚未发布 ≠ 无独家新鲜（空仓过月）。2026-10-08 修：旧口径两种都写 ok，
        # 作战单会说「本月无独家新鲜金股，空仓过月」——把「还没发」谎报成「本月空仓」。
        state = {"month": mo, "status": "pending", "entry_day": entry_day, "total": 0,
                 "solo_fresh": [],
                 "note": f"iwencai 公告期查询 0 条，每日重试；入场日={entry_day}（月第6交易日）"}
        OUT.write_text(json.dumps(state, ensure_ascii=False, indent=1))
        print(f"{mo}: 名单尚未发布（入场日 {entry_day}）")
        return
    import collections
    cnt = collections.Counter(r["code"] for r in rows)
    seen_year = set()
    for m2 in sorted(CACHE.glob(f"{today[:4]}-*.json")):
        if m2.stem >= mo:
            continue
        for r in json.loads(m2.read_text()):
            seen_year.add(r["code"])
    solo_fresh = [r for r in rows if cnt[r["code"]] == 1 and r["code"] not in seen_year]
    state = {"month": mo, "status": "ok", "entry_day": entry_day,
             "total": len(rows), "solo_fresh": solo_fresh,
             "note": f"入场日={entry_day}（月第6交易日），独家+年内首入 {len(solo_fresh)} 只，T+20 出"}
    if mo == _this_month() and len(rows) < 50:
        # 2026-10-18 加：本月名单正常 125~241 条，过少=券商发布未齐或翻页异常，必须喊出来，
        # 否则会像 2026-10 那样静默谎报「空仓过月」。
        state["warning"] = f"本月名单仅 {len(rows)} 条（正常 125~241），疑券商发布未齐/查询异常"
    # 月末预热：当月剩余交易日≤3 时顺带探下月名单（券商月末就发下月金股，缓存落盘供下月复用）
    remaining = [d for d in idates if d.startswith(mo) and d >= today]
    if len(remaining) <= 3:
        y2, m2 = int(mo[:4]), int(mo[5:7]) + 1
        if m2 > 12:
            y2, m2 = y2 + 1, 1
        nxt = f"{y2}-{m2:02d}"
        nrows = fetch_month(nxt)
        if nrows is None:
            state["next_month_note"] = f"{nxt} 名单预热失败（配额耗尽/接口异常），明日重试"
        elif not nrows:
            state["next_month_note"] = f"{nxt} 名单尚未发布，每日重试（入场日={tc.entry_day(nxt)}）"
        else:
            state["next_month_note"] = f"{nxt} 名单已预热 {len(nrows)} 条（缓存就绪，入场日={tc.entry_day(nxt)}）"
        print(state["next_month_note"])
    OUT.write_text(json.dumps(state, ensure_ascii=False, indent=1))
    print(f"{mo}: 名单 {len(rows)} 条，生产组合 {len(solo_fresh)} 只（入场日 {entry_day}）")


if __name__ == "__main__":
    sys.exit(main())
