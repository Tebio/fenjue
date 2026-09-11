#!/usr/bin/env python3
"""R5-B 实验：伪缠论 B1 + 组合规则（昨日首板+板块龙头+竞价高开）双回测。
纪律：前复权 big_kcache、信号次日开盘成交、净 -0.15%、分型确认延迟显式处理、
随机对照 + 反转族对照。只沪深主板（kcache 即主板池）。"""
import json, glob, random, statistics as st
from collections import defaultdict
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
FEE = 0.15

# ── 行业映射（板块联动用）──
imap = json.load(open(ROOT / "data" / "industry_map.json"))
SECTOR = {str(k).zfill(6): (v.get("industry", "") if isinstance(v, dict) else str(v))
          for k, v in imap.items()}


def macd_dif_series(closes):
    ema12, ema26, dea = closes[0], closes[0], 0.0
    difs = []
    for c in closes:
        ema12 = ema12 * 11 / 13 + c * 2 / 13
        ema26 = ema26 * 25 / 27 + c * 2 / 27
        dif = ema12 - ema26
        dea = dea * 8 / 10 + dif * 2 / 10
        difs.append(dif)
    return difs


def bottom_fractals(ks):
    """返回 {确认日i: 中间bar(i-1)}。底分型=中间bar的高低点都是三根里最低。
    确认日 = 第三根 bar 收盘后才知道 → 信号时点=确认日，入场=确认日次日开盘。"""
    out = {}
    for i in range(2, len(ks)):
        a, b, c = ks[i - 2], ks[i - 1], ks[i]
        if (float(b["low"]) < float(a["low"]) and float(b["low"]) < float(c["low"]) and
                float(b["high"]) < float(a["high"]) and float(b["high"]) < float(c["high"])):
            out[i] = i - 1
    return out


