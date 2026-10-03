"""PEAD 高增轴终审（2026-09-29，台账§6观察项补完）：
高送转解剖发现的「净利同比>30%=质量过滤器」能否脱离高送转语境独立成立？
口径：预告高增（预增≥50%/扭亏）→ 公告次日开盘 → T+20/T+60，净-0.15%；
位置匹配对照=同票同 MA60 位置随机非事件日同窗口（防位置beta）；分年验尸。
"""
import glob
import json
import random
import statistics as st

FEE = 0.0015
random.seed(7)
ev = json.load(open('/opt/data/fenjue/data/pead_events.json'))
print('pead 原始', len(ev), '字段样例:', list(ev[0].keys())[:12])
