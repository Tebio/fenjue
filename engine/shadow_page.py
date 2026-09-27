"""影子单战绩页（2026-09-27，用户令「单独搞个影子单页面」）——docs/shadow.html 静态页。

内容：
1. 每条线的累计战绩（claims_shadow.jsonl 全史）：线名/单数/胜率/均笔/复利净值
2. 在途持仓（entry 已填、未到结算期）：票名+入场日+买入价+现价+浮盈%
3. 每日净值轨迹（按出场日归因的逐笔复利）
零 JS 依赖（服务端渲染静态表）——面板 JS 事故的教训：能不动的别动。
"""
import json
import statistics as st
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
D = ROOT / "data"
OUT = ROOT / "docs/shadow.html"

CLAIM_NAMES = {
    "LIMITDOWN_LOW_DEEP35": "深档低位T+10",
    "REVERSAL_OPEN_T1": "反转族T+1",
    "PANIC_DEPTH_DOSE": "恐慌剂量",
    "LIMITDOWN_NEXT_DAY": "跌停次日接",
    "FRONTRUN_FIRSTBOARD_V2": "抢跑首板",
    "WATCHPOOL_GRAD": "观察池毕业",
    "YAO_LAUNCH_FIRSTBOARD": "妖股启动期首板",
    "MAINLINE_DIP_RSI2": "主线回踩",
    "THREE_DOWN_GOLD": "三连阴金股",
}
CLAIM_HORIZON = {"LIMITDOWN_LOW_DEEP35": "r10", "YAO_LAUNCH_FIRSTBOARD": "r1",
                 "MAINLINE_DIP_RSI2": "r5", "THREE_DOWN_GOLD": "r20"}


def main():
    names = {str(s["code"]).zfill(6): s.get("name", "")
             for s in json.loads((D / "main_board_codes.json").read_text())["stocks"]}
    lines = [json.loads(x) for x in (D / "claims_shadow.jsonl").read_text().splitlines()]
    idx = json.loads((D / "index_sh000001.json").read_text())
    last_day = idx[-1]["date"]

    # 现价（持仓浮盈用）
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

    # 每线战绩（用各线的主 horizon；没有的用 r5）
    per_claim = {}
    for r in lines:
        claim = r["claim"]
        hz = CLAIM_HORIZON.get(claim, "r5")
        v = r.get(hz) if r.get(hz) is not None else r.get("r5")
        c = per_claim.setdefault(claim, {"done": [], "open": []})
        if v is not None:
            c["done"].append(v)
        elif r.get("entry") is not None:
            c["open"].append(r)

    rows = []
    for claim, c in sorted(per_claim.items(), key=lambda kv: -len(kv[1]["done"])):
        dn = c["done"]
        nm = CLAIM_NAMES.get(claim, claim)
        if dn:
            wr = sum(1 for x in dn if x > 0) / len(dn)
            avg = st.mean(dn)
            nav = 1.0
            for x in dn:
                nav *= 1 + x
            rows.append(f"<tr><td>{nm}</td><td>{len(dn)}</td><td>{wr * 100:.0f}%</td>"
                        f"<td>{avg * 100:+.2f}%</td><td>{(nav - 1) * 100:+.1f}%</td>"
                        f"<td class='mut'>{len(c['open'])} 在途</td></tr>")
        elif c["open"]:
            rows.append(f"<tr><td>{nm}</td><td colspan='4' class='mut'>影子期数据积累中（前 {len(c['open'])} 单在途）</td>"
                        f"<td class='mut'>{len(c['open'])} 在途</td></tr>")

    # 在途明细
    open_rows = []
    for claim, c in sorted(per_claim.items()):
        nm = CLAIM_NAMES.get(claim, claim)
        for r in c["open"]:
            cur = last_px.get(r["code"])
            pnl = (cur / r["entry"] - 1) * 100 if cur else None
            cls = "pos" if (pnl or 0) > 0 else "neg"
            open_rows.append(
                f"<tr><td>{names.get(r['code'], '?')}<span class='mut'> {r['code']}</span></td>"
                f"<td>{nm}</td><td>{r['signal_date']}</td><td>{r['entry']:.2f}</td>"
                f"<td>{cur if cur else '?'}</td>"
                f"<td class='{cls}'>{f'{pnl:+.1f}%' if pnl is not None else '待回填'}</td></tr>")

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
<div class="note">影子单=系统假设「信号全跟」的纸面账户，费后净口径。胜率/均笔是单笔统计，复利净值是把每笔收益连乘（纸面满仓口径，仅作线间对比）。
<b>影子期的线（在途）还没足够结算单，别拿前几单论生死</b>——3-4 周后才轮到它们开口。</div>
<h2>各线累计战绩</h2>
<table><tr><th>线</th><th>结算单数</th><th>胜率</th><th>均笔</th><th>复利净值</th><th>在途</th></tr>
{"".join(rows) if rows else "<tr><td colspan=6 class='mut'>还没有结算单</td></tr>"}</table>
<h2>在途持仓（还没到结算日的单）</h2>
<table><tr><th>票</th><th>线</th><th>信号日</th><th>买入价</th><th>现价</th><th>浮盈</th></tr>
{"".join(open_rows) if open_rows else "<tr><td colspan=6 class='mut'>当前没有在途影子单</td></tr>"}</table>
<div class="note">← <a href="./">回操作台</a> · 本页静态生成，随每日影子盘日更刷新 · 研究辅助不是买卖指令</div>
</body></html>"""
    OUT.write_text(html)
    print(f"shadow.html built: {len(per_claim)} 线, {sum(len(c['open']) for c in per_claim.values())} 在途")


if __name__ == "__main__":
    main()
