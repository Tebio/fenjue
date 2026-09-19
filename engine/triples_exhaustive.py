#!/usr/bin/env python3
"""engine/triples_exhaustive.py — BACKLOG#7 三条件以上组合穷举（2026-09-19 深夜）。

现状：三条件组合靠消融漏斗非穷举（cross_matrix 只做了底座×单确认层 45 对）。
本模块穷举：3 底座 × C(8 确认层, 2) + C(8 确认层, 3) = 3×(28+56) = 252 格。
  底座（注册表三底座，均已过闸门）：
    跌停低    = 跌停接_MA60下
    缺口低    = 组合_缺口低开_低位阳线
    触板低    = 组合_触板未封_低位
  确认层（存活组件 + 剔亏ST）：输家250 / 超跌20 / 三连阴 / 缩量<0.8 / TD9买入 / 避雷针低 / 大长腿低 / 剔亏ST
两阶段漏斗（与 cross_matrix 同款纪律）：
  stage1 事件研究全 horizon 曲线（T+1/2/3/5/10/20，用户钦定汇报纪律）；
         入围线 = n≥200 且 T+5 均值>0 且优于同底座裸跑均值；
  stage2 入围者逐个过 lp.submit_gate 七闸门（G1-G7，零放宽）。
空集/互斥格全量披露（穷举=包括空格），禁选择性汇报。
用法：.venv/bin/python engine/triples_exhaustive.py [--stage1-only]
输出：data/triples_exhaustive_YYYYMMDD.json
"""
import itertools
import json
import statistics as st
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import law_pipeline as lp

ROOT = Path("/opt/data/fenjue")
FEE = 0.0015
HORIZONS = [1, 2, 3, 5, 10, 20]
MIN_N = 200

BASES = {
    "跌停低": lp.REGISTRY["跌停接_MA60下"],
    "缺口低": lp.REGISTRY["组合_缺口低开_低位阳线"],
    "触板低": lp.REGISTRY["组合_触板未封_低位"],
}
CONFS = {
    "输家250": lp._loser250,
    "超跌20": lp._oversold20_60d,
    "三连阴": lp._three_down,
    "缩量": lambda d, i: lp._volratio(d, i) < 0.8,
    "TD9买": lp._td9buy,
    "避雷针低": lp._bigupper,
    "大长腿低": lp._biglower,
    "剔亏ST": lp._fund_healthy,
}


def collect(stocks):
    """单遍：先判 3 底座，命中才评 8 确认层；事件直接落进所属组合格。"""
    combos = {}  # (base, frozenset(confs)) -> [(code,i)]
    base_events = {b: [] for b in BASES}
    bnames, bdet = list(BASES), [BASES[b] for b in BASES]
    cnames, cdet = list(CONFS), [CONFS[c] for c in CONFS]
    hi = max(lp.HORIZONS) + 1
    for code, d in stocks.items():
        n = d["n"]
        o = d["o"]
        for i in range(lp.START, n - hi):
            if o[i + 1] <= 0:
                continue
            hit_bases = []
            for bi, bd in enumerate(bdet):
                try:
                    if bd(d, i):
                        hit_bases.append(bnames[bi])
                except Exception:
                    pass
            if not hit_bases:
                continue
            hits = set()
            for ci, cd in enumerate(cdet):
                try:
                    if cd(d, i):
                        hits.add(cnames[ci])
                except Exception:
                    pass
            for b in hit_bases:
                base_events[b].append((code, i))
                for k in (2, 3):
                    for cs in itertools.combinations(sorted(hits), k):
                        combos.setdefault((b, cs), []).append((code, i))
    return base_events, combos


def stats(events, stocks):
    """全 horizon 事件研究（净口径，剔次日一字跌停开盘）。"""
    out = {"n": len(events)}
    for h in HORIZONS:
        rs = []
        for code, i in events:
            d = stocks[code]
            ei = i + 1
            if ei + h >= d["n"] or d["o"][ei] <= 0 or d["o"][ei] <= d["c"][i] * 0.905:
                continue
            rs.append(d["c"][ei + h] / d["o"][ei] - 1 - FEE)
        if rs:
            wins = [r for r in rs if r > 0]
            losses = [r for r in rs if r <= 0]
            odds = (st.mean(wins) / abs(st.mean(losses))) if wins and losses else None
            out[f"T+{h}"] = {"胜率%": round(100 * len(wins) / len(rs), 1),
                             "均值%": round(100 * st.mean(rs), 2),
                             "赔率": round(odds, 2) if odds else None, "n": len(rs)}
        else:
            out[f"T+{h}"] = None
    return out


