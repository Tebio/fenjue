#!/usr/bin/env python3
"""engine/broker_reconcile.py — 实盘对账闭环 v1（MID-01 / AGENTS #263-B5）

券商成交明细 CSV → 与影子账本/信号源逐笔对账：滑点、漏单、人工偏离、费率（实付 vs 假设
0.15%）、P&L 归因草稿（执行 vs 费税 vs 待兑现 alpha）。只读既有产物，不改生产。
输出（私有，I7）：data/private/recon/reconcile_report_<YYYYMMDD>.json
用法：broker_reconcile.py <csv> [--data-dir data] [--out PATH] | --selftest（合成数据全链路）
规范见 docs/broker-trades-csv.md；费用假设口径已切 TAX-01 唯一真源 costs.FLAT_RT（0.15%）。
"""
import argparse, csv, hashlib, json, os, re, subprocess, sys, tempfile
from costs import FLAT_RT  # TAX-01 唯一真源 engine/costs.py（AGENTS #287）
from datetime import date, datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BJT = timezone(timedelta(hours=8))

DIFF_KINDS = ("missed_signal", "extra_trade", "price_gap", "fee_gap")  # v1 枚举（spec 全量 7 类）
# ── 列名映射（规范 docs/broker-trades-csv.md §3）──────────────────────────
COL_ALIASES = {
    "date":       ["成交日期", "交易日期", "日期"],
    "time":       ["成交时间", "时间"],
    "code":       ["证券代码", "股票代码", "代码"],
    "name":       ["证券名称", "股票名称", "名称"],
    "side":       ["买卖标志", "买卖方向", "委托方向", "交易类型", "业务名称", "方向"],
    "price":      ["成交价格", "成交均价", "价格"],
    "shares":     ["成交数量", "成交股数", "数量"],
    "amount":     ["成交金额", "发生金额", "金额"],
    "commission": ["佣金", "手续费", "佣金及手续费"],
    "stamp_tax":  ["印花税"],
    "transfer_fee": ["过户费"],
    "other_fee":  ["其他费用", "规费"],
}
REQUIRED = ["date", "code", "side", "price", "shares", "amount", "commission", "stamp_tax", "transfer_fee"]
BUY_WORDS, SELL_WORDS = {"买入", "证券买入", "买", "buy", "b"}, {"卖出", "证券卖出", "卖", "sell", "s"}


def _norm_num(s):
    """'10,000.50' / '￥1,234' / ' 3.05 ' → float；失败抛 ValueError。"""
    s = re.sub(r"[,，￥$\s]", "", str(s))
    return float(s)


def _norm_date(s):
    s = str(s).strip().replace("/", "-").replace(".", "-")
    if re.fullmatch(r"\d{8}", s):
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    raise ValueError(f"无法解析日期: {s!r}")


def _norm_code(s):
    m = re.search(r"(\d{6})", str(s))
    if not m:
        raise ValueError(f"无法解析证券代码: {s!r}")
    return m.group(1)


