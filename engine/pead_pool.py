#!/usr/bin/env python3
"""预增低位池·组合账本影子（2026-10-03 立项，用户批准 10万/5槽/T+20）

结构（与 law_pipeline 注册检测器 _pead_low_screen 同口径，防前视三件套）：
  池 = 沪深主板非ST，60自然日内有业绩预增/扭亏(或略增≥50%)公告（NOTICE_DATE 严格早于信号日）
       + 收盘距60日高 ≤ -20% + 流通市值 < 50亿（cap_hist PIT 日值）
组合规则（10f 纪律：测量账本≠组合账本，本模块是组合账本）：
  本金10万 / 5槽×2万 / 每交易日收盘后扫池，最深位（距60日高最低）优先排队
  T日收盘入选 → T+1【9:25 竞价挂单】买入（=开盘价，回测口径；1859事件一字开率0%，竞价可成交已实证）
  卖出双规则（2026-10-03 实测定版）：
    ①浮盈≥10%后，收盘自峰值回撤10% → 当日收盘卖（移动止损，+5.64%/68%，跨族赢家）
    ②否则持有满20个交易日 → 第20日收盘卖（机械底线）
  装不下跳过（记skip）；同一票持有期内不重复买；卖出后可再入选
  跳空无否决（实测：低开+5.8/平开+4.8/高开1-3%+6.7，高开≠毒性，竞价照常）
台账：data/pead_pool_ledger.jsonl（按 (date,action,code) 幂等，重跑零新增）
状态：data/pead_pool_state.json（持仓+待买队列）
"""
import json, glob, os, bisect, sys
from datetime import date as _date, timedelta as _td

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KC = os.path.join(ROOT, "data/big_kcache")
CAPD = os.path.join(ROOT, "data/cap_hist")
LEDGER = os.path.join(ROOT, "data/pead_pool_ledger.jsonl")
STATE = os.path.join(ROOT, "data/pead_pool_state.json")
SLOT_CASH = 20000.0
SLOTS = 5
HOLD_DAYS = 20

_names = None
def names():
    global _names
    if _names is None:
        mc = json.load(open(os.path.join(ROOT, "data/main_board_codes.json")))
        _names = {s["code"]: s["name"] for s in mc["stocks"]}
    return _names

_pead = None
def pead_map():
    """code -> sorted unique NOTICE_DATE list（预增/扭亏 或 略增>=50）"""
    global _pead
    if _pead is None:
        ev = json.load(open(os.path.join(ROOT, "data/pead_events.json")))
        m = {}
        for e in ev:
            ft = e.get("FORECASTTYPE") or ""
            inc = e.get("INCREASEL") or 0
            if (ft in ("预增", "扭亏")) or (ft == "略增" and inc >= 50):
                m.setdefault(e["SECURITY_CODE"], set()).add((e.get("NOTICE_DATE") or "")[:10])
        _pead = {c: sorted(v) for c, v in m.items()}
    return _pead

def has_pead60(code, dstr):
    """60自然日内有公告，且公告日严格早于 dstr（防披露时点前视）"""
    ds = pead_map().get(code)
    if not ds:
        return False
    y, m, dd = map(int, dstr.split("-"))
    lo = str(_date(y, m, dd) - _td(days=60))
    hi = str(_date(y, m, dd) - _td(days=1))
    i = bisect.bisect_left(ds, lo)
    return i < len(ds) and ds[i] <= hi

_cap = {}
def cap_at(code, dstr):
    if code not in _cap:
        p = os.path.join(CAPD, f"{code}.json")
        _cap[code] = json.load(open(p)) if os.path.exists(p) else []
    arr = _cap[code]
    if not arr:
        return None
    ds = [x[0] for x in arr]
    i = bisect.bisect_right(ds, dstr) - 1
    return arr[i][2] if i >= 0 else None   # r[2]=流通市值(亿)（r[1]是股价，勿用错）

_K = None
def kcache():
    global _K
    if _K is None:
        nm = names()
        _K = {}
        for f in glob.glob(os.path.join(KC, "*.json")):
            code = os.path.basename(f)[:6]
            if not (code.startswith("60") or code.startswith("00")):
                continue
            n = nm.get(code, "")
            if "ST" in n or "退" in n:
                continue
            _K[code] = json.load(open(f))
    return _K

def pool_at(dstr=None, topn=None):
    """dstr（默认=全市场最近共同交易日）的池子，按距60日高深→浅排序"""
    K = kcache()
    if dstr is None:
        dstr = max(b["date"] for bars in K.values() for b in bars[-1:])
    out = []
    for code, bars in K.items():
        idx = {b["date"]: j for j, b in enumerate(bars)}
        if dstr not in idx:
            continue
        i = idx[dstr]
        if i < 59:
            continue
        b = bars[i]
        if b["volume"] == 0:
            continue
        cap = cap_at(code, dstr)
        if cap is None or cap >= 50:
            continue
        win = bars[i - 59:i + 1]
        h60 = max(x["high"] for x in win)
        if h60 <= 0:
            continue
        pos = b["close"] / h60 - 1
        if pos > -0.20:
            continue
        if not has_pead60(code, dstr):
            continue
        out.append({"code": code, "name": names().get(code, ""), "close": b["close"],
                    "pos": round(pos, 4), "mcap": round(cap, 1), "date": dstr})
    # 排序（2026-10-03 实测定版）：<5元低价层优先（83%/+10.25%，对照归因=预增×低价交互+7.4pp），
    # 层内按距60日高深→浅（剂量单调：≤-40%档 +14.6%/92%）
    out.sort(key=lambda r: (0 if r["close"] < 5 else 1, r["pos"]))
    return out[:topn] if topn else out

