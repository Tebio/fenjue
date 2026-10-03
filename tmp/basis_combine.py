"""基差结合点探索（2026-09-29，tmp 探索，未注册）。
A. 恐慌期标签日 × IF贴水分位 → 指数未来5/10日收益（土壤确认门候选）
B. 反转族信号日(T-1跌≥3%) × 贴水分位 → T+1(次日开盘→收盘, 净-0.15%)，全史 vs 2026（死策略能否被过滤救活）
C. 贴水分位 5 日急跌 → 指数未来5日（链式风险预警 or 见底）
口径坑：主力连续换月接缝未剔除，结论按探索级对待。
"""
import glob
import json
import statistics as st

FEE = 0.0015
data = json.load(open('/opt/data/fenjue/data/futures_basis.json'))
tl = json.load(open('/opt/data/fenjue/data/regime_timeline_hcap.json'))
panic_days = {d['date'] for d in tl if d.get('regime') == '恐慌期'} if isinstance(tl, list) else set()

rows = data['IF']['rows']
bps_sorted = sorted(r['basis_pct'] for r in rows)
N = len(rows)
def qtile(v, n=N, s=bps_sorted):
    return min(4, sum(1 for b in s if b < v) * 5 // n)
rank_map = {r['date']: sum(1 for b in bps_sorted if b < r['basis_pct']) / N for r in rows}

def fwd(rows, i, k):
    return rows[i + k]['spot'] / rows[i]['spot'] - 1

def show(bucket, label, k):
    if not bucket:
        return f"  {label}: n=0"
    wr = sum(1 for x in bucket if x > 0) / len(bucket) * 100
    return f"  {label}: n={len(bucket)} 胜率{wr:.0f}% 均值{st.mean(bucket)*100:+.2f}%"

# ---- A. 恐慌期 × 贴水分位 → 现货指数(沪深300)未来收益
print("A. 恐慌期标签日 × IF贴水分位 → 沪深300未来5日")
buckets = [[] for _ in range(5)]
for i, r in enumerate(rows[:-11]):
    if r['date'] in panic_days:
        buckets[qtile(r['basis_pct'])].append(fwd(rows, i, 5))
for i, b in enumerate(buckets):
    tag = '最深贴水' if i == 0 else ('最浅/升水' if i == 4 else '')
    print(show(b, f"Q{i+1}{tag}", 5))
np_bucket = [fwd(rows, i, 5) for i, r in enumerate(rows[:-11]) if r['date'] not in panic_days]
print(show(np_bucket, "非恐慌日(基线)", 5))

# ---- B. 反转族 × 贴水分位
print("\nB. 反转族(T-1跌≥3%→次日开盘买→当日尾盘,净) × IF贴水分位")
rev = [[] for _ in range(5)]
rev26 = [[] for _ in range(5)]
cnt = 0
for fp in glob.glob('/opt/data/fenjue/data/big_kcache/*.json'):
    code = fp.split('/')[-1].split('.')[0]
    if code[0] not in '06' or code.startswith(('300', '301', '688')):
        continue
    bars = json.load(open(fp))
    for i in range(1, len(bars) - 1):
        pc, c = bars[i - 1]['close'], bars[i]['close']
        if pc <= 0 or c / pc - 1 > -0.03:
            continue
        nb = bars[i + 1]
        if nb['open'] <= 0:
            continue
        rk = rank_map.get(nb['date'])  # 入场日的贴水分位（当日盘前已知昨收贴水? 用信号日更安全）
        rk_s = rank_map.get(bars[i]['date'])
        if rk_s is None:
            continue
        ret = nb['close'] / nb['open'] - 1 - FEE
        q = min(4, int(rk_s * 5))
        rev[q].append(ret)
        if bars[i]['date'] >= '2026-01-01':
            rev26[q].append(ret)
        cnt += 1
print(f"  信号总数 {cnt}")
for i in range(5):
    tag = '最深贴水' if i == 0 else ('最浅/升水' if i == 4 else '')
    print(show(rev[i], f"全史 Q{i+1}{tag}", 1))
print("  --- 仅2026 ---")
for i in range(5):
    tag = '最深贴水' if i == 0 else ('最浅/升水' if i == 4 else '')
    print(show(rev26[i], f"2026 Q{i+1}{tag}", 1))

# ---- C. 贴水分位5日急跌
print("\nC. IF贴水分位 5 日变化最急降档 → 沪深300未来5日")
deltas = []
for i in range(5, len(rows) - 6):
    d = rank_map[rows[i]['date']] - rank_map[rows[i - 5]['date']]
    deltas.append((d, i))
ds = sorted(d for d, _ in deltas)
lo = ds[len(ds) // 10]
hi = ds[-len(ds) // 10]
crash = [fwd(rows, i, 5) for d, i in deltas if d <= lo]
spike = [fwd(rows, i, 5) for d, i in deltas if d >= hi]
print(show(crash, "贴水5日急降最深10%(对冲盘涌入)", 5))
print(show(spike, "贴水5日急升最猛10%(对冲盘撤离)", 5))
