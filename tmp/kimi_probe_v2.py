#!/usr/bin/env python3
"""Kimi 数据源连通性实测 v2：SSH 短连接 + Windows 端落盘读回。

v1 失败教训：单次 SSH 里喂多轮 JSON-RPC 并等待长响应会被 SSH 会话/管道缓冲吞掉。
改成：把 payload 写成 Windows 本地文件 -> node 读文件跑 -> 结果写文件 -> scp 读回。
"""
import json
import subprocess
import sys

SSH = ["ssh", "-o", "BatchMode=yes", "-i", "/opt/data/home/.ssh/windows_ed25519",
       "特比欧炸@192.168.2.11"]
WIN = r"C:\Users\Tebio Zack"
MCP_DIR = WIN + r"\.kimi-code\plugins\managed\kimi-datasource"
TMP = WIN + r"\AppData\Local\Temp\kimi_probe"

REQS = [
    {"jsonrpc": "2.0", "id": 1, "method": "initialize",
     "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                "clientInfo": {"name": "hermes", "version": "1.0"}}},
    {"jsonrpc": "2.0", "method": "notifications/initialized"},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
     "params": {"name": "get_data_source_desc", "arguments": {"name": "stock_finance_data"}}},
]
payload = "\n".join(json.dumps(r, ensure_ascii=False) for r in REQS) + "\n"

# 1) 把 payload 送过去
p1 = subprocess.run(SSH + [
    f'mkdir "{TMP}" 2>nul & powershell -NoProfile -Command "[Console]::In.ReadToEnd() | Set-Content -Encoding UTF8 \'{TMP}\\req.jsonl\'"'
], input=payload.encode("utf-8"), capture_output=True, timeout=120)
print("step1 rc", p1.returncode, p1.stderr.decode("utf-8", "replace")[:300])

# 2) 远端跑 MCP，结果落盘
cmd2 = (f'cd /d "{MCP_DIR}" && node ./bin/kimi-datasource.mjs < "{TMP}\\req.jsonl" > "{TMP}\\resp.jsonl" 2> "{TMP}\\err.txt"')
p2 = subprocess.run(SSH + [cmd2], capture_output=True, timeout=600)
print("step2 rc", p2.returncode)

# 3) 读回结果大小 + 内容
cmd3 = (f'chcp 65001 >nul & powershell -NoProfile -Command "'
        f'$f=\'{TMP}\\resp.jsonl\'; if(Test-Path $f){{ (Get-Item $f).Length }} else {{ \'NOFILE\' }}"')
p3 = subprocess.run(SSH + [cmd3], capture_output=True, timeout=120)
size = p3.stdout.decode("utf-8", "replace").strip()
print("resp size:", size)

cmd4 = (f'powershell -NoProfile -Command "Get-Content \'{TMP}\\resp.jsonl\' -Raw | '
        f'Select-Object -First 1 | ForEach-Object {{ $_.Substring(0,[Math]::Min(4000,$_.Length)) }}"')
p4 = subprocess.run(SSH + [cmd4], capture_output=True, timeout=180)
print("=== RESP (first 4000) ===")
print(p4.stdout.decode("utf-8", "replace")[:4200])

cmd5 = f'powershell -NoProfile -Command "if(Test-Path \'{TMP}\\err.txt\'){{Get-Content \'{TMP}\\err.txt\' -Raw}}"'
p5 = subprocess.run(SSH + [cmd5], capture_output=True, timeout=120)
e = p5.stdout.decode("utf-8", "replace")[:800]
if e.strip():
    print("=== ERR ===", e)
