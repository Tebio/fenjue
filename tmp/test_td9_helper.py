import sys, json
sys.path.insert(0, '/opt/data/scripts')
import importlib.util
spec = importlib.util.spec_from_file_location('rd', '/opt/data/scripts/reversal_daily.py')
rd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rd)

kc = json.load(open('/opt/data/fenjue/data/big_kcache/002163.json'))
last_close = kc[-1]['close']
last_high = kc[-1]['high']
print('002163 最后k线:', kc[-1]['date'], '收', last_close)
print('td9_buy:', rd.td9_buy('002163', last_close))
print('oversold20:', rd.oversold20('002163', last_close, last_high))
print('ma60_above:', rd.ma60_above('002163', last_close))
# 对照 law_pipeline 的 _td9buy/_oversold20_60d 在 (d, i=last) 上的值
sys.path.insert(0, '/opt/data/fenjue/engine')
import law_pipeline as lp
d = {'c': [k['close'] for k in kc], 'o': [k['open'] for k in kc],
     'h': [k['high'] for k in kc], 'l': [k['low'] for k in kc], 'n': len(kc),
     'date': [k['date'] for k in kc]}
i = len(kc) - 1
print('对照 _td9buy:', lp._td9buy(d, i))
print('对照 _oversold20_60d:', lp._oversold20_60d(d, i))