def run():
    files = sorted(glob.glob(str(ROOT / "data" / "big_kcache" / "*.json")))
    kdata = {}
    for fp in files:
        code = fp.split("/")[-1][:6]
        try:
            ks = json.load(open(fp))
            if len(ks) >= 60:
                kdata[code] = ks
        except Exception:
            pass
    print(f"股票数: {len(kdata)}")

    # ── 实验1：伪缠论 B1（底分型确认 + MACD 背驰近似 + 缩量）──
    chan_events = []       # (date, ret_t1, ret_t5)
    rev_events = []        # 反转族对照 prev_cc<=-3
    all_days = []          # 随机对照池
    for code, ks in kdata.items():
        closes = [float(k["close"]) for k in ks]
        vols = [float(k["volume"]) for k in ks]
        difs = macd_dif_series(closes)
        fr = bottom_fractals(ks)
        fr_confirms = sorted(fr.keys())
        for i in range(30, len(ks) - 6):
            # 反转族对照（prev_cc <= -3%）
            if closes[i - 1] / closes[i - 2] - 1 <= -0.03:
                rev_events.append((closes[i] / closes[i] * 0 + (0), i))  # placeholder
            if i not in fr:
                continue
            mid = fr[i]
            prev_mids = [fr[j] for j in fr_confirms if j < i]
            if not prev_mids:
                continue
            prev_mid = prev_mids[-1]
            if prev_mid >= mid or i - prev_mid < 5:
                continue
            price_lower = float(ks[mid]["low"]) < float(ks[prev_mid]["low"])
            dif_higher = difs[mid] > difs[prev_mid]
            shrink = vols[i] < sum(vols[max(0, i - 20):i]) / max(1, len(vols[max(0, i - 20):i]))
            if price_lower and dif_higher and shrink:
                entry = float(ks[i + 1]["open"])
                if entry <= 0:
                    continue
                r1 = (closes[i + 1] / entry - 1) * 100 - FEE
                r5 = (closes[i + 5] / entry - 1) * 100 - FEE
                chan_events.append((ks[i]["date"], r1, r5))
    # 反转族对照重算（干净版）
    rev_events = []
    for code, ks in kdata.items():
        closes = [float(k["close"]) for k in ks]
        for i in range(2, len(ks) - 1):
            if closes[i - 1] / closes[i - 2] - 1 <= -0.03:
                entry = float(ks[i]["open"])
                if entry > 0:
                    rev_events.append((closes[i] / entry - 1) * 100 - FEE)
    # 随机对照：全市场随机 stock-day，次日开盘买尾盘卖
    random.seed(42)
    rand_events = []
    pool = [(c, ks) for c, ks in kdata.items()]
    for _ in range(20000):
        c, ks = random.choice(pool)
        closes = [float(k["close"]) for k in ks]
        i = random.randrange(2, len(ks) - 1)
        entry = float(ks[i]["open"])
        if entry > 0:
            rand_events.append((closes[i] / entry - 1) * 100 - FEE)

    def agg(rs, label):
        if not rs:
            return f"{label}: n=0"
        w = sum(1 for x in rs if x > 0) / len(rs) * 100
        return f"{label}: n={len(rs)} 胜率{w:.1f}% 均值{st.mean(rs):+.2f}% 中位{st.median(rs):+.2f}%"

    print("\n=== 实验1：伪缠论 B1（底分型+MACD背驰+缩量，次日开盘买）===")
    print(agg([e[1] for e in chan_events], "伪缠论B1 T+1尾盘"))
    print(agg([e[2] for e in chan_events], "伪缠论B1 T+5"))
    print(agg(rev_events, "对照-反转族(跌3%) T+1"))
    print(agg(rand_events, "对照-随机 T+1"))

    # ── 实验2：组合规则（昨日首板 + 板块有≥3板龙头 + 今开+2~4%，开盘买）──
    # 预计算：每只股票每日 连板数 & 首板标记（60日内首次涨停）
    print("\n=== 实验2：组合规则 ===")
    limstreak = {}   # code -> {i: streak}
    first_board = {} # code -> set(i)
    for code, ks in kdata.items():
        closes = [float(k["close"]) for k in ks]
        st_map, fb = {}, set()
        streak = 0
        for i in range(1, len(ks)):
            if closes[i] / closes[i - 1] - 1 >= 0.098:
                streak += 1
            else:
                streak = 0
            st_map[i] = streak
            if streak == 1:
                # 60日内首次涨停
                if not any(st_map.get(j, 0) >= 1 for j in range(max(0, i - 60), i)):
                    fb.add(i)
        limstreak[code] = st_map
        first_board[code] = fb
    # 按日期建板块龙头表：date -> sector -> max streak
    date_sector_max = defaultdict(lambda: defaultdict(int))
    for code, ks in kdata.items():
        sec = SECTOR.get(code, "")
        if not sec:
            continue
        for i, st_ in limstreak[code].items():
            if st_ >= 1:
                d = ks[i]["date"]
                if st_ > date_sector_max[d][sec]:
                    date_sector_max[d][sec] = st_
    combo, combo_nodragon, plain_fb = [], [], []
    for code, ks in kdata.items():
        closes = [float(k["close"]) for k in ks]
        sec = SECTOR.get(code, "")
        for i in range(1, len(ks) - 1):
            if i - 1 not in first_board.get(code, ()):  # 昨日不是首板
                continue
            o = float(ks[i]["open"])
            if o <= 0:
                continue
            og = o / closes[i - 1] - 1
            if not (0.02 <= og <= 0.04):
                continue
            r_close = (closes[i] / o - 1) * 100 - FEE           # 当日尾盘
            r_next = (closes[i + 1] / o - 1) * 100 - FEE        # 次日尾盘
            dragon = date_sector_max[ks[i - 1]["date"]].get(sec, 0) >= 3 if sec else False
            (combo if dragon else combo_nodragon).append((r_close, r_next))
            plain_fb.append((r_close, r_next))
    def agg2(ev, label):
        if not ev:
            return f"{label}: n=0"
        rc = [e[0] for e in ev]; rn = [e[1] for e in ev]
        return (f"{label}: n={len(ev)} | 当日尾盘 胜率{sum(1 for x in rc if x>0)/len(rc)*100:.1f}% "
                f"均值{st.mean(rc):+.2f}% | 次日尾盘 胜率{sum(1 for x in rn if x>0)/len(rn)*100:.1f}% "
                f"均值{st.mean(rn):+.2f}%")
    print(agg2(combo, "组合规则(首板+板块≥3板龙头+高开2-4%)"))
    print(agg2(combo_nodragon, "对照(首板+高开2-4%,无龙头)"))
    print(agg2(plain_fb, "对照(首板+高开2-4%,全量)"))

    # ── 明日标的预筛（用今日数据）：今日首板 + 板块有≥3板龙头 ──
    print("\n=== 明日组合规则观察名单（今日首板且板块有≥3板龙头）===")
    today = max(k["date"] for k in next(iter(kdata.values())))
    # 日期可能不全同步，用全市场最大日期
    today = max(ks[-1]["date"] for ks in kdata.values())
    watch = []
    for code, ks in kdata.items():
        if ks[-1]["date"] != today:
            continue
        i = len(ks) - 1
        if i in first_board.get(code, ()):  # 今日首板
            sec = SECTOR.get(code, "")
            if sec and date_sector_max[today].get(sec, 0) >= 3:
                watch.append((code, ks[-1].get("name", code), sec))
    # 名字不在 kcache 里，从 regime_log 的 boards 拿
    names = {}
    for l in open(ROOT / "data" / "regime_log.jsonl"):
        for b in json.loads(l).get("boards", []):
            names[b["code"]] = b["name"]
    for code, _, sec in sorted(watch, key=lambda x: x[2]):
        print(f"  {code} {names.get(code,'?')} [{sec}]")
    print(f"共 {len(watch)} 只。明早竞价高开 2-4% 才触发，其他开盘幅度不动作。")


if __name__ == "__main__":
    run()
