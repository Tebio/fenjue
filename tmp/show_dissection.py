import json

d = json.load(open('/opt/data/fenjue/data/signal_dissection_20260922.json'))
for line in ('T1-MEGA', 'X2'):
    r = d[line]
    print(f"\n═══════ {line}（n={r['n']} 全样本 {r['win']*100:.0f}%/{r['mean']*100:+.2f}%）═══════")
    for dname, cells in r['dims'].items():
        if not cells:
            continue
        top = sorted(cells.items(), key=lambda kv: -kv[1]['mean'])[:3]
        bot = sorted(cells.items(), key=lambda kv: kv[1]['mean'])[:2]
        ts = ' | '.join(f"{k}:{v['win']*100:.0f}%/{v['mean']*100:+.2f}%(n{v['n']},t{v['t']})" for k, v in top)
        bs = ' | '.join(f"{k}:{v['mean']*100:+.2f}%" for k, v in bot)
        print(f"  {dname:<8} 强: {ts}  ‖ 弱: {bs}")
