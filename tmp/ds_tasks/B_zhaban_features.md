# 任务B：炸板回封「浅炸/深炸」的事前可分特征筛查

## 背景
炸板回踩挂单策略已被判负期望（逆向选择：回封的买不进、买得进的全是失败票），
但残留一个活口：**浅炸子集（当日最低涨幅3%~8.5%）每成交期望 +4.5~5.3%/胜率75-80% 为真，
深炸（最低<3%）剧毒**——问题是事发时不知道会炸多深。
本任务：找「事前（信号日上午）可分」的特征，把未来浅炸和未来深炸分开。

## 数据（全部本地，只读）
- data/m60_cache/<code>.json：不复权60分钟bar，[{"day":"YYYY-MM-DD HH:MM","open","high","low","close","volume",...},...]，窗口 2024-08-30..2026-09-11，3234只
- data/big_kcache/<code>.json：前复权日K [{"date","open","high","low","close","volume","amount",...}]（算比率安全）
- data/cap_hist/<code>.json：[[date, price, 流通市值亿],...]
- 信号定义（与既有研究一致）：昨日涨停（收/前收-1≥+9.8%）且 今日开盘≥昨收×1.05
-  outcome：挂单价=昨收×1.07，成交规则=bar.open≤限价按open、bar.low≤限价按限价、否则未成交；
  浅炸=当日最低涨幅∈[3%,8.5%]，深炸=<3%；收益=T+1收盘/成交价-1-0.0015；每信号期望含未成交=0

## 候选事前特征（信号日10:30前可知，全部要用「当日10:30前/昨日及以前」数据，严禁用全天数据）
1. 昨日是否60日首板（big_kcache 比率判定）
2. 昨日封板时间（m60：昨日首根 high≥前收×1.098 的bar → 早盘(≤10:30)/午盘/尾盘(≥14:00)）
3. 昨日量比（昨日量/前5日均量，big_kcache）
4. 今开幅度档（5~6%/6~7%/7~8%/8%+）
5. 信号日首30分钟量能 vs 昨日首30分钟（m60 首bar）
6. 市值带（cap_hist 当月：<50/50-150/150-400/>400亿）
7. 距60日高点距离（big_kcache）

## 交付物
新文件 engine/zhaban_features.py，完整可运行，输出 data/zhaban_features_20260913.json：
- 每个特征×分档的：信号数/浅炸率/每信号期望%/每成交期望%（挂+7%口径）
- 时间分半验证：train=≤2025-08-31，test=2025-09-01起，所有结论两段并列
- 若找到可分特征：给出决策规则（如「只做X且Y」）+ train/test 两段的每信号期望+样本数
- 若全不可分：如实输出「不可分」+ 证据表，禁止硬凑规则
- 多重检验纪律：明文报告一共测了多少个分档格子

## 硬断言
- 特征计算不得引用信号日 10:30 之后的 bar（除 outcome 外）
- 每信号期望必须把未成交计 0 计入

