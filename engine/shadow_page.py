"""影子单战绩页 v2（2026-09-27 深夜，用户四连问驱动）——docs/shadow.html 静态页。

修正：
1. 同事件重复登记标注：REVERSAL_OPEN_T1 与 PANIC_DEPTH_DOSE 是同批事件的两种口径
   （跌≥3% 既触发反转族也按深度进剂量档）——合并展示，剂量线只给分档表。
2. 「真实组合口径」段：5 万本金/5 槽/单仓 1 万，按时间顺序过账本——装不下的跳过，
   回答「模拟 10W 能买这么多吗」（不能——测量口径≠组合口径，两个都给）。
3. 复利连乘删除，改「累计盈亏（元，每笔固定 1 万）」。
4. 持仓周期 T+N + 预计出场日列。
"""
import bisect
import json
import statistics as st
from collections import defaultdict
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
D = ROOT / "data"
OUT = ROOT / "docs/shadow.html"

CLAIM_NAMES = {
    "LIMITDOWN_LOW_DEEP35": "深档低位T+10",
    "REVERSAL_OPEN_T1": "反转族T+1",
    "PANIC_DEPTH_DOSE": "恐慌剂量（分档）",
    "LIMITDOWN_NEXT_DAY": "跌停次日接",
    "FRONTRUN_FIRSTBOARD_V2": "抢跑首板",
    "WATCHPOOL_GRAD": "观察池毕业",
    "YAO_LAUNCH_FIRSTBOARD": "妖股启动期首板",
    "MAINLINE_DIP_RSI2": "主线回踩",
    "THREE_DOWN_GOLD": "三连阴金股",
}
CLAIM_HORIZON = {"LIMITDOWN_LOW_DEEP35": "r10", "YAO_LAUNCH_FIRSTBOARD": "r1",
                 "MAINLINE_DIP_RSI2": "r5", "THREE_DOWN_GOLD": "r20"}
# 同一批事件的重复登记（反转族与恐慌剂量同源于跌≥3%事件）
DUP_NOTE = {"PANIC_DEPTH_DOSE": "与反转族同一批事件（深度分档视图），非独立交易"}


def realistic_sim(events_by_day, days, capital=100000.0, slot=20000.0, max_pos=5):
    """真实组合口径：5槽×2万，按时间序进场，装不下跳过。返回 (终值, 成交, 跳仓, 回撤)"""
    cash, positions = capital, []
    taken = skipped = 0
    peak, mdd = capital, 0.0
    for day in days:
        for p in [p for p in positions if p["exit"] <= day]:
            cash += p["amt"] * (1 + p["ret"])
            positions.remove(p)
        for ret, hn in events_by_day.get(day, []):
            if len(positions) >= max_pos or cash < slot:
                skipped += 1
                continue
            import bisect as _bs
            j = _bs.bisect_left(days, day)
            exit_day = days[min(j + hn, len(days) - 1)]
            positions.append({"amt": slot, "ret": ret, "exit": exit_day})
            cash -= slot
            taken += 1
        mv = cash + sum(p["amt"] for p in positions)
        peak = max(peak, mv)
        mdd = min(mdd, mv / peak - 1)
    final = cash + sum(p["amt"] * (1 + p["ret"]) for p in positions)
    return final, taken, skipped, mdd


