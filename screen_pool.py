#!/usr/bin/env python3
"""从池文件出发，不用网络，筛多个候选策略。"""
import glob
import json
import sys
from pathlib import Path

for root in (
    Path(__file__).resolve().parents[1],
    Path("/opt/data/skills/fenjue-screening"),
):
    if (root / "fenjue" / "pool.py").exists():
        sys.path.insert(0, str(root))
        break

from fenjue.pool import PoolExpiredError, validate_pool_date

pool_file = sorted(glob.glob('/opt/data/fenjue/pool_*.json'))[-1]
try:
    pool_status = validate_pool_date(pool_file)
except PoolExpiredError as exc:
    raise SystemExit(f"拒绝运行：{exc}") from exc
if pool_status["level"] == "warning":
    print(
        "⚠️ 股票池已超过1个交易日，结果仅供观察："
        f"{pool_status['trading_days_old']}T"
    )
with open(pool_file) as f:
    pool = json.load(f)['results']

print(f'池文件: {pool_file.split("/")[-1]}')
print(f'池内: {len(pool)}只')
print()

# ========================================
# 策略1: 快金叉 — MA5接近MA20但未上穿
# ========================================
print('='*65)
print('📐 策略1: 快金叉 (MA5/MA20差 -8%→+3% + 成交>1亿)')
print('='*65)
golden = []
for s in pool:
    ma5 = s.get('ma5')
    ma20 = s.get('ma20')
    if not ma5 or not ma20:
        continue
    gap = (ma5 - ma20) / ma20 * 100
    amt = s.get('amount_yi', 0) or 0
    if -8 <= gap <= 3 and amt > 1:
        golden.append({**s, 'ma_gap': round(gap, 1)})
golden.sort(key=lambda x: abs(x['ma_gap']))

print(f'候选: {len(golden)}只')
for s in golden[:12]:
    pct = s.get('pct', 0) or 0
    sig = s.get('line_signal', '')
    pe = s.get('pe')
    pe_str = f'PE={pe:.0f}' if pe else 'PE=--'
    print(f'  {s["code"]} {s["name"]:<8} {pe_str:<7} MA差{s["ma_gap"]:+5.1f}% 涨{pct:+5.1f}% 成交{s.get("amount_yi",0):.0f}亿 {s.get("sector","")[:8]} [{sig}]')

# ========================================
# 策略2: 底部潜伏 — 昨涨<5% + 成交3-15亿 + 非热门板块
# ========================================
print()
print('='*65)
print('🥷 策略2: 底部潜伏 (昨涨<5% + 成交3-15亿 + 非主线)')
print('='*65)
hot = ['半导体','消费电子','元件','光学光电','通信设备','电力','煤炭','军工电子','其他电源','电池']
low = []
for s in pool:
    pct = s.get('pct', 0) or 0
    amt = s.get('amount_yi', 0) or 0
    sec = s.get('sector', '') or ''
    if pct < 5 and 3 <= amt <= 15 and not any(h in sec for h in hot):
        low.append(s)
low.sort(key=lambda x: x.get('amount_yi', 0) or 0, reverse=True)

print(f'候选: {len(low)}只')
for s in low[:10]:
    pct = s.get('pct', 0) or 0
    amt = s.get('amount_yi', 0) or 0
    pe = s.get('pe')
    pe_str = f'PE={pe:.0f}' if pe else 'PE=--'
    print(f'  {s["code"]} {s["name"]:<8} {pe_str:<7} 涨{pct:+5.1f}% 成交{amt:.0f}亿 {s.get("sector","")}')

# ========================================
# 策略3: 低位金叉+量 — 快金叉 + 涨幅<3% + 成交>3亿
# ========================================
print()
print('='*65)
print('🎯 策略3: 低位金叉 + 量 (MA差-8→+3% + 涨<3% + 成交>3亿)')
print('='*65)
low_golden = []
for s in pool:
    ma5 = s.get('ma5')
    ma20 = s.get('ma20')
    if not ma5 or not ma20:
        continue
    gap = (ma5 - ma20) / ma20 * 100
    pct = s.get('pct', 0) or 0
    amt = s.get('amount_yi', 0) or 0
    if -8 <= gap <= 3 and -3 <= pct <= 3 and amt > 3:
        low_golden.append({**s, 'ma_gap': round(gap, 1)})
low_golden.sort(key=lambda x: x.get('amount_yi', 0) or 0, reverse=True)

print(f'候选: {len(low_golden)}只')
for s in low_golden[:10]:
    pct = s.get('pct', 0) or 0
    amt = s.get('amount_yi', 0) or 0
    pe = s.get('pe')
    pe_str = f'PE={pe:.0f}' if pe else 'PE=--'
    print(f'  {s["code"]} {s["name"]:<8} {pe_str:<7} MA差{s["ma_gap"]:+5.1f}% 涨{pct:+5.1f}% 成交{amt:.0f}亿 {s.get("sector","")}')