def load_broker_trades(csv_path):
    """读券商 CSV → 统一结构 list[dict]。编码 utf-8-sig→gbk 自适应；缺列/坏行显式报错；
    同一笔(日期,代码,方向,价格,数量)重复 → 去重 + warnings。"""
    raw, enc_used = None, None
    for enc in ("utf-8-sig", "gbk"):
        try:
            with open(csv_path, encoding=enc) as f:
                raw = f.read()
            enc_used = enc
            break
        except UnicodeDecodeError:
            continue
    if raw is None:
        raise SystemExit(f"[ERROR] {csv_path}: 编码既不是 utf-8-sig 也不是 gbk，无法读取")
    rows = list(csv.DictReader(raw.splitlines()))
    if not rows:
        raise SystemExit(f"[ERROR] {csv_path}: 空文件或无数据行")
    for i, r in enumerate(rows, 2):
        if None in r:
            raise SystemExit(f"[ERROR] {csv_path} 第{i}行列数多于表头——通常是未加引号的千分位数字"
                             f"（如 10,500.00）。请重新导出或给该字段加引号。原始行: {[v for k, v in r.items() if k]}")
    header = {k.strip(): k for k in rows[0].keys() if k}
    colmap = {}
    for canon, aliases in COL_ALIASES.items():
        for a in aliases:
            if a in header:
                colmap[canon] = header[a]
                break
    missing = [c for c in REQUIRED if c not in colmap]
    if missing:
        raise SystemExit(f"[ERROR] {csv_path}: 缺必需列 {missing}；已识别表头: {sorted(header)}；"
                         f"映射规范见 docs/broker-trades-csv.md")
    trades, warns, seen = [], [], set()
    for i, r in enumerate(rows, 2):
        try:
            side_raw = str(r[colmap["side"]]).strip().lower()
            side = "buy" if side_raw in BUY_WORDS else "sell" if side_raw in SELL_WORDS else None
            if side is None:
                raise ValueError(f"无法识别买卖方向: {r[colmap['side']]!r}")
            t = {
                "date": _norm_date(r[colmap["date"]]),
                "time": str(r.get(colmap.get("time", ""), "") or "").strip(),
                "code": _norm_code(r[colmap["code"]]),
                "name": str(r.get(colmap.get("name", ""), "") or "").strip(),
                "side": side,
                "price": _norm_num(r[colmap["price"]]),
                "shares": int(_norm_num(r[colmap["shares"]])),
                "amount": _norm_num(r[colmap["amount"]]),
                "commission": _norm_num(r[colmap["commission"]] or 0),
                "stamp_tax": _norm_num(r[colmap["stamp_tax"]] or 0),
                "transfer_fee": _norm_num(r[colmap["transfer_fee"]] or 0),
                "other_fee": _norm_num(r.get(colmap.get("other_fee", ""), 0) or 0),
            }
        except (ValueError, KeyError) as e:
            raise SystemExit(f"[ERROR] {csv_path} 第{i}行解析失败: {e}（原始行: {dict(r)}）")
        key = (t["date"], t["code"], t["side"], t["price"], t["shares"])
        if key in seen:
            warns.append(f"重复成交已去重: {key}")
            continue
        seen.add(key)
        t["fee_total"] = round(t["commission"] + t["stamp_tax"] + t["transfer_fee"] + t["other_fee"], 2)
        trades.append(t)
    return trades, {"encoding": enc_used, "warnings": warns, "raw_rows": len(rows)}


# ── 信号/影子账本 → 统一 intent（只读）────────────────────────────────────
def _next_weekday(dstr):
    d = date.fromisoformat(dstr) + timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d.isoformat()


def _jsonl(path):
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()] if os.path.exists(path) else []


def load_intents(data_dir):
    """intent = {code, name, entry_day, ref_price, source}。ref_price=None 只参与漏单/偏离判定。"""
    out = []
    for r in _jsonl(os.path.join(data_dir, "shadow_intents.jsonl")):
        out.append({"code": str(r["code"]), "name": r.get("name", ""), "entry_day": _norm_date(r["date"]),
                    "ref_price": r.get("buy"), "source": f"shadow_intents:{r.get('kind','?')}"})
    for r in _jsonl(os.path.join(data_dir, "banlu_signals.jsonl")):
        out.append({"code": str(r["code"]), "name": r.get("name", ""), "entry_day": _next_weekday(_norm_date(r["date"])),
                    "ref_price": r.get("close"), "source": "banlu"})  # 信号日收盘为锚，次日入场（节假日近似）
    for r in _jsonl(os.path.join(data_dir, "xrules_shadow.jsonl")):
        if r.get("entry_date") and r.get("ep"):
            out.append({"code": str(r["code"]), "name": r.get("name", ""), "entry_day": _norm_date(r["entry_date"]),
                        "ref_price": r["ep"], "source": f"xrules:{r.get('rule','?')}"})
    for r in _jsonl(os.path.join(data_dir, "ops_briefing_ledger.jsonl")):
        for item in r.get("buys", []):
            m = re.search(r"(\d{6})", str(item))
            if m:
                out.append({"code": m.group(1), "name": str(item).replace(m.group(1), "").strip(),
                            "entry_day": _norm_date(r["date"]), "ref_price": None, "source": "ops_briefing"})
    return out


