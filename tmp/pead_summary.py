import json

d = json.load(open('/opt/data/fenjue/data/pead_s4_20260922.json'))
s = json.load(open('/opt/data/fenjue/data/pead_s4_submit_20260922.json'))
for name, r in d.items():
    dc = r['衰减曲线']
    row = '  '.join(f"{h}:{dc[h]['win%']:.0f}%/{dc[h]['mean%']:+.2f}%" for h in ['T+1', 'T+5', 'T+10', 'T+20'] if h in dc)
    marg = s[name].get('位置匹配边际pp', {})
    rg = r.get('regime分段', {})
    rg_s = ' '.join(f"{k[:2]}{v['mean%']:+.2f}" for k, v in rg.items())
    seg = r.get('时间分段', {})
    seg_s = ' '.join(f"{k[:7]}{v['mean%']:+.2f}" for k, v in seg.items())
    print(f"{name:<16} n={r['全样本']['n']:>5} | {row}")
    print(f"{'':18} 边际T5/T20={marg.get('5')}/{marg.get('20')}pp | regime: {rg_s} | 分段: {seg_s}")
