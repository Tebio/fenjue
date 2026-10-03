"""环境状态快照（2026-09-27 深夜，用户批「面板全面升级」）：一处计算，多处消费。

输出：regime/段龄/下阶段概率（历史转移矩阵）+ 杠杆门 + 趋势门 + 节日窗 + 深档四象限格。
消费方：ops_briefing（9:25 作战单）、dashboard_build（面板）、radar（大盘行）。
"""
import bisect
import json
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
D = ROOT / "data"

HOLIDAYS = [("2020-01-24", "春节"), ("2020-10-09", "国庆"), ("2021-02-18", "春节"), ("2021-10-08", "国庆"),
            ("2022-02-07", "春节"), ("2022-10-10", "国庆"), ("2023-01-30", "春节"), ("2023-10-09", "国庆"),
            ("2024-02-19", "春节"), ("2024-10-08", "国庆"), ("2025-02-05", "春节"), ("2025-10-09", "国庆"),
            ("2026-02-24", "春节"), ("2026-10-09", "国庆")]

# 段级转移矩阵（2026-09-27 从 regime_timeline_hcap 算出，1867 天 810 段）
NEXT_PROBS = {
    "恐慌期": {"妖股期": 0.47, "平淡期": 0.43, "主线期": 0.10},
    "平淡期": {"妖股期": 0.61, "恐慌期": 0.29, "主线期": 0.10},
    "妖股期": {"平淡期": 0.58, "恐慌期": 0.27, "主线期": 0.15},
    "主线期": {"妖股期": 0.50, "平淡期": 0.36, "恐慌期": 0.14},
}
SEG_MEDIAN_DAYS = {"恐慌期": 1, "平淡期": 2, "妖股期": 2, "主线期": 1}