# ── 对账核心 ─────────────────────────────────────────────────────────────
def reconcile(trades, intents, slip_threshold=0.005, assumed_rate=FLAT_RT, match_window_days=3):
    end = max(t["date"] for t in trades)
    end_d = date.fromisoformat(end)
    start_d = date.fromisoformat(min(t["date"] for t in trades))
    scope_floor = start_d - timedelta(days=match_window_days)  # 对账范围下限：CSV 覆盖期之前的信号不归本期
    diffs, matched_pairs, used_intents, used_trades = [], [], set(), set()

    buys = [(i, t) for i, t in enumerate(trades) if t["side"] == "buy"]
    for ti, t in buys:
        best, best_dist = None, None
        for ii, it in enumerate(intents):
            if ii in used_intents or it["code"] != t["code"]:
                continue
            dist = abs((date.fromisoformat(t["date"]) - date.fromisoformat(it["entry_day"])).days)
            if dist <= match_window_days and (best_dist is None or dist < best_dist):
                best, best_dist = ii, dist
        if best is None:
            used_trades.add(ti)
            diffs.append({"kind": "extra_trade", "code": t["code"], "name": t["name"],
                          "expected": None, "actual": f"{t['date']} 买入 @{t['price']}×{t['shares']}",
                          "delta_yuan": None, "note": "无信号买入=人工偏离"})
            continue
        it = intents[best]
        used_intents.add(best)
        slip = None
        if it["ref_price"]:
            slip = round(t["price"] / it["ref_price"] - 1, 5)
            if abs(slip) > slip_threshold:
                diffs.append({"kind": "price_gap", "code": t["code"], "name": t["name"] or it["name"],
                              "expected": it["ref_price"], "actual": t["price"], "delta_yuan": None,
                              "note": f"滑点 {slip:+.2%} 超阈 ±{slip_threshold:.1%}（{it['source']}）"})
        matched_pairs.append({"trade": t, "intent": it, "slippage": slip})

    missed, pending, out_of_scope = [], 0, 0
    for ii, it in enumerate(intents):
        if ii in used_intents:
            continue
        if date.fromisoformat(it["entry_day"]) < scope_floor:
            out_of_scope += 1  # 早于本期 CSV 覆盖范围，既不判漏也不参与匹配
            continue
        if date.fromisoformat(it["entry_day"]) + timedelta(days=match_window_days) <= end_d:
            missed.append(it)
            diffs.append({"kind": "missed_signal", "code": it["code"], "name": it["name"],
                          "expected": f"{it['entry_day']} 应买（{it['source']}）", "actual": None,
                          "delta_yuan": None, "note": "应买未买=漏单"})
        else:
            pending += 1

    fee_gap_n = 0
    for t in trades:
        rate = t["fee_total"] / t["amount"] if t["amount"] else 0
        t["fee_rate"] = round(rate, 5)
        if rate > assumed_rate:
            fee_gap_n += 1
            note = f"实付费率 {rate:.2%} > 假设 {assumed_rate:.2%}"
            if t["commission"] >= 4.99 and t["amount"] < 20000:
                note += "（最低佣金 5 元扭曲小额单）"
            diffs.append({"kind": "fee_gap", "code": t["code"], "name": t["name"],
                          "expected": assumed_rate, "actual": t["fee_rate"],
                          "delta_yuan": round(t["fee_total"] - t["amount"] * assumed_rate, 2), "note": note})

    priced = [p for p in matched_pairs if p["slippage"] is not None]
    w_slip = (sum(p["slippage"] * p["trade"]["amount"] for p in priced) /
              sum(p["trade"]["amount"] for p in priced)) if priced else None
    exec_drag = round(sum((p["trade"]["price"] - p["intent"]["ref_price"]) * p["trade"]["shares"]
                          for p in priced), 2)
    fee_drag = round(sum(t["fee_total"] for t in trades), 2)
    buys_amt = [t for t in trades if t["side"] == "buy" and t["amount"]]
    sells_amt = [t for t in trades if t["side"] == "sell" and t["amount"]]
    summary = {
        "trades": len(trades), "n_buy": len(buys_amt), "n_sell": len(sells_amt),
        "date_min": min(t["date"] for t in trades), "date_max": end,
        "intents_loaded": len(intents), "matched": len(matched_pairs),
        "missed": len(missed), "pending_intents": pending, "out_of_scope_intents": out_of_scope,
        "extra": len(used_trades),
        "miss_rate": round(len(missed) / max(1, len(matched_pairs) + len(missed)), 4),
        "slippage": {"n_priced": len(priced), "weighted_mean": round(w_slip, 5) if w_slip is not None else None,
                     "mean": round(sum(p["slippage"] for p in priced) / len(priced), 5) if priced else None,
                     "threshold": slip_threshold},
        "fees": {"total_yuan": fee_drag, "assumed_rate": assumed_rate, "fee_gap_count": fee_gap_n,
                 "buy_rate_mean": round(sum(t["fee_rate"] for t in buys_amt) / len(buys_amt), 5) if buys_amt else None,
                 "sell_rate_mean": round(sum(t["fee_rate"] for t in sells_amt) / len(sells_amt), 5) if sells_amt else None},
        "attribution_draft": {"execution_drag_yuan": exec_drag, "fee_drag_yuan": fee_drag,
                              "note": "alpha 兑现需卖出匹配+持仓台账（MID-02）；本表只拆执行与费税两段拖累"},
    }
    return {"diffs": diffs, "matched_pairs": matched_pairs, "summary": summary,
            "trades": trades, "missed": missed}


