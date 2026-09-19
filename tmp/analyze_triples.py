import json, sys
sys.path.insert(0, 'engine')
d = json.load(open('data/triples_exhaustive_20260919.json'))
s2 = d['stage2']
print('stage2 总数:', len(s2))
rej = [k for k, v in s2.items() if not v.get('判决', '').startswith('PASS')]
print('REJECT:', rej)
passes = {k: v for k, v in s2.items() if v.get('判决', '').startswith('PASS')}
print('PASS:', len(passes))
for base in ['跌停低', '缺口低', '触板低']:
    group = [(k, v) for k, v in passes.items() if k.split('_')[1] == base]
    group.sort(key=lambda x: -(x[1]['容量']['槽10_K1']['年化%'] if x[1].get('容量', {}).get('槽10_K1') else -99))
    print(f'\n== {base} ({len(group)}) 按G7 K1年化排序 ==')
    for k, v in group[:12]:
        cap = v['容量']['槽10_K1']
        t5 = v['衰减曲线'].get('T+5', {})
        print(f"  {k}: K1年化{cap['年化%']} 均笔{cap['均笔%']} 回撤{cap['回撤%']} 笔{cap['笔数']:.0f} | T+5 {t5.get('win%')}%/{t5.get('mean%')} n{t5.get('n')} | 边际{v['位置匹配边际pp']}")