def main():
    names = {str(s["code"]).zfill(6): s.get("name", "")
             for s in json.loads((D / "main_board_codes.json").read_text())["stocks"]}
    lines = [json.loads(x) for x in (D / "claims_shadow.jsonl").read_text().splitlines()]
    idx = json.loads((D / "index_sh000001.json").read_text())
    last_day = idx[-1]["date"]
    idx_dates = [r["date"] for r in idx]

    last_px = {}
    for r in lines:
        if r.get("entry") is None:
            continue
        kc = D / "big_kcache" / f"{r['code']}.json"
        if kc.exists():
            try:
                ks = json.loads(kc.read_text())
                last_px[r["code"]] = ks[-1]["close"]
            except Exception:
                pass

    per_claim = {}
    for r in lines:
        claim = r["claim"]
        hz = CLAIM_HORIZON.get(claim, "r5")
        v = r.get(hz) if r.get(hz) is not None else r.get("r5")
        c = per_claim.setdefault(claim, {"done": [], "open": [], "done_events": []})
        if v is not None:
            c["done"].append(v)
            hold_n = int(CLAIM_HORIZON.get(claim, "r5")[1:])
            c["done_events"].append((r.get("entry_date") or r["signal_date"], v, hold_n))
        elif r.get("entry") is not None:
            c["open"].append(r)

    rows = []
    total_pnl_yuan = 0.0
    total_done = 0
    for claim, c in sorted(per_claim.items(), key=lambda kv: -len(kv[1]["done"])):
        dn = c["done"]
        nm = CLAIM_NAMES.get(claim, claim)
        hz = CLAIM_HORIZON.get(claim, "r5")
        hold_days = hz.replace("r", "T+")
        dup = f'<br><span class="mut">{DUP_NOTE[claim]}</span>' if claim in DUP_NOTE else ""
        if dn:
            wr = sum(1 for x in dn if x > 0) / len(dn)
            avg = st.mean(dn)
            pnl_yuan = sum(dn) * 10000
            total_pnl_yuan += pnl_yuan
            total_done += len(dn)
            rows.append(f"<tr><td>{nm}{dup}</td><td>{len(dn)}</td><td>{wr * 100:.0f}%</td>"
                        f"<td>{avg * 100:+.2f}%</td>"
                        f"<td class='{'pos' if pnl_yuan > 0 else 'neg'}'>{pnl_yuan:+,.0f} 元</td>"
                        f"<td>{hold_days}</td><td class='mut'>{len(c['open'])} 在途</td></tr>")
        elif c["open"]:
            rows.append(f"<tr><td>{nm}{dup}</td><td colspan='4' class='mut'>影子期数据积累中（{len(c['open'])} 单在途）</td>"
                        f"<td>{hold_days}</td><td class='mut'>{len(c['open'])} 在途</td></tr>")

    # ── 真实组合口径（10万/5槽/单仓2万，全部线混合按时间序） ──
    events_by_day = defaultdict(list)
    for claim, c in per_claim.items():
        for day, v, hn in c["done_events"]:
            events_by_day[day].append((v, hn))
    days = sorted(events_by_day)
    final, taken, skipped, mdd = realistic_sim(events_by_day, days)
    real_ret = final / 100000 - 1

    # 在途明细
    open_rows = []
    for claim, c in sorted(per_claim.items()):
        nm = CLAIM_NAMES.get(claim, claim)
        hz = CLAIM_HORIZON.get(claim, "r5")
        hold_n = int(hz[1:])
        for r in c["open"]:
            cur = last_px.get(r["code"])
            pnl = (cur / r["entry"] - 1) * 100 if cur else None
            cls = "pos" if (pnl or 0) > 0 else "neg"
            exit_day = "?"
            ed = r.get("entry_date")
            if ed and ed in idx_dates:
                j = idx_dates.index(ed)
                exit_day = idx_dates[min(j + hold_n, len(idx_dates) - 1)] if j + hold_n < len(idx_dates) else f"约{hold_n}个交易日后"
            open_rows.append(
                f"<tr><td>{names.get(r['code'], '?')}<span class='mut'> {r['code']}</span></td>"
                f"<td>{nm}</td><td>{r['signal_date']}</td><td>{r['entry']:.2f}</td>"
                f"<td>{cur if cur else '?'}</td>"
                f"<td class='{cls}'>{f'{pnl:+.1f}%' if pnl is not None else '待回填'}</td>"
                f"<td class='mut'>{exit_day} 出</td></tr>")

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>焚诀影子单战绩</title><style>
body{{font-family:-apple-system,'PingFang SC',sans-serif;max-width:860px;margin:0 auto;padding:16px;background:#fff;color:#37352f}}
h1{{font-size:20px}} table{{border-collapse:collapse;width:100%;font-size:14px;margin:10px 0 22px}}
td,th{{padding:7px 9px;border-bottom:1px solid #ededeb;text-align:left}}
.mut{{color:#9b9a97}} .pos{{color:#0f7b3d}} .neg{{color:#c0392b}}
.note{{background:#f7f6f3;border-radius:8px;padding:10px 14px;font-size:13px;color:#73726e;line-height:1.7}}
</style></head><body>
<h1>👻 影子单战绩 · 截至 {last_day}</h1>
<div class="note">影子单=系统假设「信号全跟」的纸面账户，费后净口径。<b>累计盈亏按「每笔固定 1 万本金」折算成元</b>——有界、诚实、可感知；高频线的单笔重叠不构成复利。
<b>影子期的线（在途）还没足够结算单，别拿前几单论生死</b>——3-4 周后才轮到它们开口。</div>
<h2>真实组合口径（10 万本金 · 5 槽 × 2 万 · 装不下就跳过）</h2>
<div class="note" style="font-size:16px">全部线混合按时间序跑账本：终值 <b>{final:,.0f}</b>（{real_ret * 100:+.1f}%）· 成交 {taken} 笔 · <b>跳仓 {skipped} 笔（仓位满了装不下）</b> · 最大回撤 {mdd * 100:.1f}%。
这才是「10 万块能买多少」的答案——事件洪流期大部分信号根本排不上队。</div>
<h2>影子盘总账（测量口径：所有事件都记账）</h2>
<div class="note" style="font-size:16px">从 9/11 起共结算 <b>{total_done}</b> 单，累计盈亏 <b class="{'pos' if total_pnl_yuan > 0 else 'neg'}">{total_pnl_yuan:+,.0f} 元</b>（每笔固定 1 万口径，非复利）。</div>
<h2>各线累计战绩</h2>
<table><tr><th>线</th><th>结算单数</th><th>胜率</th><th>均笔</th><th>累计盈亏</th><th>持仓</th><th>在途</th></tr>
{"".join(rows) if rows else "<tr><td colspan=7 class='mut'>还没有结算单</td></tr>"}</table>
<h2>在途持仓（还没到结算日的单）</h2>
<table><tr><th>票</th><th>线</th><th>信号日</th><th>买入价</th><th>现价</th><th>浮盈</th><th>出场日</th></tr>
{"".join(open_rows) if open_rows else "<tr><td colspan=7 class='mut'>当前没有在途影子单</td></tr>"}</table>
<div class="note">← <a href="./">回操作台</a> · 本页静态生成，随每日影子盘日更刷新 · 研究辅助不是买卖指令</div>
</body></html>"""
    OUT.write_text(html)
    print(f"shadow.html v2 built: {len(per_claim)} 线, 组合口径 {final:,.0f}（跳仓 {skipped}）")


if __name__ == "__main__":
    main()
