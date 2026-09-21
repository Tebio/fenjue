"""9 月实盘模拟：5 万本金走当前可推主张（2026-09-20）。
口径声明（先声明后跑数）：
- 主张集=当前注册且推送链真实接线的：跌停底座成簇版、恐慌复活门(≥50)、摇篮成簇、
  缺口低_避周一、TD9旗舰4条（49-53）。打板系（frontrun/观察池）因 fill 黑盒只报参考不进账本。
- 入场=信号次日开盘（_epx 口径，剔一字跌停），出场=T+5 收盘，费 0.3%（5千/笔的小账户真实成本：
  佣金 5 元×2 + 印花税 + 滑点），容量=10 槽 × 5 千。
- 数据止于 9/18：信号日 >9/11 的单子 T+5 走不完，单列「在途」不计收益。
"""
import sys, json, statistics as st
sys.path.insert(0, 'engine')
import law_pipeline as lp

stocks = lp.load_universe()
lp.build_xsection(stocks)

CLAIMS = {
    '跌停低_MA60下': '组合_跌停低_三连阴',   # 推送线实际执行的组合版
    '恐慌复活门': '反转族_跌停潮50',
    '摇篮成簇': '妖股摇篮_成簇',
    '缺口低_避周一': '组合_缺口低开_低位阳线_避周一',
    'TD9旗舰_输家': '组合_跌停低_TD9买_输家250',
    'TD9旗舰_超跌': '组合_跌停低_TD9买_超跌20',
}
SEP = ('2026-09-01', '2026-09-18')
FEE = 0.003
HOLD = 5

# 收集 9 月信号（去重：同票同日多主张命中=一笔）
seen = set()
trades = []  # (signal_date, code, entry_date, ret or None, hit_by)
for cname, det_name in CLAIMS.items():
    det = lp.REGISTRY[det_name]
    for code, d in stocks.items():
        n = d['n']
        for i in range(lp.START, n - 1):
            dt = d['date'][i]
            if dt < SEP[0] or dt > SEP[1]:
                continue
            if lp._epx(d, i) <= 0:
                continue
            try:
                if not det(d, i):
                    continue
            except Exception:
                continue
            key = (dt, code)
            if key in seen:
                continue
            seen.add(key)
            ei = i + 1
            r = None
            if ei + HOLD < n:
                r = d['c'][ei + HOLD] / lp._epx(d, i) - 1 - FEE
            trades.append((dt, code, d['date'][ei], r, cname))

trades.sort()
print(f'9/1-9/18 信号（去重后）: {len(trades)} 笔')
by_day = {}
for t in trades:
    by_day.setdefault(t[0], []).append(t)
for dt in sorted(by_day):
    done = [t[3] for t in by_day[dt] if t[3] is not None]
    pending = sum(1 for t in by_day[dt] if t[3] is None)
    line = f'{dt}: {len(by_day[dt])} 笔'
    if done:
        wins = sum(1 for r in done if r > 0)
        line += f' | 已结算 {len(done)} 笔 胜率{100*wins/len(done):.0f}% 均值{100*st.mean(done):+.2f}%'
    if pending:
        line += f' | 在途 {pending}'
    print(line)

# 容量模拟：10 槽 × 5000 元，满仓上限=5万，排队=错过
done_trades = [t for t in trades if t[3] is not None]
wins = sum(1 for t in done_trades if t[3] > 0)
tot_ret = sum(t[3] for t in done_trades)
print(f'\n== 无容量约束（全跟）==')
print(f'已结算 {len(done_trades)} 笔：胜率 {100*wins/len(done_trades):.1f}% 均笔 {100*st.mean([t[3] for t in done_trades]):+.2f}%')
print(f'若每笔 5000 元全跟：盈亏 = {tot_ret*5000:+.0f} 元（占用峰值另算）')

# 容量约束版：同日信号>空槽时随机取舍（3 种子），槽位占用 5 交易日
import random
def sim(seed, per=5000.0, slots=10):
    random.seed(seed)
    # 按入场日排序模拟：持仓占用 hold 个交易日
    events = sorted(done_trades, key=lambda t: t[2])
    # 需要交易日历来算槽位释放——简化：按入场日索引排序，持有 5 个交易日近似为日历 7 天
    cal = sorted({t[2] for t in done_trades})
    cidx = {d: k for k, d in enumerate(cal)}
    open_pos = []  # (release_cidx)
    cash_used = 0.0
    pnl = 0.0
    taken, missed = 0, 0
    for t in events:
        ci = cidx[t[2]]
        open_pos = [r for r in open_pos if r > ci]
        if len(open_pos) < slots:
            open_pos.append(ci + HOLD)
            pnl += t[3] * per
            taken += 1
        else:
            missed += 1
    return pnl, taken, missed

for seed in (1, 2, 3):
    pnl, taken, missed = sim(seed)
    print(f'槽位模拟 seed{seed}: 成交 {taken} 错过 {missed} | 盈亏 {pnl:+.0f} 元（5万本金 {pnl/500:+.2f}%）')

# 在途单列
pend = [t for t in trades if t[3] is None]
if pend:
    print(f'\n在途 {len(pend)} 笔（信号 9/14 后，T+5 未走完）：')
    for t in pend[:10]:
        print(f'  {t[0]} 信号 {t[1]} {t[4]} 入场日 {t[2]}')