def render_brief(rep):
    s = rep["summary"]
    L = [f"实盘对账 {s['date_min']}~{s['date_max']}（成交 {s['trades']} 笔：买 {s['n_buy']} / 卖 {s['n_sell']}）"]
    sl = s["slippage"]
    wm = f"{sl['weighted_mean']:+.2%}" if sl["weighted_mean"] is not None else "n/a"
    L.append(f"· 匹配信号 {s['matched']} 笔：金额加权滑点 {wm}（阈值 ±{sl['threshold']:.1%}，"
             f"超阈 {sum(1 for d in rep['diffs'] if d['kind']=='price_gap')} 笔）")
    miss_txt = ""
    if s["missed"]:
        head = rep["missed"][:8]
        miss_txt = "：" + "、".join(f"{m['code']}{m['name']}({m['source']})" for m in head) \
                   + (f" 等{s['missed']}笔" if s["missed"] > 8 else "")
    L.append(f"· 漏单 {s['missed']} 笔（漏单率 {s['miss_rate']:.0%}，另有 {s['pending_intents']} 条信号未到对账窗、"
             f"{s.get('out_of_scope_intents', 0)} 条早于本期范围）{miss_txt}")
    extras = [d for d in rep["diffs"] if d["kind"] == "extra_trade"]
    L.append(f"· 人工偏离 {s['extra']} 笔" + ("：" + "、".join(f"{d['code']}{d['name']}" for d in extras) if extras else ""))
    f = s["fees"]
    L.append(f"· 费税合计 {f['total_yuan']:.2f} 元：买单实付均值 {f['buy_rate_mean']:.3%} / 卖单 {f['sell_rate_mean'] if f['sell_rate_mean'] is not None else 0:.3%} "
             f"vs 假设 {f['assumed_rate']:.2%}；超假设 {f['fee_gap_count']} 笔（小额最低佣金扭曲重点看）")
    a = s["attribution_draft"]
    L.append(f"· 归因草稿：执行拖累 {a['execution_drag_yuan']:+.2f} 元，费税拖累 -{a['fee_drag_yuan']:.2f} 元；{a['note']}")
    return "\n".join(L)


