import re
import requests

t = requests.get('https://i.eastmoney.com/4108316046438234', headers={'User-Agent': 'Mozilla/5.0'}, timeout=15).text
for m in re.findall(r'<script[^>]+src=["\']([^"\']+)', t):
    print('JS:', m)
for m in re.findall(r'["\'](/api/[^"\']+|https?://[^"\']*(?:api|json|list)[^"\']*)["\']', t):
    print('EP:', m[:140])
print('────── 尾部 ──────')
print(t[-1500:])
