"""解析云峰全部帖子 → 提（时间，股票，动作意图）事件表。"""
import collections
import json
import re

posts = json.load(open('/opt/data/fenjue/tmp/yunfeng_posts.json'))
print('总帖数', len(posts))

STOCK_TAG = re.compile(r'\$([^$]{1,12})\((?:SH|SZ)?(\d{6})\)\$')
BUY_KW = re.compile(r'买入|上车|开仓|建仓|抄底|低吸|接了|加仓|进了|杀入|搞了|满仓|半仓')
SELL_KW = re.compile(r'卖出|清仓|止盈|止损|走了|跑了|下车|撤了|减仓|出了')
HOLD_KW = re.compile(r'持有|稳住|拿着|捏着|锁仓|躺平|不动')

events = []
for p in posts:
    title = p.get('post_title') or ''
    content = p.get('post_content') or ''
    src_title = p.get('source_post_title') or ''
    src_content = p.get('source_post_content') or ''
    text = f'{title} {content} {src_title} {src_content}'
    ts = p.get('post_publish_time') or p.get('post_display_time') or ''
    tags = STOCK_TAG.findall(text)
    code_name = p.get('code_name') or ''
    # 帖子的股吧归属也是股票线索
    m = re.search(r'(\d{6})', str(p.get('selected_post_code') or ''))
    bar_code = m.group(1) if m else ''
    intent = ('buy' if BUY_KW.search(text) else
              'sell' if SELL_KW.search(text) else
              'hold' if HOLD_KW.search(text) else 'talk')
    events.append({'ts': ts, 'intent': intent, 'tags': [(n, c) for n, c in tags],
                   'bar': bar_code, 'bar_name': code_name,
                   'title': title[:80], 'content': text[:200]})

events.sort(key=lambda e: e['ts'])
json.dump(events, open('/opt/data/fenjue/tmp/yunfeng_events.json', 'w'), ensure_ascii=False, indent=1)

by_intent = collections.Counter(e['intent'] for e in events)
print('意图分布:', dict(by_intent))
with_tag = [e for e in events if e['tags']]
print('带股票签的帖:', len(with_tag))
print('\n═══ 2026-03~07 窗口内带股票签的帖（按时间）═══')
for e in events:
    if e['tags'] and '2026-03' <= e['ts'][:7] <= '2026-07':
        stocks = ' '.join(f'{n}({c})' for n, c in e['tags'])
        print(f"{e['ts'][:16]} [{e['intent']}] {stocks} | {e['title'][:40]}")