def _git_sha():
    try:
        return subprocess.run(["git", "-C", ROOT, "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, timeout=10).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def build_report(csv_path, data_dir, args):
    trades, meta = load_broker_trades(csv_path)
    intents = load_intents(data_dir)
    rep = reconcile(trades, intents, args.slip_threshold, args.assumed_rate, args.match_window)
    params = {"slip_threshold": args.slip_threshold, "assumed_rate": args.assumed_rate,
              "match_window_days": args.match_window}
    report = {
        "_meta": {"generated_at": datetime.now(BJT).isoformat(timespec="seconds"),
                  "params_hash": hashlib.md5(json.dumps(params, sort_keys=True).encode()).hexdigest()[:6],
                  "data_snapshot": rep["summary"]["date_max"], "code_version": _git_sha(),
                  "inputs": [csv_path, f"{data_dir}/shadow_intents.jsonl", f"{data_dir}/banlu_signals.jsonl",
                             f"{data_dir}/xrules_shadow.jsonl", f"{data_dir}/ops_briefing_ledger.jsonl"],
                  "owner": "engine.broker_reconcile"},
        "import_meta": meta, "summary": rep["summary"], "diffs": rep["diffs"],
        "matched": [{"code": p["trade"]["code"], "date": p["trade"]["date"], "fill": p["trade"]["price"],
                     "ref": p["intent"]["ref_price"], "slippage": p["slippage"], "source": p["intent"]["source"]}
                    for p in rep["matched_pairs"]],
        "trades": rep["trades"],
    }
    report["morning_brief"] = render_brief(rep)
    return report


def _selftest():
    """合成 CSV 10 笔覆盖四情形（滑点/漏单/人工偏离/费率）+ 去重 + GBK + 缺列/千分位反例。"""
    tmp = tempfile.mkdtemp(prefix="recon_selftest_")
    dd = os.path.join(tmp, "data")
    os.makedirs(dd)
    open(os.path.join(dd, "shadow_intents.jsonl"), "w").write("\n".join([
        '{"date":"20261012","code":"600001","name":"测试一","buy":10.00,"kind":"trend-top3"}',
        '{"date":"20261012","code":"600002","name":"测试二","buy":20.00,"kind":"trend-top3"}',
        '{"date":"20261013","code":"600003","name":"测试三","buy":5.00,"kind":"trend-top3"}',
        '{"date":"20261010","code":"600004","name":"测试四","buy":8.00,"kind":"trend-top3"}']))  # 600004→漏单
    open(os.path.join(dd, "banlu_signals.jsonl"), "w").write("\n".join([
        '{"date":"2026-10-14","code":"600005","name":"测试五","trigger_px":11.0,"sealed":true,"close":11.50,"regime_ok":true}',
        '{"date":"2026-10-09","code":"600006","name":"测试六","trigger_px":7.0,"sealed":true,"close":7.20,"regime_ok":true}']))  # 600006→漏单
    open(os.path.join(dd, "xrules_shadow.jsonl"), "w").write(
        '{"rule":"T1-MEGA","sig_date":"2026-10-12","code":"600007","name":"测试七","entry_date":"2026-10-13","ep":15.00,"status":"open"}')
    open(os.path.join(dd, "ops_briefing_ledger.jsonl"), "w").write('{"date":"2026-10-15","buys":["测试八 600008"]}')
    head = "成交日期,成交时间,证券代码,证券名称,买卖标志,成交价格,成交数量,成交金额,佣金,印花税,过户费,其他费用"
    rows = [
        "2026-10-12,09:31:00,600001,测试一,买入,10.02,1000,10020.00,5.00,0,0.10,0",     # 匹配 ok +0.2%
        "2026-10-12,09:32:00,600002,测试二,买入,20.24,1000,20240.00,5.06,0,0.20,0",     # 匹配 price_gap +1.2%
        "2026-10-13,09:25:00,600003,测试三,买入,5.00,100,500.00,5.00,0,0.01,0",         # 匹配, 最低佣金→fee_gap
        "2026-10-15,09:30:00,600005,测试五,买入,11.53,1000,11530.00,5.00,0,0.12,0",     # 匹配 banlu 次日 ok
        "2026-10-13,09:35:00,600007,测试七,买入,15.05,1000,15050.00,5.00,0,0.15,0",     # 匹配 xrules ok
        "2026-10-15,09:40:00,600008,测试八,买入,9.80,2000,19600.00,5.00,0,0.20,0",      # 匹配 ops(无价)
        "2026-10-14,10:00:00,600009,测试九,买入,6.00,1000,6000.00,5.00,0,0.06,0",       # extra_trade
        "2026-10-15,11:00:00,600010,测试十,买入,4.50,1000,4500.00,5.00,0,0.05,0",       # extra_trade
        '2026-10-15,14:00:00,600001,测试一,卖出,10.50,1000,"10,500.00",5.25,5.25,0.11,0',  # 卖出含印花税+千分位(带引号)
        "2026-10-12,09:31:00,600001,测试一,买入,10.02,1000,10020.00,5.00,0,0.10,0",     # 重复→去重
    ]
    csv_path = os.path.join(tmp, "trades.csv")
    open(csv_path, "w", encoding="utf-8-sig").write(head + "\n" + "\n".join(rows))
    # 反例 0：未加引号的千分位 → 必须显式报错（列错位），不得静默错解析
    bad0 = os.path.join(tmp, "bad0.csv")
    open(bad0, "w").write(head + "\n" + rows[8].replace('"', ""))
    try:
        load_broker_trades(bad0)
        raise AssertionError("未加引号千分位 CSV 未报错")
    except SystemExit as e:
        assert "千分位" in str(e), f"列错位报错信息不对: {e}"
    args = argparse.Namespace(slip_threshold=0.005, assumed_rate=FLAT_RT, match_window=3)
    rep = build_report(csv_path, dd, args)
    s, kinds = rep["summary"], [d["kind"] for d in rep["diffs"]]
    exp = {"trades": 9, "matched": 6, "missed": 2, "extra": 2}
    for k, v in exp.items():
        assert s[k] == v, f"{k}: 期望 {v} 实得 {s[k]}"
    assert kinds.count("price_gap") == 1, f"price_gap 应 1 实得 {kinds.count('price_gap')}"
    assert kinds.count("fee_gap") == 1, f"fee_gap 应 1 实得 {kinds.count('fee_gap')}"
    assert rep["import_meta"]["warnings"], "重复行应产生去重告警"
    amt = [t for t in rep["trades"] if t["side"] == "sell"][0]["amount"]
    assert abs(amt - 10500.0) < 0.01, "千分位金额应清洗为 10500"
    # 反例 1：GBK 编码
    gbk_path = os.path.join(tmp, "gbk.csv")
    open(gbk_path, "wb").write((head + "\n" + rows[0]).encode("gbk"))
    tr, meta = load_broker_trades(gbk_path)
    assert meta["encoding"] == "gbk" and len(tr) == 1, "GBK 自适应失败"
    # 反例 2：缺列必须报错
    bad = os.path.join(tmp, "bad.csv")
    open(bad, "w").write("成交日期,证券代码,买卖标志,成交价格\n2026-10-12,600001,买入,10.0")
    try:
        load_broker_trades(bad)
        raise AssertionError("缺列 CSV 未报错")
    except SystemExit as e:
        assert "缺必需列" in str(e), f"缺列报错信息不对: {e}"
    print(rep["morning_brief"])
    print(f"\n[SELFTEST OK] matched={s['matched']} missed={s['missed']} extra={s['extra']} "
          f"price_gap=1 fee_gap=1 dedup=1 gbk=ok missing_col=ok（样本目录 {tmp}）")
    return 0


def main():
    ap = argparse.ArgumentParser(description="券商成交明细 ↔ 影子账本逐笔对账（MID-01 v1）")
    ap.add_argument("csv", nargs="?", help="券商成交明细 CSV（规范 docs/broker-trades-csv.md）")
    ap.add_argument("--data-dir", default=os.path.join(ROOT, "data"))
    ap.add_argument("--out", default=None, help="默认 data/private/recon/reconcile_report_<YYYYMMDD>.json")
    ap.add_argument("--slip-threshold", type=float, default=0.005)
    ap.add_argument("--assumed-rate", type=float, default=FLAT_RT, help="假设单边总费率（默认=costs.FLAT_RT 唯一真源）")
    ap.add_argument("--match-window", type=int, default=3, dest="match_window", help="匹配窗（自然日）")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return _selftest()
    if not args.csv:
        ap.error("需要 CSV 路径，或 --selftest")
    report = build_report(args.csv, args.data_dir, args)
    out = args.out or os.path.join(ROOT, "data", "private", "recon",
                                   f"reconcile_report_{datetime.now(BJT):%Y%m%d}.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    os.replace(tmp, out)
    print(report["morning_brief"])
    print(f"\n报告已写入 {out}（私有，不进 git）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
