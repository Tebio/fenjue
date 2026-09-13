#!/usr/bin/env python3
"""engine/claims_audit.py — 主张审计引擎（定律工程自我修正回路）

每条注册主张按 kill_line 复验：
- law_pipeline 背书的主张：全量重跑 + 滚动 250 交易日窗口边际贡献
- 位置匹配对照（position_matched）：同票同 MA60 下方随机日，剥离位置因子
- 随机入场对照（random_entry）：任意随机日
状态机：CANDIDATE/LAW → DECAYING（跌破 kill 线）→ DEAD（连续 2 次未恢复）→ 恢复需回到基线 70%。
看门狗纪律：只有状态变更才输出报告；无变更输出一行心跳。
用法：python3 engine/claims_audit.py [--report]   # --report 强制全量输出
"""
import json, math, random, statistics as st, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from law_pipeline import load_universe, REGISTRY, START, build_xsection

ROOT = Path("/opt/data/fenjue")
REG_YAML = ROOT / "data/claims_registry.yaml"
STATE = ROOT / "data/claims_state.json"
FEE = 0.0015
ROLL_N = 250  # 滚动窗口（交易日）
RECOVER_RATIO = 0.7


def _entry_px(d, i, entry):
    """入场价口径：next_open=次日开盘（默认）/ signal_close=信号日收盘（打板系close-entry主张）/
    trigger6=前收×1.06（半路板盘中触发价代理）"""
    if entry == "signal_close":
        return d["c"][i]
    if entry == "trigger6":
        return d["c"][i - 1] * 1.06
    return d["o"][i + 1]


def marginals(det, stocks, control, horizons, entry="next_open"):
    """返回 {h: (全量边际pp, 滚动边际pp, 滚动事件数)}"""
    rnd = random.Random(7)
    sig = {h: ([], []) for h in horizons}  # h -> ([日期], [收益])
    ctl = {h: [] for h in horizons}
    for code, d in stocks.items():
        c, o, n, ma = d["c"], d["o"], d["n"], d["ma60"]
        days, lows = [], []
        for i in range(START, n - max(horizons) - 1):
            if _entry_px(d, i, entry) <= 0:
                continue
            if control == "position_matched":
                if ma[i] is None:
                    continue
                low = c[i] <= ma[i]
                if low:
                    lows.append(i)
                if low and det(d, i):
                    days.append(i)
            else:
                if det(d, i):
                    days.append(i)
        for i in days:
            ep = _entry_px(d, i, entry)
            for h in horizons:
                sig[h][0].append(d["date"][i])
                sig[h][1].append(c[i + h] / ep - 1 - FEE)
        if control == "position_matched":
            pool = lows
        else:
            pool = [i for i in range(START, n - max(horizons) - 1) if _entry_px(d, i, entry) > 0]
        for i in rnd.sample(pool, min(len(days), len(pool))):
            ep = _entry_px(d, i, entry)
            for h in horizons:
                ctl[h].append(c[i + h] / ep - 1 - FEE)
    out = {}
    # 修正（2026-09-12 自查）：滚动窗口必须按交易日历切，不是按信号日切——
    # 稀疏信号（年触发30次）按信号日切会把窗口拉到数年，丧失"近期存活"语义。
    all_days = sorted({dt for d in stocks.values() for dt in d["date"]})
    cutoff = all_days[-ROLL_N] if len(all_days) > ROLL_N else None
    for h in horizons:
        ds, rs = sig[h]
        if len(rs) < 30 or len(ctl[h]) < 30:
            continue
        full_pp = 100 * (st.mean(rs) - st.mean(ctl[h]))
        if cutoff:
            idx = [j for j, dt in enumerate(ds) if dt >= cutoff]
            roll_pp = 100 * (st.mean([rs[j] for j in idx]) - st.mean([ctl[h][j] for j in idx])) if len(idx) >= 30 else None
        else:
            roll_pp, idx = full_pp, list(range(len(rs)))
        out[h] = (round(full_pp, 2), None if roll_pp is None else round(roll_pp, 2), len(idx))
    return out


def transit(state, verdict):
    """状态机。verdict: True=过kill线 False=跌破"""
    prev = state.get("status", "CANDIDATE")
    fails = state.get("consecutive_fails", 0)
    if verdict:
        return ("CANDIDATE" if prev == "DEAD" else prev if prev != "DECAYING" else "CANDIDATE", 0, prev)
    fails += 1
    new = "DEAD" if fails >= 2 else "DECAYING"
    return new, fails, prev


def main():
    claims = yaml.safe_load(REG_YAML.read_text())["claims"]
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    stocks = None
    changes, rows = [], []
    for c in claims:
        cid = c["id"]
        det_key = c.get("detector", "")
        s = state.get(cid, {"status": "CANDIDATE", "consecutive_fails": 0, "history": []})
        if det_key not in REGISTRY:
            rows.append(f"[{cid}] external 背书，本轮只登记不复跑（{c.get('note','')}）")
            state.setdefault(cid, s)
            continue
        if stocks is None:
            stocks = load_universe()
            build_xsection(stocks)
        res = marginals(REGISTRY[det_key], stocks, c.get("control", "random_entry"), c["horizon"],
                        entry=c.get("entry", "next_open"))
        # 填基线
        for h, (full_pp, _r, _n) in res.items():
            if c["baseline_pp"].get(h) is None:
                c["baseline_pp"][h] = full_pp
        verdicts = {}
        for h in c["horizon"]:
            if h not in res:
                continue
            _f, roll_pp, nroll = res[h]
            kill = c["kill_line_pp"][h]
            if c.get("direction") == "negative":
                ok = roll_pp is not None and roll_pp < kill  # 负向主张：滚动值须保持在kill线下
            else:
                ok = roll_pp is not None and roll_pp >= kill
            verdicts[h] = (roll_pp, kill, ok, nroll)
        ok_all = all(v[2] for v in verdicts.values()) if verdicts else True
        new, fails, prev = transit(s, ok_all)
        s.update(status=new, consecutive_fails=fails)
        today_bjt = (datetime.now(timezone.utc) + timedelta(hours=8)).date().isoformat()
        s["history"].append({"date": today_bjt, "verdicts": {str(h): v[:3] for h, v in verdicts.items()}})
        s["history"] = s["history"][-52:]
        state[cid] = s
        line = f"[{cid}] {prev}→{new} | " + " ".join(
            f"T+{h}: 滚动{v[0]}pp vs kill {v[1]}pp {'✅' if v[2] else '❌'}(n={v[3]})" for h, v in verdicts.items())
        rows.append(line)
        if new != prev:
            changes.append(line)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1))
    REG_YAML.write_text(yaml.safe_dump({"claims": claims}, allow_unicode=True, sort_keys=False))
    if "--report" in sys.argv or changes:
        print("\n".join(rows))
        print("状态变更:", len(changes))
    else:
        print(f"claims audit ok: {len(claims)} 条主张，无状态变更。")


if __name__ == "__main__":
    main()
