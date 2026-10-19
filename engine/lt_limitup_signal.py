#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""engine/lt_limitup_signal.py — 低换手打板信号（生产版）

依据 AGENTS #310~#312（2026-10-19）：
  可用档条件 = 换手率 < 4%  且  封单额/流通市值 < 1%  且  首次封板 ≤ 10:00  且  连板数 ≤ 2
  回测（2025-09~2026-10，主板，n=1083）：单笔 +2.10%／胜 66.1%／中位 +1.35%／日均 4.6 只，
  日等权组合 +2.11%/日、日胜率 84.1%，p1 -5.2%、最差 -7.2%。
  执行 = 当日封板价买入，**次日开盘价卖出**（开盘 +2.10% 明显优于收盘 +1.53%）。

为什么是「换手低」而不是「换手高」：
  换手 0-4% × 封单>2% = +6.68%，换手 25%+ × 封单<0.5% = -1.97%。
  低换手=惜售、筹码锁定好；高换手=分歧巨大，次日大概率被砸。
  封单越强次日溢价越高，但封单越强越排不上队 → 所以选「封单 0.5~1% 的弱封单 + 低换手」。

用法：
  python3 engine/lt_limitup_signal.py                  # 今日（盘中实时 / 盘后终值）
  python3 engine/lt_limitup_signal.py 2026-10-16       # 指定日复盘
  python3 engine/lt_limitup_signal.py --strict         # 附带强封单参考档（难成交，仅观察）
输出：终端摘要 + data/lt_limitup_ledger.jsonl
"""
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, '/opt/data/fenjue/engine')
ROOT = Path('/opt/data/fenjue')
LEDGER = ROOT / 'data/lt_limitup_ledger.jsonl'
HS_MAX = 4.0        # 换手率上限 %
FUND_MAX = 1.0      # 封单额/流通市值上限 %
FBT_MAX = '10:00'   # 首次封板时间上限
LB_MAX = 2          # 连板数上限


def fmt_fbt(v):
    if not v:
        return '00:00'
    s = str(int(v)).zfill(6)
    return f'{s[:2]}:{s[2:4]}'


def fetch(date8):
    from limitup_pool_fetch import fetch_pool
    raw = fetch_pool(date8)
    if not raw:
        return []
    out = []
    for x in raw:
        code = x.get('c') or ''
        if code[:2] not in ('60', '00'):      # 只留主板，与回测口径一致
            continue
        ltsz = x.get('ltsz') or 0
        fund = x.get('fund') or 0
        out.append(dict(
            code=code, name=x.get('n') or '', zdp=x.get('zdp') or 0,
            hs=x.get('hs') or 0, lbc=x.get('lbc') or 1, zbc=x.get('zbc') or 0,
            fbt=fmt_fbt(x.get('fbt')), fund_pct=(fund / ltsz * 100) if ltsz else 0,
            ltsz=ltsz / 1e8, amt=(x.get('amount') or 0) / 1e8,
            hybk=x.get('hybk') or '',
        ))
    return out


def main():
    args = [a for a in sys.argv[1:]]
    strict = '--strict' in args
    args = [a for a in args if not a.startswith('--')]
    now = datetime.now()
    date = args[0] if args else now.strftime('%Y-%m-%d')
    date8 = date.replace('-', '')

    pool = fetch(date8)
    if not pool:
        print(f'{date} 涨停池为空或抓取失败（非交易日？）')
        return 1

    ok = [x for x in pool if x['hs'] < HS_MAX and x['fund_pct'] < FUND_MAX
          and x['fbt'] <= FBT_MAX and x['lbc'] <= LB_MAX]
    strong = [x for x in pool if x['hs'] < HS_MAX and x['fund_pct'] >= 2
              and x['fbt'] <= FBT_MAX and x['lbc'] <= LB_MAX and x['zbc'] == 0]

    intraday = (date == now.strftime('%Y-%m-%d') and now.hour < 15)
    print('=' * 78)
    print(f'低换手打板信号  {date}   {"【盘中实时快照，会变】" if intraday else "【收盘终值】"}')
    print('=' * 78)
    print(f'主板涨停 {len(pool)} 只 → 符合可用档 {len(ok)} 只')
    print(f'条件：换手<{HS_MAX}% 且 封单/流通<{FUND_MAX}% 且 首封≤{FBT_MAX} 且 连板≤{LB_MAX}')
    if ok:
        print(f'\n{"代码":<8}{"名称":<10}{"换手":>7}{"封单":>7}{"首封":>7}{"板":>3}{"炸":>3}{"流通亿":>8}  行业')
        for x in sorted(ok, key=lambda y: y['hs']):
            print(f"{x['code']:<8}{x['name'][:8]:<10}{x['hs']:>6.1f}%{x['fund_pct']:>6.2f}%"
                  f"{x['fbt']:>7}{x['lbc']:>3}{x['zbc']:>3}{x['ltsz']:>8.1f}  {x['hybk'][:8]}")
        print('\n执行：当日封板价买入 → 次日开盘价卖出（回测 +2.10%/笔、胜66.1%、中位+1.35%）')
        print('      别贪隔日，别等收盘（开盘 +2.10% vs 收盘 +1.53%）；炸板不回封就当日走，别硬扛')
    else:
        print('\n今日没有符合可用档的票。空手是常态 —— 回测日均只有 4.6 只，且要求换手极低。')
    if strict and strong:
        print(f'\n【参考档·强封单】{len(strong)} 只（历史 +6.68%/笔，但封单这么厚基本排不上队，只能看）')
        for x in sorted(strong, key=lambda y: -y['fund_pct']):
            print(f"  {x['code']} {x['name'][:8]:<9} 换手{x['hs']:>4.1f}% 封单{x['fund_pct']:>6.2f}% 首封{x['fbt']}")

    with LEDGER.open('a', encoding='utf-8') as f:
        f.write(json.dumps({'ts': now.isoformat(timespec='seconds'), 'date': date,
                            'intraday': intraday, 'pool': len(pool),
                            'picked': [x['code'] for x in ok]}, ensure_ascii=False) + '\n')
    print(f'\n已记账 → {LEDGER.name}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
