#!/usr/bin/env python3
"""Hermes 侧：跨 Windows 调用 kimi-datasource MCP server 做连通性实测。

协议：stdio MCP，newline-delimited JSON-RPC 2.0。
流程：initialize -> tools/list -> get_data_source_desc(stock_finance_data)
"""
import json
import subprocess
import sys

WIN_SSH = ["ssh", "-o", "BatchMode=yes", "-i", "/opt/data/home/.ssh/windows_ed25519",
           "特比欧炸@192.168.2.11"]
MCP_DIR = r"C:\Users\Tebio Zack\.kimi-code\plugins\managed\kimi-datasource"

REQS = [
    {"jsonrpc": "2.0", "id": 1, "method": "initialize",
     "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                "clientInfo": {"name": "hermes-probe", "version": "1.0"}}},
    {"jsonrpc": "2.0", "method": "notifications/initialized"},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
]

payload = "\n".join(json.dumps(r, ensure_ascii=False) for r in REQS) + "\n"

# 通过 ssh 把 payload 喂给 node MCP server
remote_cmd = f'cd /d "{MCP_DIR}" && node ./bin/kimi-datasource.mjs'
p = subprocess.run(WIN_SSH + [remote_cmd], input=payload.encode("utf-8"),
                   capture_output=True, timeout=180)
out = p.stdout.decode("utf-8", "replace")
err = p.stderr.decode("utf-8", "replace")
print("=== exit", p.returncode)
print("=== STDOUT (first 4000) ===")
print(out[:4000])
print("=== STDERR (first 1500) ===")
print(err[:1500])
