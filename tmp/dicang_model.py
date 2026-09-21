"""留底仓项目实测：5 只股息锚 2025-01 建仓 → 2026-09-18。
Part1 留底仓算术：2025/1/2 以 5 万买入，持有至今，卖多少股成本归 0/归目标；零成本底仓的股息率。
Part2 网格做T增强（合法T+0库存股模型）：
  每日检查（用 OHLC）：
   反T：盘中高 ≥ 昨收×1.015 且收盘 < 高点的卖出价 → 卖出10%底仓@昨收×1.015，收盘前买回
        成交判定：high ≥ trigger 即视为触价成交（保守：要求 close < trigger 才算赚到）
   正T：盘中低 ≤ 昨收×0.985 且 close > low的买入价 → 买10%@昨收×0.985，卖等量旧股@close
        成交判定：low ≤ trigger 且 close > trigger
  每次T毛利=1.5%×T金额，费=0.1%（双边佣金+印花税，5000/笔已含最低佣金影响）
  底价触发间距 1.5%（银行股日常波动量级）
诚实标签：OHLC 看不到日内路径，双向触价同日出iaxian时按只成一笔计；限价单不一定成交。
"""
import json

anchors = [('601838', '成都银行', 0.052), ('600919', '江苏银行', 0.048), ('601229', '上海银行', 0.055),
           ('601077', '渝农商行', 0.050), ('000333', '美的集团', 0.045)]
CAP = 50000.0
T_FRac = 0.10      # 每次T用底仓的10%
STEP = 0.015       # 触发间距1.5%
FEE_T = 0.001      # T单笔费用（双边佣金+印花税，占T金额比）

print('========== Part1 留底仓算术（2025-01-02 建仓 5 万 → 2026-09-18）==========')
print(f'{"标的":<8}{"成本价":>8}{"现价":>8}{"涨幅":>8}{"卖出比例→成本0":>14}{"剩股数(每5万)":>12}{"零成本仓年股息":>12}')
for code, nm, dy in anchors:
    ks = json.load(open(f'/opt/data/fenjue/data/big_kcache/{code}.json'))
    b = next(k for k in ks if k['date'] >= '2025-01-02')
    last = ks[-1]
    c0, p = b['close'], last['close']
    n0 = CAP / c0
    sell_frac = c0 / p                    # 卖到成本0：卖出 成本/现价 比例
    n_left = n0 * (1 - sell_frac)
    freed = CAP - n_left * 0              # 抽回=卖出金额=n0*sell_frac*p = CAP（全部本金）
    div_year = n_left * p * dy            # 零成本仓每年股息（按现价×股息率）
    print(f'{nm:<8}{c0:>8.2f}{p:>8.2f}{100*(p/c0-1):>+7.1f}%{100*sell_frac:>13.1f}%{n_left:>11.0f}股{div_year:>11.0f}元')
print('注：卖出比例=成本/现价；卖出后抽回全部本金 5 万，剩余=纯利润仓，年股息=白捡')

print('\n========== Part2 底仓网格做T增强（2025-01-02 → 2026-09-18，底仓5万）==========')
print(f'{"标的":<8}{"T成功次数":>10}{"T失败/磨损":>10}{"年均成功":>8}{"T净增强":>10}{"折合年化":>8}{"底仓年涨幅":>10}{"合计年化":>8}')
for code, nm, dy in anchors:
    ks = json.load(open(f'/opt/data/fenjue/data/big_kcache/{code}.json'))
    seg = [k for k in ks if k['date'] >= '2025-01-02']
    wins, losses = 0, 0
    t_pnl = 0.0
    for j in range(1, len(seg)):
        pc = seg[j - 1]['close']
        o, h, l, c = seg[j]['open'], seg[j]['high'], seg[j]['low'], seg[j]['close']
        amt = CAP * T_FRac
        did = False
        # 反T：先卖后买（高触 +1.5%，收盘更低买回）
        trig_sell = pc * (1 + STEP)
        if h >= trig_sell and c < trig_sell:
            gross = (trig_sell - c) / trig_sell
            t_pnl += amt * (gross - FEE_T)
            wins += 1 if gross > FEE_T else 0
            losses += 0 if gross > FEE_T else 1
            did = True
        # 正T：先买后卖（低触 -1.5%，收盘更高卖出旧股）
        if not did:
            trig_buy = pc * (1 - STEP)
            if l <= trig_buy and c > trig_buy:
                gross = (c - trig_buy) / trig_buy
                t_pnl += amt * (gross - FEE_T)
                if gross > FEE_T:
                    wins += 1
                else:
                    losses += 1
    years = len(seg) / 244
    t_ann = t_pnl / years
    r_hold = seg[-1]['close'] / seg[0]['close'] - 1
    hold_ann = (1 + r_hold) ** (1 / years) - 1
    print(f'{nm:<8}{wins:>10}{losses:>10}{wins/years:>8.0f}{t_pnl:>9.0f}元{100*t_ann/CAP:>7.1f}%{100*hold_ann:>9.1f}%{100*(hold_ann+t_ann/CAP):>7.1f}%')