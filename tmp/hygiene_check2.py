import json, re
tl = json.load(open('data/regime_timeline_hcap.json'))
print('timeline 类型:', type(tl))
if isinstance(tl, dict):
    ks = sorted(tl.keys())
    print('regime 时间轴最新:', ks[-3:], {k: tl[k] for k in ks[-3:]})
elif isinstance(tl, list):
    print('regime 时间轴尾部:', tl[-3:])
for f in ['600519', '000001', '601137']:
    d = json.load(open(f'data/big_kcache/{f}.json'))
    if isinstance(d, list):
        print(f, 'kcache 最新:', d[-1] if not isinstance(d[-1], dict) else d[-1].get('date'))
    else:
        print(f, 'kcache 最新:', d['date'][-1])
src = open('engine/claims_shadow.py').read()
print('shadow 引用:', re.findall(r'claims_registry|REGISTRY|load_claims|yaml', src)[:10])
