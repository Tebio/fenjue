"""PEAD S4 冲刺主跑（2026-09-22 夜班）：业绩预告漂移，六变体全管线+submit 闸门。

数据：data/pead_events.json（东财 RPT_PUBLIC_OP_PREDICT，39451 条，2019 至今）。
探测器已注册 REGISTRY（PEAD_*，事件日=NOTICE_DATE 后首个交易日，入场次日开盘，净-0.15%）。
输出：data/pead_s4_20260922.json（每变体 run_pipeline 全量 + submit 判决）。
"""
import json
import sys
import time

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

VARIANTS = ["PEAD_预增", "PEAD_预增50", "PEAD_扭亏", "PEAD_首亏", "PEAD_预增50_低位", "PEAD_预增50_高位"]


def main():
    stocks = lp.load_universe()
    regime = lp.load_regime()
    stock_cap, qs = lp.load_cap_quintiles()
    print(f"universe={len(stocks)}", flush=True)

    out = {}
    for name in VARIANTS:
        t0 = time.time()
        det = lp.REGISTRY[name]
        r = lp.run_pipeline(name, det, stocks, regime, stock_cap, qs)
        out[name] = r
        fs = r.get("全样本", {})
        print(f"[{name}] n={fs.get('n')} 胜率{fs.get('胜率')} 均值{fs.get('均值%')} "
              f"({time.time() - t0:.0f}s)", flush=True)

    json.dump(out, open("/opt/data/fenjue/data/pead_s4_20260922.json", "w"),
              ensure_ascii=False, indent=1, default=str)
    print("saved data/pead_s4_20260922.json", flush=True)

    # submit 闸门（六闸+G7）
    subs = {}
    for name in VARIANTS:
        try:
            passed, verdict = lp.submit_gate(name, lp.REGISTRY[name], stocks, regime, stock_cap, qs)
            subs[name] = {"passed": passed, **verdict}
            print(f"SUBMIT {name}: {'PASS' if passed else 'REJECT'}", flush=True)
        except Exception as e:
            subs[name] = {"passed": False, "error": str(e)}
            print(f"SUBMIT {name}: ERROR {e}", flush=True)
    json.dump(subs, open("/opt/data/fenjue/data/pead_s4_submit_20260922.json", "w"),
              ensure_ascii=False, indent=1, default=str)
    print("saved data/pead_s4_submit_20260922.json")


if __name__ == "__main__":
    main()
