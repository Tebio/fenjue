import json, sys
sys.path.insert(0, 'engine')
import law_pipeline as lp

stocks = lp.load_universe()
lp.build_xsection(stocks)

CONFS = {"输家250": lp._loser250, "超跌20": lp._oversold20_60d, "三连阴": lp._three_down,
         "缩量": lambda d, i: lp._volratio(d, i) < 0.8, "TD9买": lp._td9buy,
         "避雷针低": lp._bigupper, "大长腿低": lp._biglower, "剔亏ST": lp._fund_healthy}
BASES = {"跌停低": lp.REGISTRY["跌停接_MA60下"], "缺口低": lp.REGISTRY["组合_缺口低开_低位阳线"],
         "触板低": lp.REGISTRY["组合_触板未封_低位"]}

CASES = {'组合_跌停低_TD9买_输家250': ('跌停低', ['TD9买', '输家250']),
         '组合_跌停低_TD9买_超跌20': ('跌停低', ['TD9买', '超跌20']),
         '组合_缺口低_剔亏ST_超跌20_输家250': ('缺口低', ['剔亏ST', '超跌20', '输家250']),
         '组合_触板低_TD9买_剔亏ST_超跌20': ('触板低', ['TD9买', '剔亏ST', '超跌20'])}
for new, (b, cs) in CASES.items():
    conds = [BASES[b]] + [CONFS[c] for c in cs]
    def detect(d, i, conds=conds):
        return all(c(d, i) for c in conds)
    a = lp._collect_sigs(detect, stocks)
    b2 = lp._collect_sigs(lp.REGISTRY[new], stocks)
    na = {k: set(v) for k, v in a.items()}
    nb = {k: set(v) for k, v in b2.items()}
    same = na == nb
    print(f"{new}: 组合版 {sum(len(v) for v in a.values())} vs REGISTRY版 {sum(len(v) for v in b2.values())}  集合相等={'✓' if same else '✗'}")
