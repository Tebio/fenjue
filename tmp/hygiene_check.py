import json, re
tl = json.load(open('data/regime_timeline_hcap.json'))
last = sorted(tl)[-3:] if isinstance(tl, dict) else None
print('regime 时间轴最新:', last)
for f in ['600519', '000001', '601137']:
    d = json.load(open(f'data/big_kcache/{f}.json'))
    print(f, 'kcache 最新:', d['date'][-1])
src = open('engine/claims_shadow.py').read()
m = re.findall(r'claims_registry|REGISTRY|load_claims|yaml', src)[:10]
print('shadow 引用:', m)
# 影子桥是否动态枚举注册表主张
m2 = re.findall(r'def (\w+)', src)
print('shadow 函数:', m2[:15])
