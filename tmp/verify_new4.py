import json, sys
sys.path.insert(0, 'engine')
import law_pipeline as lp

stocks = lp.load_universe()
lp.build_xsection(stocks)
ckpt = {}
for line in open('data/triples_submit_ckpt_20260919.jsonl'):
    rec = json.loads(line)
    ckpt[rec['信号']] = rec

MAP = {'组合_跌停低_TD9买_输家250': '穷举_跌停低_TD9买_输家250',
       '组合_跌停低_TD9买_超跌20': '穷举_跌停低_TD9买_超跌20',
       '组合_缺口低_剔亏ST_超跌20_输家250': '穷举_缺口低_剔亏ST_超跌20_输家250',
       '组合_触板低_TD9买_剔亏ST_超跌20': '穷举_触板低_TD9买_剔亏ST_超跌20'}
for new, old in MAP.items():
    det = lp.REGISTRY[new]
    sigs = lp._collect_sigs(det, stocks)
    n_new = sum(len(v) for v in sigs.values())
    n_old = ckpt[old]['全样本']['n']
    print(f"{new}: REGISTRY事件 {n_new} vs 穷举证据 {n_old}  {'✓' if n_new == n_old else '✗ MISMATCH'}")
