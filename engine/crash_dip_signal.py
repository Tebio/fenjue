#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""engine/crash_dip_signal.py — 极端崩盘日抄底信号（生产版）

依据 AGENTS #312（2026-10-19 复核 regime_switch 矛盾时确立）：
  信号 = 当日跌停（≤-9.8%）且 收盘 ≤ MA60（主板）
  执行 = 次日开盘价买入，T+5 收盘价卖出，扣 0.2% 成本
  铁律 = **当日信号数 ≥ 50 才出手**。8 年只有 28 天达标（年均 3.5 次），
         日组合 +5.02%/日、胜 60%+、8 年累计 +250%、年化 +16.9%、最大回撤 -14.8%。
         当日信号数 1~4 只的日子（年均 110 天）每笔 -3.39%，**无条件执行 8 年归零**。

用法：
  python3 engine/crash_dip_signal.py               # 用最新可用交易日
  python3 engine/crash_dip_signal.py 2026-10-16    # 指定日
  python3 engine/crash_dip_signal.py --scan        # 只打印近 40 日日信号数，不发信号
输出：终端摘要 + data/crash_dip_ledger.jsonl（影子记账，一行一次判定）
"""
import json
import statistics as st
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, '/opt/data/fenjue/engine')
sys.path.insert(0, '/opt/data/python-libs')
import law_pipeline as lp  # noqa: E402

ROOT = Path('/opt/data/fenjue')
OVERLAY = ROOT / 'data/kcache_today_overlay.json'
LEDGER = ROOT / 'data/crash_dip_ledger.jsonl'
COST = 0.002
THRESHOLD = 50          # 触发门槛：当日信号数
LIMIT_DOWN = -0.098     # 跌停判定（主板 10%）
NAMES = ROOT / 'data/stock_names.json'


def load_names():
    if NAMES.exists():
        try:
            return json.loads(NAMES.read_text())
        except Exception:
            pass
    return {}


def build_universe():
    """load_universe + 当日收盘覆盖层（fast_close_update.py 15:10 写入）。"""
    U = lp.load_universe()
    ov = {}
    if OVERLAY.exists():
        try:
            ov = json.loads(OVERLAY.read_text())
        except Exception:
            ov = {}
    added = 0
    for code, bar in ov.items():
        d = U.get(code)
        if not d or not d['date']:
            continue
        if bar['date'] <= d['date'][-1]:
            continue
        d['date'].append(bar['date'])
        d['c'].append(bar['close'])
        d['o'].append(bar['open'])
        d['h'].append(bar['high'])
        d['l'].append(bar['low'])
        d['v'].append(bar['volume'])
        cs = d['c']
        d['ma60'].append(st.mean(cs[-60:]) if len(cs) >= 60 else None)
        d['n'] = len(d['c'])
        added += 1
    return U, added


def daily_counts(U):
    """→ {date: [(code, pct, dist_ma60, close)]}，只含符合信号条件的票。"""
    sig = defaultdict(list)
    for code, d in U.items():
        if code[:2] not in ('60', '00'):
            continue
        c, ma, n, dt = d['c'], d['ma60'], d['n'], d['date']
        for i in range(61, n):
            if c[i - 1] <= 0 or c[i] <= 0 or not ma[i]:
                continue
            pct = c[i] / c[i - 1] - 1
            if pct <= LIMIT_DOWN and c[i] <= ma[i]:
                sig[dt[i]].append((code, pct, c[i] / ma[i] - 1, c[i]))
    return sig


def forward(idx, U, code, target_i):
    """信号日之后第 target_i 个交易日收盘（用于历史兑现核对）。"""
    d = U[code]
    j = idx + target_i
    return d['c'][j] if j < d['n'] else None


def main():
    args = [a for a in sys.argv[1:]]
    scan = '--scan' in args
    args = [a for a in args if not a.startswith('--')]
    U, added = build_universe()
    sig = daily_counts(U)
    dates = sorted(sig.keys())
    if not dates:
        print('无信号数据')
        return 1
    target = args[0] if args else None
    if target is None:
        # 取全市场最新交易日
        target = max((d['date'][-1] for c, d in U.items() if c[:2] in ('60', '00')), default=None)
    if target not in sig:
        # 可能当日确实 0 信号，仍要能报出来
        sig.setdefault(target, [])

    if scan:
        print(f'近 40 个有信号的交易日（门槛 {THRESHOLD}）：')
        for dt in dates[-40:]:
            n = len(sig[dt])
            flag = '★触发' if n >= THRESHOLD else ('  ' if n >= 10 else '× ')
            print(f'  {dt}  {n:>4} 只 {flag}')
        return 0

    lst = sig[target]
    n = len(lst)
    hit = n >= THRESHOLD
    prev = [d for d in dates if d < target][-20:]
    names = load_names()

    print('=' * 68)
    print(f'极端崩盘日抄底信号  {target}')
    print('=' * 68)
    print(f'当日信号数：{n} 只   门槛：{THRESHOLD} 只')
    print(f'判定：{"★ 触发 —— 次日开盘买入" if hit else "不交易"}')
    if not hit:
        if n >= 10:
            print(f'  差 {THRESHOLD - n} 只。10~49 只区间历史上不划算（日组合 +0.79%/年化 13.9% 但回撤 -62.7%）。')
        else:
            print(f'  信号数 {n} < 10，这是纯亏区间：历史上这种日子每笔 -3.39%。什么都不做。')
    if prev:
        print(f'\n近 20 个信号日：' + ' '.join(f'{d[5:]}:{len(sig[d])}' for d in prev))
    if lst:
        print(f'\n{"代码":<8}{"跌幅":>8}{"距MA60":>9}{"收盘":>9}')
        for code, pct, dist, close in sorted(lst, key=lambda x: x[1]):
            print(f'{code:<8}{pct * 100:>+7.2f}%{dist * 100:>+8.1f}%{close:>9.2f}')
    else:
        print('\n当日无符合条件的个股（跌停 且 收盘≤MA60）。')
    if hit:
        print('\n执行（照做，不要改）：')
        print(f'  1) 次日开盘价买入以上全部 {n} 只，等权')
        print('  2) 持有满 5 个交易日，第 5 日收盘卖出')
        print('  3) 不加止损、不止盈（实测止损-8%/止盈+15% 会让四条线全部转负）')
        print('  4) 单票风险：最差 -10%，等权分散后组合回撤历史最大 -14.8%')

    ledger = {
        'ts': datetime.now().isoformat(timespec='seconds'),
        'date': target,
        'signal_count': n,
        'threshold': THRESHOLD,
        'triggered': hit,
        'codes': [c for c, _, _, _ in lst],
        'overlay_added': added,
    }
    with LEDGER.open('a', encoding='utf-8') as f:
        f.write(json.dumps(ledger, ensure_ascii=False) + '\n')
    print(f'\n已记账 → {LEDGER.name}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
