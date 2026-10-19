#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""engine/crash_dip_signal.py — 极端崩盘日抄底信号（生产版 v2）

依据 AGENTS #312（2026-10-19）：
  信号 = 当日跌停（≤-9.8%）且 收盘 ≤ MA60（主板）
  执行 = **次日开盘价买入**，买入后第 5 个交易日收盘卖出，扣 0.2% 成本
  铁律 = **当日信号数 ≥ 50 才出手**。8 年 28 次（年均 3.5 次），19 胜 9 负，
         8 年复利 +250%、年化 +16.9%、最大回撤 -14.8%、单次最差 -11.69%。
         信号数 1~4 只的日子（年均 110 天）每笔 -3.39%，**无条件执行 8 年归零**。

v2 新增（2026-10-19）：
  - 交易日历修正：用全市场日期并集，不再用「某只股票的最后日期」（会被停牌股带偏）
  - 直接输出**可执行委托单**：买入日、卖出日、每只股数（A 股 100 股整数倍）
  - 资金约束：--capital 指定本金（默认 10 万），买不起 100 股的票自动剔除并说明
  - 选股顺序：--pick cheap（价格最低优先，默认）/ deep（跌幅最深）/ random / all
    ※ 实测只买「最便宜的 20 只」反而比买全部更好：28 次复利 +310% vs +250%（单次 +5.62% vs +5.02%），
      低价股跌停后反弹弹性更大。所以资金受限只买便宜的，不是妥协而是更优解。

用法：
  python3 engine/crash_dip_signal.py                    # 最新交易日
  python3 engine/crash_dip_signal.py 2026-08-19 --capital 200000
  python3 engine/crash_dip_signal.py --scan             # 近 40 个信号日的信号数
  python3 engine/crash_dip_signal.py --audit            # 全部 ≥50 触发日的兑现履历
