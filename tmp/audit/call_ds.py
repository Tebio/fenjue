#!/usr/bin/env python3
"""调 DeepSeek 付费 API 跑红队审计（2026-09-19）。"""
import json
import os
import urllib.request

key = None
for line in open("/opt/data/.env"):
    if line.startswith("DEEPSEEK_API_KEY="):
        key = line.split("=", 1)[1].strip()
assert key

pack = open("/opt/data/fenjue/tmp/audit/redteam_pack.md").read()

payload = {
    "model": "deepseek-chat",
    "messages": [
        {"role": "system", "content": "你是顶级量化代码审计员/红队。任务是专门找茬：逻辑 bug、未来函数（lookahead）、口径不一致、统计错误、脏数据、边界条件崩溃。逐条输出：文件:位置 → 问题 → 为什么是问题 → 修法。按严重度排序（致命/严重/轻微/存疑）。不确定的标[存疑]。只报告有依据的问题，不凑数。中文回答。"},
        {"role": "user", "content": pack},
    ],
    "temperature": 0.0,
    "max_tokens": 8000,
}
req = urllib.request.Request(
    "https://api.deepseek.com/chat/completions",
    data=json.dumps(payload).encode(),
    headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
)
with urllib.request.urlopen(req, timeout=600) as r:
    resp = json.loads(r.read())
out = resp["choices"][0]["message"]["content"]
open("/opt/data/fenjue/tmp/audit/redteam_report.md", "w").write(out)
print("tokens:", resp.get("usage"))
print(out[:3000])
