import json
import statistics as st

data = json.load(open('/opt/data/fenjue/data/futures_basis.json'))
tl = json.load(open('/opt/data/fenjue/data/regime_timeline_hcap.json'))
if isinstance(tl, list):
    panic_days = {d['date'] for d in tl if d.get('regime') == '恐慌期'}
else:
    panic_days = {k for k, v in tl.items() if v == '恐慌期'}
print('恐慌日样本:', len(panic_days))

for key in ['IF', 'IM']:
    rows = [r for r in data[key]['rows'] if r['date'] <= '2026-09-28']
    bps = sorted(r['basis_pct'] for r in rows)
    n = len(rows)
    today_b = data[key]['rows'][-1]['basis_pct']
    rank = sum(1 for b in bps if b < today_b) / n * 100
    print(f"\n== {key}: 9/29 贴水 {today_b:+.2f}%, 全史分位 {rank:.1f}%（0%=史上最深处）")

    def quantile(v):
        return min(4, sum(1 for b in bps if b < v) * 5 // n)

    qs = [[] for _ in range(5)]
    for i, r in enumerate(rows[:-6]):
        fwd = rows[i + 5]['spot'] / r['spot'] - 1
        qs[quantile(r['basis_pct'])].append(fwd)
    for i, bucket in enumerate(qs):
        if bucket:
            wr = sum(1 for x in bucket if x > 0) / len(bucket) * 100
            tag = '最深贴水' if i == 0 else ('最深升水' if i == 4 else '')
            print(f"  Q{i+1}{tag} n={len(bucket)} 未来5日 胜率{wr:.0f}% 均值{st.mean(bucket)*100:+.2f}%")
    p = [r['basis_pct'] for r in rows if r['date'] in panic_days]
    np_ = [r['basis_pct'] for r in rows if r['date'] not in panic_days]
    if p:
        print(f"  恐慌日贴水均值 {st.mean(p):+.2f}% (n={len(p)}) vs 非恐慌 {st.mean(np_):+.2f}% (n={len(np_)})")
