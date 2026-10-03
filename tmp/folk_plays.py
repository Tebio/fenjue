"""三个民间打法实测（2026-09-29，tmp 探索级）：豹子号 / 20日箱体 / 炒年份（生肖名字票）。
统一口径：主板（剔300/688/8/4/920），big_kcache 前复权，信号日收盘已知→次日开盘买，净-0.15%。
"""
import glob
import json
import statistics as st

FEE = 0.0015
idx = {r['date']: r['close'] for r in json.load(open('/opt/data/fenjue/data/index_sh000001.json'))}
names = {s['code']: s['name'] for s in json.load(open('/opt/data/fenjue/data/main_board_codes.json'))['stocks']}

bazi = {'对子尾': [], '88尾': [], '44尾': [], 'base': []}
box = {'下沿': [], '上沿': [], '突破20日新高': [], 'base': []}
# 生肖：年份 -> (生肖字, 预热窗start, 当年end)
zodiac = {'龙': ('2023-10-01', '2024-12-31'), '蛇': ('2024-10-01', '2025-12-31'), '马': ('2025-10-01', '2026-09-28')}
zret = {z: {'basket': {}, 'window': w} for z, w in zodiac.items()}  # code -> (startclose, endclose)

for fp in glob.glob('/opt/data/fenjue/data/big_kcache/*.json'):
    code = fp.split('/')[-1].split('.')[0]
    if code[0] not in '06' or code.startswith(('300', '301', '688')):
        continue
    bars = json.load(open(fp))
    if len(bars) < 25:
        continue
    nm = names.get(code, '')
    for i in range(20, len(bars) - 1):
        b, nb = bars[i], bars[i + 1]
        if b['close'] <= 0 or nb['open'] <= 0:
            continue
        ret = nb['close'] / nb['open'] - 1 - FEE
        bazi['base'].append(ret)
        tail = round(b['close'] * 100) % 100
        if tail % 11 == 0:  # 00/11/22.../99 对子尾
            bazi['对子尾'].append(ret)
        if tail % 10 == 8:
            bazi['88尾'].append(ret)
        if tail % 10 == 4:
            bazi['44尾'].append(ret)
        lo20 = min(x['low'] for x in bars[i - 20:i])
        hi20 = max(x['high'] for x in bars[i - 20:i])
        box['base'].append(ret)
        if b['close'] <= lo20 * 1.02:
            box['下沿'].append(ret)
        if b['close'] >= hi20 * 0.98:
            box['上沿'].append(ret)
        if b['close'] > max(x['close'] for x in bars[i - 20:i]):
            box['突破20日新高'].append(ret)
    # 生肖篮子：预热窗首日开盘买，窗末收盘卖
    for z, (ws, we) in zodiac.items():
        if z in nm:
            in_win = [x for x in bars if ws <= x['date'] <= we]
            if len(in_win) > 5:
                zret[z]['basket'][code] = (in_win[0]['open'], in_win[-1]['close'])

def show(rs, label):
    if not rs:
        print(f"  {label}: n=0"); return
    wr = sum(1 for x in rs if x > 0) / len(rs) * 100
    print(f"  {label}: n={len(rs)} 胜率{wr:.1f}% 均值{st.mean(rs)*100:+.3f}%")

print("== 豹子号（收盘价尾数）→ T+1（次日开盘→收盘, 净）")
for k in ['对子尾', '88尾', '44尾', 'base']:
    show(bazi[k], '全部交易日基线' if k == 'base' else k)

print("\n== 20日箱体 → T+1（次日开盘→收盘, 净）")
for k in ['下沿', '上沿', '突破20日新高', 'base']:
    show(box[k], '全部交易日基线' if k == 'base' else k)

print("\n== 炒年份（生肖名字票，预热窗10/01→次年12/31，等权买入持有）")
for z, d in zret.items():
    b = d['basket']
    if not b:
        print(f"  {z}: 无名字票"); continue
    rets = [e / s - 1 for s, e in b.values() if s > 0]
    ws, we = d['window']
    idates = sorted(d2 for d2 in idx if ws <= d2 <= we)
    iret = idx[idates[-1]] / idx[idates[0]] - 1 if len(idates) > 1 else 0
    wr = sum(1 for x in rets if x > 0) / len(rets) * 100
    print(f"  {z}字辈 n={len(rets)} 窗口{ws}~{we}: 等权{st.mean(rets)*100:+.1f}% 中位{st.median(rets)*100:+.1f}% 胜率{wr:.0f}% vs 上证{iret*100:+.1f}%")
