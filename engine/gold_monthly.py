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

ROOT = Path("/opt/data/fenjue")
CACHE = ROOT / "data/gold_stock_cache"
CLI = ROOT.parent / ".iwencai-skillhub/skills/hithink-insresearch-query/scripts/cli.py"
OUT = ROOT / "data/gold_current.json"

env = dict()
for line in Path("/opt/data/.env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        env[k] = v


def fetch_month(mo):
    """拉一月名单；配额耗尽返回 None（不写缓存），成功写缓存返回列表"""
    fp = CACHE / f"{mo}.json"
    if fp.exists():
        cached = json.loads(fp.read_text())
        if cached:
            return cached
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
    month_days = [d for d in idates if d.startswith(mo)]
    entry_day = month_days[5] if len(month_days) >= 6 else None

    rows = fetch_month(mo)
    if rows is None:
        state = {"month": mo, "status": "quota_dead", "entry_day": entry_day,
                 "note": "iwencai 配额耗尽，每日 08:30 自动重试；名单拿到前金股线不出票"}
        OUT.write_text(json.dumps(state, ensure_ascii=False, indent=1))
        print(f"{mo}: 配额耗尽（状态已落盘）")
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
    OUT.write_text(json.dumps(state, ensure_ascii=False, indent=1))
    print(f"{mo}: 名单 {len(rows)} 条，生产组合 {len(solo_fresh)} 只（入场日 {entry_day}）")


if __name__ == "__main__":
    sys.exit(main())