输出：终端摘要 + data/crash_dip_ledger.jsonl（每次运行一行）
"""
import json
import random
import statistics as st
import sys
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
ENTRY_DISCOUNT = 5.0    # 买入低吸幅度：挂「信号日收盘 × (1-5%)」限价，未成交立即市价买（AGENTS #316）


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
        if not d or not d['date'] or bar['date'] <= d['date'][-1]:
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


def trade_calendar(U):
    """全市场交易日并集；停牌不影响集合完整性。"""
    return sorted({d for c, x in U.items() if c[:2] in ('60', '00') for d in x['date']})


def daily_signals(U):
    """→ {date: [(code, pct, dist_ma60, close)]}"""
    sig = {}
    for code, d in U.items():
        if code[:2] not in ('60', '00'):
            continue
        c, ma, n, dt = d['c'], d['ma60'], d['n'], d['date']
        for i in range(61, n):
            if c[i - 1] <= 0 or c[i] <= 0 or not ma[i]:
                continue
            pct = c[i] / c[i - 1] - 1
            if pct <= LIMIT_DOWN and c[i] <= ma[i]:
                sig.setdefault(dt[i], []).append((code, pct, c[i] / ma[i] - 1, c[i]))
    return sig


def realize(U, date, cal):
    """某信号日的实际兑现：次日开盘买 → 第5个交易日收盘卖（日等权）。"""
    if date not in cal:
        return None
    i = cal.index(date)
    if i + 6 >= len(cal):
        return None
    buy, sell = cal[i + 1], cal[i + 6]
    rets = []
    for code, d in U.items():
        if code[:2] not in ('60', '00'):
            continue
        if date not in d['date'] or buy not in d['date'] or sell not in d['date']:
            continue
        j, k, m = d['date'].index(date), d['date'].index(buy), d['date'].index(sell)
        if d['c'][j - 1] <= 0 or d['c'][j] <= 0 or not d['ma60'][j]:
            continue
        if d['c'][j] / d['c'][j - 1] - 1 <= LIMIT_DOWN and d['c'][j] <= d['ma60'][j] and d['o'][k] > 0:
            rets.append(d['c'][m] / d['o'][k] - 1 - COST)
    if not rets:
        return None
    return dict(n=len(rets), mean=st.mean(rets), win=sum(1 for r in rets if r > 0) / len(rets),
                worst=min(rets), best=max(rets))


def realize_subset(U, date, cal, codes):
    """只买指定代码集合的兑现（日等权）。"""
    if date not in cal:
        return None
    i = cal.index(date)
    if i + 6 >= len(cal):
        return None
    buy, sell = cal[i + 1], cal[i + 6]
    rets = []
    for code in codes:
        d = U.get(code)
        if not d or date not in d['date'] or buy not in d['date'] or sell not in d['date']:
            continue
        k, m = d['date'].index(buy), d['date'].index(sell)
        if d['o'][k] > 0:
            rets.append(d['c'][m] / d['o'][k] - 1 - COST)
    return st.mean(rets) if rets else None


def cash_sim(U, cal, sig, trig, hold, cheap_n=20):
    """真实资金池模拟：单一份本金，前一批未到期则无法开新仓（跳过该信号）。
    这是把「每次都能满仓独立建仓」的数学幻觉打掉的检验 —— 连续触发日（2024-02-05/06/07）会撞车。"""
    events = []
    for d in trig:
        if d not in cal:
            continue
        i = cal.index(d)
        if i + 1 + hold >= len(cal):
            continue
        buy, sell = cal[i + 1], cal[i + 1 + hold]
        cs = sorted(sig[d], key=lambda x: x[3])[:cheap_n]
        rets = []
        for code, _, _, _ in cs:
            d2 = U.get(code)
            if not d2 or buy not in d2['date'] or sell not in d2['date']:
                continue
            k, m = d2['date'].index(buy), d2['date'].index(sell)
            if d2['o'][k] > 0:
                rets.append(d2['c'][m] / d2['o'][k] - 1 - COST)
        if rets:
            events.append((buy, sell, st.mean(rets)))
    cash, positions, taken, skipped = 1.0, [], 0, 0
    for buy, sell, r in events:
        free = [p for p in positions if p[1] > buy]
        cash += sum(p[2] for p in positions if p[1] <= buy)
        positions = free
        if cash <= 1e-9:
            skipped += 1
            continue
        positions.append((buy, sell, cash * (1 + r)))
        cash = 0.0
        taken += 1
    eq = cash + sum(p[2] for p in positions)
    return eq, taken, skipped


def main():
    argv = sys.argv[1:]
    scan = '--scan' in argv
    audit = '--audit' in argv
    capital, pick, pos = 100000.0, 'cheap', []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == '--capital' and i + 1 < len(argv):
            capital = float(argv[i + 1]); i += 2; continue
        if a == '--pick' and i + 1 < len(argv):
            pick = argv[i + 1]; i += 2; continue
        if not a.startswith('--'):
            pos.append(a)
        i += 1

    U, added = build_universe()
    cal = trade_calendar(U)
    sig = daily_signals(U)

    if audit:
        trig = sorted(d for d in sig if len(sig[d]) >= THRESHOLD)
        print(f'全部 {len(trig)} 个 ≥{THRESHOLD} 触发日的兑现履历（次日开盘买 → 第5个交易日收盘卖）')
        print(f'{"信号日":<12}{"只数":>6}{"全部买":>10}{"只买最便宜20只":>15}{"胜率":>7}{"最差":>8}')
        eq, eqc, rows = 1.0, 1.0, []
        for d in trig:
            r = realize(U, d, cal)
            if not r:
                continue
            eq *= 1 + r['mean']
            cheap = sorted(sig[d], key=lambda x: x[3])[:20]
            rc = realize_subset(U, d, cal, {c[0] for c in cheap})
            if rc:
                eqc *= 1 + rc
            rows.append(r)
            print(f'{d:<12}{r["n"]:>6}{r["mean"] * 100:>+9.2f}%'
                  f'{(rc * 100 if rc is not None else 0):>+14.2f}%{r["win"] * 100:>6.0f}%'
                  f'{r["worst"] * 100:>+7.1f}%')
        yrs = (datetime.strptime(trig[-1], '%Y-%m-%d') - datetime.strptime(trig[0], '%Y-%m-%d')).days / 365.25
        print(f'\n复利累计 {(eq - 1) * 100:+.0f}%   实际跨度 {yrs:.2f} 年   '
              f'年化 {(eq ** (1 / max(yrs, 0.1)) - 1) * 100:+.1f}%')
        print(f'单次胜率 {sum(1 for r in rows if r["mean"] > 0)}/{len(rows)}')
        print(f'只买最便宜 20 只：复利 {(eqc - 1) * 100:+.0f}%   '
              f'年化 {(eqc ** (1 / max(yrs, 0.1)) - 1) * 100:+.1f}%（可执行口径，优于买全部）')
        big = [r['n'] for r in rows if r['n'] > 500]
        if big:
            print(f'注意：{len(big)} 次触发日信号数超 500 只（最大 {max(big)} 只），'
                  f'「买全部」不可执行，实盘只能买其中一部分')
        print('\n资金约束检验（只买最便宜 20 只，单一份本金；前一批未到期就不能开新仓）：')
        for h in (3, 5, 10, 20):
            eqc2, tk, sk = cash_sim(U, cal, sig, trig, h)
            yrs2 = (datetime.strptime(trig[-1], '%Y-%m-%d') - datetime.strptime(trig[0], '%Y-%m-%d')).days / 365.25
            print(f'  T+{h:<2} 复利 {(eqc2 - 1) * 100:>+8.0f}%   年化 {(eqc2 ** (1 / yrs2) - 1) * 100:>+6.1f}%   '
                  f'执行 {tk} 次 / 因资金占用跳过 {sk} 次')
        print('  ※ 「无约束满仓」的 T+20 +1733% 是幻觉：它假设每次触发都能用全部资金重新开仓，')
        print('    而 2024-02-05/06/07 三天连发时只有一份钱。**以本表的 T+5 全仓为对外口径。**')
        return 0

    if scan:
        print(f'近 40 个有信号的交易日（门槛 {THRESHOLD}）：')
        for dt in sorted(sig)[-40:]:
            n = len(sig[dt])
            flag = '★触发' if n >= THRESHOLD else ('  ' if n >= 10 else '× ')
            print(f'  {dt}  {n:>4} 只 {flag}')
        return 0

    target = pos[0] if pos else cal[-1]
    lst = sig.get(target, [])
    n = len(lst)
    hit = n >= THRESHOLD
    prev = [d for d in sorted(sig) if d < target][-20:]

    print('=' * 72)
    print(f'极端崩盘日抄底信号  {target}')
    print('=' * 72)
    print(f'当日信号数：{n} 只   门槛：{THRESHOLD} 只')
    print(f'判定：{"★ 触发 —— 次日开盘买入" if hit else "不交易"}')
    if not hit:
        if n >= 10:
            print(f'  差 {THRESHOLD - n} 只。10~49 只区间日组合 +0.79%/年化13.9%，但回撤 -62.7%，不划算。')
        else:
            print(f'  信号数 {n} < 10，纯亏区间：历史这类日子每笔 -3.39%。什么都不做。')
    if prev:
        print('\n近 20 个信号日：' + ' '.join(f'{d[5:]}:{len(sig[d])}' for d in prev))

    if lst:
        print(f'\n{"代码":<8}{"跌幅":>8}{"距MA60":>9}{"收盘":>9}')
        for code, pct, dist, close in sorted(lst, key=lambda x: x[1])[:30]:
            print(f'{code:<8}{pct * 100:>+7.2f}%{dist * 100:>+8.1f}%{close:>9.2f}')
        if n > 30:
            print(f'  … 另有 {n - 30} 只（完整名单已写入 ledger）')
    else:
        print('\n当日无符合条件的个股（跌停 且 收盘≤MA60）。')

    if hit:
        ci = cal.index(target) if target in cal else None
        buy = cal[ci + 1] if ci is not None and ci + 1 < len(cal) else '（下个交易日）'
        sell = cal[ci + 6] if ci is not None and ci + 6 < len(cal) else '（买入后第5个交易日）'
        print('\n' + '─' * 72)
        print('委托单')
        print('─' * 72)
        print(f'  买入   {buy} 09:25 前挂限价买单：**信号日收盘价 × {1 - ENTRY_DISCOUNT / 100:.2f}**（下浮 '
              f'{ENTRY_DISCOUNT:.0f}%）')
        print(f'         09:30 开盘后若没成交，立刻改市价单买入（成交价≈开盘价+滑点）')
        print(f'         ※ 实测这个挂法比纯开盘买更好：单笔 +5.64% → +6.50%，年化 +21.3% → +25.1%，')
        print(f'           7 年里 6 年更优（78% 的日子开盘后还有更低点，挂低吸多数能成交）')
        print(f'  卖出   {sell} 14:55 前（买入后第 5 个交易日收盘）')
        print(f'  本金   {capital / 10000:.1f} 万；不加止损、不止盈（实测止盈止损会让这条线转负）')
        cand = list(lst)
        if pick == 'deep':
            cand.sort(key=lambda x: x[1])
        elif pick == 'random':
            random.shuffle(cand)
        else:                       # cheap：价格从低到高（默认，实测更优且天然满足资金约束）
            cand.sort(key=lambda x: x[3])
        # 目标持仓数：最多 20 只（实测「最便宜 20 只」优于买全部），至少 5 只才够分散
        TARGET, MINSHARE = 20, 5
        picks = cand[:TARGET]
        # 单只上限：可用资金 / 目标只数，但不少于该股 100 股所需
        per = capital / max(len(picks), 1)
        held = []
        for c_ in picks:
            need = c_[3] * 100
            if need > per:
                continue
            held.append(c_)
        if not held:
            cheap_need = min(c[3] for c in cand) * 100 * MINSHARE
            print(f'  ⚠ 本金不足：凑不出 {MINSHARE} 只满 100 股的仓位。'
                  f'建议本金 ≥ {cheap_need / 10000:.1f} 万（当天最便宜 5 只各 100 股的钱）。')
        elif len(held) < MINSHARE:
            need = sum(c[3] for c in cand[:MINSHARE]) * 100
            print(f'  ⚠ 只买得起 {len(held)} 只，集中度过高（单票 -10% 就伤组合）。'
                  f'要买齐最便宜的 {MINSHARE} 只各 100 股，本金至少要 {need / 10000:.1f} 万。')
        if held:
            per = capital / len(held)
            print(f'\n  {"代码":<8}{"收盘价":>9}{"股数":>7}{"占用":>10}   (等权 {per:.0f} 元/只，共 {len(held)} 只)')
            for code, pct, dist, close in held:
                sh = int(per / close / 100) * 100
                print(f'  {code:<8}{close:>9.2f}{sh:>7}{sh * close:>10.0f}')
            tot = sum(int(per / c[3] / 100) * 100 * c[3] for c in held)
            print(f'  合计占用 {tot:.0f} 元（{tot / capital * 100:.0f}% 仓位，其余为 100 股取整的找零）')
        if len(cand) > len(held):
            print(f'  未买入 {len(cand) - len(held)} 只：按「价格最低优先」只取前 {TARGET} 只中买得起的，'
                  f'这是实测最优的可执行子集（28 次复利 +310% vs 买全部 +250%）')

    rec = {'ts': datetime.now().isoformat(timespec='seconds'), 'date': target,
           'signal_count': n, 'threshold': THRESHOLD, 'triggered': hit,
           'codes': [c for c, _, _, _ in lst], 'overlay_added': added,
           'capital': capital, 'pick': pick}
    with LEDGER.open('a', encoding='utf-8') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    print(f'\n已记账 → {LEDGER.name}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