## 附：既有成交重测源码（engine/zhaban_m60_fill.py，复用其 daily_bars/成交规则逻辑）
```python
#!/usr/bin/env python3
"""engine/zhaban_m60_fill.py — 炸板回踩挂单的成交现实重测（2026-09-12）

动机：zhaban_backtest（日K）的 opt/mid 入场是成交子集乐观口径，撞 #35 限价单恒等式坑。
本模块在 m60 空间全自洽重测（不复权 60 分钟 bar，2024-08-30..2026-09-11，3234 只）：
  信号：m60 聚合日K重判（昨收→今收 ≥+9.8% 涨停；今开≥+5%；今日最低涨幅∈[3%,8.5%]）
  挂单：限价 = 昨收×(1+X)，X∈{6%,7%,8%}
  成交规则（保守）：bar.open≤限价→按 bar.open 成交；bar.low≤限价→按限价成交；否则未成交=0
  出场：T+1 开盘（次日首 bar open）/ T+1 收盘（次日末 bar close），费 0.15%
  关键输出：成交率（R/U 分组=逆向选择定量）、每信号期望（未成交=0）、每成交期望
残留乐观（诚实标注）：60 分钟粒度，秒级触碰+薄队列的不可成交无法识别——成交率仍偏高。
"""
import json, sys, statistics as st
from collections import defaultdict
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
M60 = ROOT / "data/m60_cache"
FEE = 0.0015
LIMITS = [0.06, 0.07, 0.08]


def S(rs):
    if len(rs) < 30:
        return None
    m = st.mean(rs)
    return {"n": len(rs), "win%": round(100*sum(r > 0 for r in rs)/len(rs), 1),
            "mean%": round(100*m, 2), "med%": round(100*st.median(rs), 2)}


def daily_bars(rows):
    """m60 → 日K（不复权）。"""
    days = defaultdict(list)
    for r in rows:
        days[r["day"][:10]].append(r)
    out = []
    for dt in sorted(days):
        bs = sorted(days[dt], key=lambda r: r["day"])
        out.append({"date": dt, "open": float(bs[0]["open"]),
                    "high": max(float(b["high"]) for b in bs),
                    "low": min(float(b["low"]) for b in bs),
                    "close": float(bs[-1]["close"]), "bars": bs})
    return out


def main():
    per_limit = {x: {"sig": [], "fill_open": [], "fill_close": [], "fill_R": [], "fill_U": [],
                     "band_open": [], "band_close": [],
                     "n_sig": 0, "n_fill": 0, "n_R": 0, "n_U": 0, "fill_in_R": 0,
                     "n_band": 0, "n_deep": 0} for x in LIMITS}
    files = sorted(M60.glob("*.json"))
    for k, fp in enumerate(files):
        if k % 500 == 0:
            print(f"progress {k}/{len(files)}", flush=True)
        try:
            rows = json.loads(fp.read_text())
        except Exception:
            continue
        dk = daily_bars(rows)
        for i in range(2, len(dk) - 1):
            pc = dk[i-1]["close"]
            ppc = dk[i-2]["close"]
            if pc <= 0 or ppc <= 0:
                continue
            if (pc/ppc - 1) * 100 < 9.8:   # 昨日未涨停
                continue
            o, lo, cl = dk[i]["open"], dk[i]["low"], dk[i]["close"]
            if o <= 0 or (o/pc - 1) * 100 < 5:
                continue
            g_low = (lo/pc - 1) * 100
            in_band = 3 <= g_low <= 8.5
            reseal = (cl/pc - 1) * 100 >= 9.8
            nxt = dk[i+1]
            for x in LIMITS:
                stt = per_limit[x]
                stt["n_sig"] += 1
                stt["n_band" if in_band else "n_deep"] += 1
                stt["n_R" if reseal else "n_U"] += 1
                lim = pc * (1 + x)
                fill_px = None
                for b in dk[i]["bars"]:
                    bo, bl = float(b["open"]), float(b["low"])
                    if bo <= lim:
                        fill_px = bo
                        break
                    if bl <= lim:
                        fill_px = lim
                        break
                if fill_px is None or fill_px <= 0:
                    continue  # 未成交=0（不进 fill 统计，per-signal 期望单独算）
                stt["n_fill"] += 1
                if reseal:
                    stt["fill_in_R"] += 1
                r_open = nxt["open"]/fill_px - 1 - FEE if nxt["open"] > 0 else None
                r_close = nxt["close"]/fill_px - 1 - FEE
                if r_open is not None:
                    stt["fill_open"].append(r_open)
                    if in_band:
                        stt["band_open"].append(r_open)
                stt["fill_close"].append(r_close)
                if in_band:
                    stt["band_close"].append(r_close)
                (stt["fill_R"] if reseal else stt["fill_U"]).append(r_close)

    out = {"meta": {"window": "m60 2024-08-30..2026-09-11", "fee": FEE,
                    "note": "per_signal期望=成交收益×成交率(未成交=0)；60分粒度成交率仍偏高"}}
    for x in LIMITS:
        stt = per_limit[x]
        fill_rate = stt["n_fill"] / stt["n_sig"] if stt["n_sig"] else 0
        r_in_R = stt["fill_in_R"] / stt["n_R"] if stt["n_R"] else 0
        r_in_U = (stt["n_fill"] - stt["fill_in_R"]) / stt["n_U"] if stt["n_U"] else 0
        per_sig_open = [r * fill_rate for r in stt["fill_open"]]  # 近似：E=fill_rate×E|fill
        res = {
            "信号数": stt["n_sig"], "其中浅炸(3~8.5%)": stt["n_band"], "深炸(<3%)": stt["n_deep"],
            "成交率%": round(100*fill_rate, 1),
            "成交率_R组%": round(100*r_in_R, 1), "成交率_U组%": round(100*r_in_U, 1),
            "每成交_T1开盘": S(stt["fill_open"]), "每成交_T1收盘": S(stt["fill_close"]),
            "浅炸子集_T1开盘": S(stt["band_open"]),
            "每成交_T1收盘_R组": S(stt["fill_R"]), "每成交_T1收盘_U组": S(stt["fill_U"]),
            "每信号期望_T1开盘%": round(100*st.mean(per_sig_open), 2) if per_sig_open else None,
        }
        out[f"挂+{int(x*100)}%"] = res
        print(f"== 挂+{int(x*100)}% ==", json.dumps(res, ensure_ascii=False), flush=True)
    (ROOT/"data/zhaban_m60_fill_20260912.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    print("SAVED data/zhaban_m60_fill_20260912.json")


if __name__ == "__main__":
    main()

```