def env_state(day=None):
    """全量环境快照。day=None 时用数据最新日。"""
    idx = json.loads((D / "index_sh000001.json").read_text())
    idates = [r["date"] for r in idx]
    iclose = {r["date"]: r["close"] for r in idx}
    if day is not None and not isinstance(day, str):
        day = day.isoformat()  # 调用方可能传 datetime.date
    today = day or idates[-1]
    i = bisect.bisect_left(idates, today)
    if i >= len(idates) or idates[i] != today:
        i -= 1
        today = idates[i]

    # regime + 段龄
    age = json.loads((D / "regime_age.json").read_text())
    ages = age["ages"]
    cur = ages.get(today) or age.get("today") or {}
    regime, seg_age = cur.get("regime", "?"), cur.get("age", "?")
    nxt = NEXT_PROBS.get(regime, {})
    nxt_top = max(nxt.items(), key=lambda kv: kv[1]) if nxt else ("?", 0)

    # 趋势门：指数 20 日涨跌
    trend = None
    if i >= 20:
        trend = iclose[idates[i]] / iclose[idates[i - 20]] - 1
    trend_gate = None if trend is None else ("跌>3%" if trend < -0.03 else "平/涨")

    # 杠杆门：RZYE 20 日变化
    margin_fp = D / "margin_history.json"
    margin_gate, margin_chg = None, None
    if margin_fp.exists():
        margin = json.loads(margin_fp.read_text())
        mrec = {str(r.get("date"))[:10]: float(r.get("rzye") or r.get("RZYE") or 0)
                for r in margin} if isinstance(margin, list) else margin
        mdays = sorted(mrec)
        j = bisect.bisect_right(mdays, today) - 1
        if j >= 20 and mrec[mdays[j - 20]] > 0:
            margin_chg = mrec[mdays[j]] / mrec[mdays[j - 20]] - 1
            margin_gate = ("去杠杆" if margin_chg < -0.03 else
                           "加杠杆" if margin_chg > 0.073 else "中段")

    # 节日窗（±20 自然日近似）
    import datetime
    d0 = datetime.date.fromisoformat(today)
    holiday = None
    for hd, name in HOLIDAYS:
        delta = (datetime.date.fromisoformat(hd) - d0).days
        if abs(delta) <= 20:
            holiday = (name, delta)
            break

    # 深档四象限格
    quadrant = None
    if trend_gate and margin_gate:
        quadrant = ("🟢黄金格" if trend_gate == "跌>3%" and margin_gate == "去杠杆" else
                    "🔴毒气室" if trend_gate == "平/涨" and margin_gate == "中段" else "🟡中间格")
    # 期指贴水（第三传感器 2026-09-29，仅展示不作闸门）：IF 主力连续贴水在全史的分位
    # 深贴水极值=对冲盘拥挤（独立数据源的真恐慌佐证）；换月接缝口径坑已记档，故只按分位展示
    basis_pct = basis_rank = None
    try:
        from datetime import date as _date
        fb = json.loads((D / "futures_basis.json").read_text())["IF"]["rows"]
        ty = _date.fromisoformat(today)
        if fb and abs((_date.fromisoformat(fb[-1]["date"]) - ty).days) <= 5:
            bp = [r["basis_pct"] for r in fb]
            basis_pct = fb[-1]["basis_pct"]
            basis_rank = sum(1 for b in bp if b < basis_pct) / len(bp)
    except Exception:
        pass
    # 市场温度（第四传感器 2026-09-29，终审过分年）：多头占比滚动250日分位
    # 冰点≤10%分位=T+10 64%/+0.81；过热≥90%分位=T+10 42%/-0.41（减仓侧）
    breadth_pct = breadth_rank = None
    try:
        bd = json.loads((D / "breadth_daily.json").read_text())
        days = sorted(bd)
        if days and days[-1] <= today:
            bpcts = [bd[d2]["bull_pct"] for d2 in days]
            win = bpcts[-250:]
            breadth_pct = bpcts[-1]
            breadth_rank = sum(1 for v in win if v < breadth_pct) / len(win)
    except Exception:
        pass
    return {
        "date": today, "regime": regime, "age": seg_age,
        "seg_median": SEG_MEDIAN_DAYS.get(regime, "?"),
        "next_top": nxt_top[0], "next_prob": nxt_top[1],
        "next_all": nxt,
        "trend_chg20": trend, "trend_gate": trend_gate,
        "margin_chg20": margin_chg, "margin_gate": margin_gate,
        "holiday": holiday, "quadrant": quadrant,
        "basis_pct": basis_pct, "basis_rank": basis_rank,
        "breadth_pct": breadth_pct, "breadth_rank": breadth_rank,
    }


def fmt_brief(e):
    """作战单用的单行环境摘要"""
    hol = ""
    if e["holiday"]:
        name, delta = e["holiday"]
        hol = f" · {name}{'前' if delta > 0 else '后'}{abs(delta)}天"
    mc = f"{e['margin_chg20'] * 100:+.1f}%" if e["margin_chg20"] is not None else "?"
    bs = ""
    if e.get("basis_pct") is not None:
        depth = "🔴极深" if e["basis_rank"] < 0.05 else ("🟠偏深" if e["basis_rank"] < 0.20 else "")
        bs = f" | IF贴水{e['basis_pct']:+.1f}%({e['basis_rank'] * 100:.0f}%分位{depth})"
    if e.get("breadth_pct") is not None:
        hot = "🔴过热" if e["breadth_rank"] >= 0.90 else ("🟢冰点" if e["breadth_rank"] <= 0.10 else "")
        bs += f" | 温度{e['breadth_pct'] * 100:.0f}%({e['breadth_rank'] * 100:.0f}%分位{hot})"
    return (f"{e['regime']}第{e['age']}天（段中位{e['seg_median']}天）→ 下阶段大概率 {e['next_top']}({e['next_prob'] * 100:.0f}%)"
            f" | 趋势门{e['trend_gate']} 杠杆门{e['margin_gate']}({mc}){hol}{bs}"
            + (f" | 深档{e['quadrant']}" if e["quadrant"] else ""))


if __name__ == "__main__":
    import sys
    e = env_state(sys.argv[1] if len(sys.argv) > 1 else None)
    print(json.dumps(e, ensure_ascii=False, indent=1, default=str))
    print(fmt_brief(e))
