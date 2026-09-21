"""PEAD S4 深挖：T+20 口径终审（首亏/扭亏/预增50，2026-09-22 夜班）。

T+5 口径六变体七闸全灭已归档。但衰减曲线 T+20 普遍转正，
其中 首亏 +3.22%/57%（位置匹配边际 +2.56pp）最强——「利空出尽反弹」假设。
本脚本以 horizon=20 重跑管线三变体：时间分段/regime/市值/成本/衰减全换 T+20 视野。
过则注册 horizon=[20] 候选主张，不过则 PEAD 全线封档。
"""
import json
import sys
import time

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

VARIANTS = ["PEAD_首亏", "PEAD_扭亏", "PEAD_预增50"]


def main():
    stocks = lp.load_universe()
    regime = lp.load_regime()
    stock_cap, qs = lp.load_cap_quintiles()
    out = {}
    for name in VARIANTS:
        t0 = time.time()
        r = lp.run_pipeline(name, lp.REGISTRY[name], stocks, regime, stock_cap, qs, horizon=20)
        out[name] = r
        fs = r["全样本"]
        print(f"[{name}] T+20 n={fs['n']} {fs['win%']}%/{fs['mean%']:+.2f}% t={fs['t']} "
              f"判决={r['判决']} 边际={r.get('位置匹配边际pp')} DSR={r.get('DSR概率')}", flush=True)
        print(f"  分段: {json.dumps({k: v['mean%'] for k, v in r['时间分段'].items()}, ensure_ascii=False)}", flush=True)
        print(f"  regime: {json.dumps({k: v['mean%'] for k, v in r['regime分段'].items()}, ensure_ascii=False)}", flush=True)
        # 逐年（用衰减曲线口径手动补：重扫事件按年分桶 T+20）
        yearly = {}
        det = lp.REGISTRY[name]
        for code, d in stocks.items():
            n = d["n"]
            for i in range(lp.START, n - 21):
                if lp._epx(d, i) <= 0 or not det(d, i):
                    continue
                y = d["date"][i][:4]
                yearly.setdefault(y, []).append(d["c"][i + 20] / lp._epx(d, i) - 1 - 0.0015)
        ys = {y: f"{sum(1 for x in v if x > 0) / len(v) * 100:.0f}%/{sum(v) / len(v) * 100:+.2f}%(n={len(v)})"
              for y, v in sorted(yearly.items())}
        print(f"  逐年T+20: {ys}", flush=True)
        out[name]["逐年T+20"] = ys
    json.dump(out, open("/opt/data/fenjue/data/pead_s4_t20_20260922.json", "w"),
              ensure_ascii=False, indent=1, default=str)
    print("saved data/pead_s4_t20_20260922.json")


if __name__ == "__main__":
    main()
