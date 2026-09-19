import json, sys
sys.path.insert(0, 'engine')
import law_pipeline as lp

stocks = lp.load_universe()
lp.build_xsection(stocks)
regime = lp.load_regime()
stock_cap, qs = lp.load_cap_quintiles()

CONFS = {"输家250": lp._loser250, "超跌20": lp._oversold20_60d, "三连阴": lp._three_down,
         "缩量": lambda d, i: lp._volratio(d, i) < 0.8, "TD9买": lp._td9buy,
         "避雷针低": lp._bigupper, "大长腿低": lp._biglower, "剔亏ST": lp._fund_healthy}
BASES = {"跌停低": lp.REGISTRY["跌停接_MA60下"], "缺口低": lp.REGISTRY["组合_缺口低开_低位阳线"],
         "触板低": lp.REGISTRY["组合_触板未封_低位"]}

cells = json.load(open('data/triples5_exhaustive_20260919.json'))
surv = [(nm, s) for nm, s in cells.items() if s["n"] >= 200 and s.get("T+5") and s["T+5"]["均值%"] > 0]
out = {}
for nm, s in surv:
    parts = nm.split('_')[1:]
    b, cs = parts[0], parts[1:]
    conds = [BASES[b]] + [CONFS[c] for c in cs]
    def detect(d, i, conds=conds):
        return all(c(d, i) for c in conds)
    try:
        passed, v = lp.submit_gate(nm, detect, stocks, regime, stock_cap, qs)
    except Exception as e:
        v = {"信号": nm, "判决": f"ERROR {e}"}
        passed = False
    out[nm] = v
    cap = v.get('容量', {}).get('槽10_K1', {})
    print(f"{nm}: {'PASS' if passed else 'REJECT'} 闸门={v.get('闸门')} K1年化={cap.get('年化%')}", flush=True)
json.dump(out, open('data/triples5_submit_20260919.json', 'w'), ensure_ascii=False, indent=1)
print('saved data/triples5_submit_20260919.json')
