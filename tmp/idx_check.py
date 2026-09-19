import json
tl = json.load(open('data/regime_timeline_hcap.json'))
zeros = sum(1 for r in tl if r.get('idx') == 0)
print(f"idx=0 的天数: {zeros}/{len(tl)}")
# 最后 10 个非零 idx
nz = [r for r in tl if r.get('idx') != 0]
print('最后的非零 idx 条目:', nz[-3:] if nz else '无非零！全部 idx=0')
# idx 字段是什么时候开始恒 0 的
if nz:
    print('最后一个非零 idx 日期:', nz[-1]['date'])
