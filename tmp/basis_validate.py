"""基差信号清洗+细分验证（2026-09-29，tmp 探索级，未注册）。

清洗项（用户令：未来函数+脏数据）：
  F1 未来函数：分位由「全史」改「滚动250交易日」（历史日不再用未来数据）
  F2 脏数据：换月接缝——CFFEX 交割日=每月第三个周五，剔除交割周±3交易日；
     另剔 |Δbasis_pct| 超 P99 的离群跳变日（连续合约机械跳价）
信号：当日 IF 贴水滚动分位 <10%（深贴水）→ 沪深300 未来 5/10/20 日
口径：指数级，无个股成交问题；费≈0（指数不可交易，仅当环境读数）
验证件：随机对照（全样本日均）/早晚分段/分年验尸/regime分段/剂量反应
"""
import json
import statistics as st

rows = json.load(open('/opt/data/fenjue/data/futures_basis.json'))['IF']['rows']
tl = json.load(open('/opt/data/fenjue/data/regime_timeline_hcap.json'))
panic = {d['date'] for d in tl if d.get('regime') == '恐慌期'} if isinstance(tl, list) else set()

def third_friday(y, m):
    import datetime as dt
    d = dt.date(y, m, 15)
    return d + dt.timedelta(days=(4 - d.weekday()) % 7)

import datetime as dt
expiry = set()
for r in rows:
    y, m, _ = map(int, r['date'].split('-'))
    tf = third_friday(y, m)
    expiry.add(tf.isoformat())

# 标脏：交割周±3个交易日 + |Δbp| 离群
dates = [r['date'] for r in rows]
exp_idx = set()
for i, r in enumerate(rows):
    for k in range(-3, 4):
        j = i + k
        if 0 <= j < len(rows) and rows[j]['date'] in expiry:
            exp_idx.add(i)
            break
dbp = [abs(rows[i]['basis_pct'] - rows[i - 1]['basis_pct']) for i in range(1, len(rows))]
p99 = sorted(dbp)[int(len(dbp) * 0.99)]
out_idx = {i for i in range(1, len(rows)) if abs(rows[i]['basis_pct'] - rows[i - 1]['basis_pct']) > p99}
dirty = exp_idx | out_idx
print(f"总天数 {len(rows)}，交割周±3 剔除 {len(exp_idx)}，Δbp 离群(P99={p99:.2f}) 剔除 {len(out_idx)}，合计脏日 {len(dirty)}")

# 滚动250日分位（无未来函数）
clean = []
for i, r in enumerate(rows):
    lo = max(0, i - 250)
    win = [rows[j]['basis_pct'] for j in range(lo, i)]
    if len(win) < 120:  # 窗口不足半年不评级
        continue
    rk = sum(1 for b in win if b < r['basis_pct']) / len(win)
    clean.append({'i': i, 'date': r['date'], 'rank250': rk, 'bp': r['basis_pct'], 'dirty': i in dirty})
print(f"可评级天数 {len(clean)}（前250日窗口期不评级）")

def fwd(i, k):
    return rows[i + k]['spot'] / rows[i]['spot'] - 1

def show(bucket, label, k):
    if not bucket:
        print(f"  {label}: n=0"); return
    wr = sum(1 for x in bucket if x > 0) / len(bucket) * 100
    med = st.median(bucket) * 100
    print(f"  {label}: n={len(bucket)} 胜率{wr:.0f}% 均值{st.mean(bucket)*100:+.2f}% 中位{med:+.2f}%")

K = 5
ok = [c for c in clean if not c['dirty'] and c['i'] + K + 1 < len(rows)]
sig = [c for c in ok if c['rank250'] < 0.10]
base = ok
print(f"\n== 深贴水(滚动250日分位<10%, 已剔脏) → 沪深300未来{K}日")
show([fwd(c['i'], K) for c in sig], "深贴水信号", K)
show([fwd(c['i'], K) for c in base], "全部交易日基线", K)

print("\n== 剂量反应（滚动分位分档）")
for lo, hi, tag in [(0, .05, '<5%极深'), (.05, .10, '5-10%'), (.10, .20, '10-20%'),
                    (.20, .50, '20-50%'), (.50, .80, '50-80%'), (.80, 1.01, '>80%升水侧')]:
    b = [fwd(c['i'], K) for c in ok if lo <= c['rank250'] < hi]
    show(b, tag, K)

print("\n== 分年验尸（信号均值 vs 当年全日均值）")
years = {}
for c in ok:
    years.setdefault(c['date'][:4], {'sig': [], 'base': []})
    years[c['date'][:4]]['base'].append(fwd(c['i'], K))
    if c['rank250'] < 0.10:
        years[c['date'][:4]]['sig'].append(fwd(c['i'], K))
for y in sorted(years):
    v = years[y]
    if v['sig']:
        wr = sum(1 for x in v['sig'] if x > 0) / len(v['sig']) * 100
        print(f"  {y}: 信号 n={len(v['sig'])} 胜率{wr:.0f}% 均值{st.mean(v['sig'])*100:+.2f}% vs 基线{st.mean(v['base'])*100:+.2f}%")
    else:
        print(f"  {y}: 信号 n=0")

print("\n== 早晚分段")
mid = len(ok) // 2
for seg, name in [(ok[:mid], '前半'), (ok[mid:], '后半')]:
    s = [fwd(c['i'], K) for c in seg if c['rank250'] < 0.10]
    b = [fwd(c['i'], K) for c in seg]
    if s:
        wr = sum(1 for x in s if x > 0) / len(s) * 100
        print(f"  {name}: 信号 n={len(s)} 胜率{wr:.0f}% 均值{st.mean(s)*100:+.2f}% vs 基线{st.mean(b)*100:+.2f}%")

print("\n== 10/20日持有窗")
for kk in (10, 20):
    okk = [c for c in clean if not c['dirty'] and c['i'] + kk + 1 < len(rows)]
    s = [fwd(c['i'], kk) for c in okk if c['rank250'] < 0.10]
    b = [fwd(c['i'], kk) for c in okk]
    wr = sum(1 for x in s if x > 0) / len(s) * 100
    print(f"  T+{kk}: 信号 n={len(s)} 胜率{wr:.0f}% 均值{st.mean(s)*100:+.2f}% vs 基线{st.mean(b)*100:+.2f}%")

print("\n== 与恐慌标签交叉（信号日是否恐慌期）")
ps = [c for c in sig if c['date'] in panic]
nps = [c for c in sig if c['date'] not in panic]
show([fwd(c['i'], K) for c in ps], "深贴水×恐慌期", K)
show([fwd(c['i'], K) for c in nps], "深贴水×非恐慌", K)