def trading_days():
    idx = json.load(open(os.path.join(ROOT, "data/index_sh000001.json")))
    return [b["date"] for b in idx]

def load_state():
    if os.path.exists(STATE):
        return json.load(open(STATE))
    return {"holdings": [], "pending": [], "processed_dates": []}

def save_state(st):
    json.dump(st, open(STATE, "w"), ensure_ascii=False, indent=1)

def ledger_keys():
    keys = set()
    if os.path.exists(LEDGER):
        for line in open(LEDGER):
            try:
                r = json.loads(line)
                keys.add((r["date"], r["action"], r["code"]))
            except Exception:
                pass
    return keys

def append_ledger(rows):
    keys = ledger_keys()
    with open(LEDGER, "a") as f:
        for r in rows:
            if (r["date"], r["action"], r["code"]) in keys:
                continue
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

def daily_run():
    """每交易日收盘后跑：先结算（卖到期+成交待买），再扫池排新队。幂等。"""
    st = load_state()
    K = kcache()
    cal = trading_days()
    today = max(b["date"] for bars in K.values() for b in bars[-1:])
    if today in st["processed_dates"]:
        print(f"[SKIP] {today} 已处理")
        return
    rows = []
    # 1) 持仓处置（先移动止损，再到期机械卖）
    still = []
    for h in st["holdings"]:
        bars = K.get(h["code"], [])
        bidx = {b["date"]: j for j, b in enumerate(bars)}
        entry_i = bidx.get(h["entry_date"])
        if entry_i is None or today not in bidx:
            still.append(h); continue
        tb = bars[bidx[today]]
        if tb["volume"] == 0:
            still.append(h); continue
        close = tb["close"]
        h["peak"] = max(h.get("peak", h["entry_px"]), close)
        held = bidx[today] - entry_i
        sell_reason = None
        if h["peak"] / h["entry_px"] - 1 >= 0.10 and close <= h["peak"] * 0.90:
            sell_reason = "trail"      # 浮盈>=10%后自峰值回撤10%（实测定版规则①）
        elif held >= HOLD_DAYS:
            sell_reason = "expire"     # 满20交易日机械卖（规则②）
        if sell_reason:
            ret = close / h["entry_px"] - 1
            rows.append({"date": today, "action": "sell", "code": h["code"],
                         "name": names().get(h["code"], ""), "price": close,
                         "reason": sell_reason, "ret": round(ret, 4),
                         "pnl": round(h["shares"] * (close - h["entry_px"]), 2),
                         "entry_date": h["entry_date"], "entry_px": h["entry_px"]})
        else:
            still.append(h)
    st["holdings"] = still
    # 2) 成交昨日排的待买（今日开盘价）
    for p in st["pending"]:
        bars = K.get(p["code"], [])
        bidx = {b["date"]: j for j, b in enumerate(bars)}
        if today not in bidx or bars[bidx[today]]["volume"] == 0:
            rows.append({"date": today, "action": "skip", "code": p["code"],
                         "name": names().get(p["code"], ""), "reason": "停牌买不进"})
            continue
        op = bars[bidx[today]]["open"]
        shares = int(SLOT_CASH // (op * 100)) * 100
        if shares <= 0:
            rows.append({"date": today, "action": "skip", "code": p["code"],
                         "name": names().get(p["code"], ""), "reason": "2万买不足一手"})
            continue
        st["holdings"].append({"code": p["code"], "entry_date": today, "entry_px": op,
                               "shares": shares, "pos0": p["pos"], "mcap": p["mcap"]})
        rows.append({"date": today, "action": "buy", "code": p["code"],
                     "name": names().get(p["code"], ""), "price": op, "shares": shares})
    st["pending"] = []
    # 3) 扫池排新队（今日收盘口径，明日开盘买）
    free = SLOTS - len(st["holdings"])
    held_codes = {h["code"] for h in st["holdings"]}
    pool = pool_at(today)
    queued = 0
    for c in pool:
        if queued >= free:
            break
        if c["code"] in held_codes:
            continue
        st["pending"].append(c)
        queued += 1
    if queued == 0 and free > 0:
        rows.append({"date": today, "action": "scan", "code": "-",
                     "name": f"池{len(pool)}只/空槽{free}/无新排队"})
    st["processed_dates"].append(today)
    save_state(st)
    append_ledger(rows)
    print(f"[OK] {today} 持仓{len(st['holdings'])} 新排队{queued} 池{len(pool)} 台账+{len(rows)}")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "pool":
        topn = int(sys.argv[2]) if len(sys.argv) > 2 else 20
        for c in pool_at(topn=topn):
            print(f"{c['code']} {c['name']:<8} 收盘{c['close']:<8} 距60日高{c['pos']*100:6.1f}% 流通{c['mcap']}亿")
    else:
        daily_run()
