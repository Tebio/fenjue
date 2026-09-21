"""2026-09-21 晚间链应急混合判定（kcache 被 baostock 限流拖到~23:30，明早 9:32 出票等不了）。

三件套（与官方链数学一致，数据源临时混编：big_kcache 历史(到9/18完整) + sina 今日收盘快照）：
1. index_sh000001.json 补 9/21 bar（sina 指数快照，收盘后=终值）
2. regime：sina_pool 全市场快照 + cap_at + load_sectors → 与 regime_daily_append 完全相同的分类规则 → upsert
3. X规则线：monkeypatch lp.load_universe 注入今日 bar（内存态，不落盘 big_kcache，避免污染复权校验）→ 跑 xrules_daily.main()
   已知降级：sina 无今日成交量 → 量比 vr=1（T1-MEGA 选票排序退化为梯队优先+探测器序），
   kcache 完成后官方链会重跑复核（23:30 前后），名单若有出入以官方为准并再推送。
"""
import json
import sys
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
sys.path.insert(0, "/opt/data/scripts")
sys.path.insert(0, str(ROOT / "engine"))
from reversal_daily import sina_pool  # noqa: E402

DAY = "2026-09-21"

# ── 1. 指数 bar（sina 快照）──
import requests  # noqa: E402

def sina_index(code="sh000001"):
    r = requests.get(f"https://hq.sinajs.cn/list={code}",
                     headers={"Referer": "https://finance.sina.com.cn"}, timeout=15)
    f = r.content.decode("gbk").split("=")[1].strip('";\n').split(",")
    return {"date": DAY, "open": float(f[1]), "high": float(f[4]),
            "low": float(f[5]), "close": float(f[3]), "volume": float(f[8])}

idx_fp = ROOT / "data/index_sh000001.json"
idx = json.loads(idx_fp.read_text())
if idx[-1]["date"] < DAY:
    bar = sina_index()
    idx.append(bar)
    idx_fp.write_text(json.dumps(idx))
    print(f"1. 指数补 bar: {bar['close']}（{bar['open']}开）")
else:
    print(f"1. 指数已最新 {idx[-1]['date']}")

# ── 2. regime（同规则）──
import regime_daily_append as rda  # noqa: E402
from regime_backtest_hcap import cap_at, load_sectors  # noqa: E402
from collections import Counter  # noqa: E402

rows = sina_pool()
names = {str(s["code"]).zfill(6): s.get("name", "")
         for s in json.loads((ROOT / "data/main_board_codes.json").read_text()).get("stocks", [])}
boards, downs = [], []
for r in rows:
    pc = r.get("prev_close")
    if not pc or pc <= 0 or r["price"] <= 0:
        continue
    pct = (r["price"] / pc - 1) * 100
    if pct >= 9.8:
        boards.append({"code": r["code"], "name": names.get(r["code"], ""),
                       "cap": cap_at(r["code"], DAY) or 0, "pct": round(pct, 2)})
    elif pct <= -9.8:
        downs.append(r["code"])
n, nd = len(boards), len(downs)
small_ratio = sum(1 for b in boards if (b["cap"] or 999) < 100) / n if n else 0


def chain(sec):
    if any(k in sec for k in ("计算机", "通信", "电子", "光学", "元件", "半导体", "消费电子", "软件")):
        return "AI电子链"
    return sec


sectors = load_sectors()
secs = Counter(chain(sectors.get(b["code"], "其他")) for b in boards)
known = {k: v for k, v in secs.items() if k != "其他"}
conc = max(known.values()) / n if known else 0
ip = (idx[-1]["close"] / idx[-2]["close"] - 1) * 100
if n >= 60 and conc >= 0.22:
    regime = "主线期"
elif n >= 40 and small_ratio >= 0.65 and conc < 0.22:
    regime = "妖股期"
elif nd >= 20 or (n < 30 and ip < -1.0):
    regime = "恐慌期"
else:
    regime = "平淡期"
entry = {"date": DAY, "regime": regime, "boards_n": n, "downs": nd,
         "small%": round(small_ratio, 2), "conc": round(conc, 2), "idx": round(ip, 2),
         "boards": boards, "top_sectors": secs.most_common(5)}
a1 = rda.upsert_timeline(entry)
a2 = rda.upsert_log(entry)
print(f"2. regime {DAY}: {regime} | 涨停{n} 跌停{nd} 小市值{small_ratio:.0%} 集中{conc:.2f} 指数{ip:+.2f}% | timeline:{a1} log:{a2}")

# ── 3. X规则线（混合宇宙）──
import law_pipeline as lp  # noqa: E402

_orig_load = lp.load_universe
today_bar = {r["code"]: {"date": DAY, "open": r["open"], "high": r["price"], "low": r["price"],
                         "close": r["price"], "volume": 0, "amount": r.get("amount_yuan", 0)}
             for r in rows if r.get("prev_close") and r["prev_close"] > 0 and r["price"] > 0}


def hybrid_load():
    stocks = _orig_load()
    for code, d in stocks.items():
        bar = today_bar.get(code)
        if bar and d["date"][-1] == "2026-09-18":
            d["c"].append(bar["close"])
            d["o"].append(bar["open"])
            d["h"].append(bar["high"])
            d["l"].append(bar["low"])
            d["v"].append(bar["volume"])
            d["amt"].append(bar["amount"])
            d["date"].append(bar["date"])
            # 新 ma60 = mean(c[n-59..n]) = (ma60[n-1]*60 - c[n-60] + c[n]) / 60
            pre_sum = d["ma60"][-1] * 60 - d["c"][-61] + d["c"][-1] if len(d["c"]) > 60 else None
            d["ma60"].append(pre_sum / 60 if pre_sum else d["ma60"][-1])
            d["n"] += 1
    return stocks


lp.load_universe = hybrid_load
import xrules_daily  # noqa: E402

sys.argv = ["xrules_daily", DAY]
xrules_daily.main()