def main():
    stage1_only = "--stage1-only" in sys.argv
    stocks = lp.load_universe()
    print("stocks:", len(stocks), flush=True)
    lp.build_xsection(stocks)

    base_events, combos = collect(stocks)
    print(f"底座事件: { {b: len(v) for b, v in base_events.items()} }", flush=True)
    print(f"非空组合格: {len(combos)} / 理论 252", flush=True)

    base_stats = {b: stats(ev, stocks) for b, ev in base_events.items()}
    cells, survivors = {}, []
    for (b, cs), ev in sorted(combos.items()):
        name = f"穷举_{b}_{'_'.join(cs)}"
        s = stats(ev, stocks)
        t5 = s.get("T+5")
        cells[name] = s
        if (s["n"] >= MIN_N and t5 and t5["均值%"] > 0
                and base_stats[b].get("T+5") and t5["均值%"] > base_stats[b]["T+5"]["均值%"]):
            survivors.append((name, b, cs, s["n"], t5["均值%"]))
    survivors.sort(key=lambda x: -x[4])
    print(f"stage1 入围 {len(survivors)} 个（n≥{MIN_N} 且 T+5>0 且优于底座）", flush=True)
    for nm, b, cs, n, m5 in survivors:
        print(f"  {nm}  n={n}  T+5={m5}%", flush=True)
    # 内存纪律（OOM 被杀两次的教训）：stage2 前释放事件列表，全库容量模拟的 didx 很吃内存
    del combos, base_events
    import gc
    gc.collect()

    result = {"meta": {"date": (datetime.now(timezone.utc) + timedelta(hours=8)).date().isoformat(),
                       "口径": "次日开盘买/剔一字跌停开盘/净0.15%/", "min_n": MIN_N,
                       "底座": list(BASES), "确认层": list(CONFS),
                       "理论格数": 3 * (28 + 56), "非空格": len(cells)},
              "底座基线": base_stats, "格子": cells, "stage2": {}}
    if not stage1_only:
        regime = lp.load_regime()
        stock_cap, qs = lp.load_cap_quintiles()
        # 断点续跑（house 纪律：长批必须 checkpoint——无 checkpoint 版本曾被 OOM 杀掉丢 5 条 submit）
        ckpt_fp = ROOT / f"data/triples_submit_ckpt_{(datetime.now(timezone.utc) + timedelta(hours=8)).strftime('%Y%m%d')}.jsonl"
        done = {}
        if ckpt_fp.exists():
            for line in open(ckpt_fp):
                line = line.strip()
                if line:
                    rec = json.loads(line)
                    done[rec["信号"]] = rec
            print(f"断点恢复：已有 {len(done)} 条 submit 结果", flush=True)
        result["stage2"] = done
        ckpt = open(ckpt_fp, "a")
        for nm, b, cs, n, m5 in survivors:
            if nm in done:
                continue
            conds = [BASES[b]] + [CONFS[c] for c in cs]

            def detect(d, i, conds=conds):
                return all(c(d, i) for c in conds)

            try:
                passed, v = lp.submit_gate(nm, detect, stocks, regime, stock_cap, qs)
            except Exception as e:
                v = {"信号": nm, "判决": f"ERROR {e}"}
                passed = False
            result["stage2"][nm] = v
            ckpt.write(json.dumps(v, ensure_ascii=False) + "\n")
            ckpt.flush()
            print(f"submit {nm}: {'PASS' if passed else 'REJECT'}", flush=True)
        ckpt.close()

    today = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y%m%d")
    fp = ROOT / f"data/triples_exhaustive_{today}.json"
    json.dump(result, open(fp, "w"), ensure_ascii=False, indent=1)
    print("saved", fp, flush=True)


if __name__ == "__main__":
    main()
