import json
import time

import requests

UID = '4108316046438234'
s = requests.Session()
s.headers.update({'User-Agent': 'Mozilla/5.0', 'Referer': f'https://i.eastmoney.com/{UID}'})

all_posts = []
page = 1
while True:
    r = s.get('https://i.eastmoney.com/api/guba/UserArticleListV2',
              params={'uid': UID, 'pagenum': page, 'pagesize': 50}, timeout=15)
    d = r.json()
    items = d.get('result') or []
    if not items:
        break
    all_posts.extend(items)
    total = d.get('count', 0)
    print(f'page {page}: +{len(items)} (累计 {len(all_posts)}/{total})', flush=True)
    if len(all_posts) >= total or len(items) < 50:
        break
    page += 1
    time.sleep(0.6)

json.dump(all_posts, open('/opt/data/fenjue/tmp/yunfeng_posts.json', 'w'), ensure_ascii=False, indent=1)
print('saved', len(all_posts))
# 字段勘察
if all_posts:
    p = all_posts[0]
    print('字段:', [k for k in p.keys() if any(x in k for x in ('title', 'content', 'date', 'time', 'stock', 'bar', 'code'))])
    print('样例:', json.dumps({k: str(v)[:120] for k, v in p.items() if isinstance(v, (str, int)) and k in
                              ('post_title', 'post_content', 'post_date', 'stock_name', 'stock_code', 'bar_name', 'post_click_count')}, ensure_ascii=False))
