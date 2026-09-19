#!/usr/bin/env python3
"""端到端实测：跨 Windows 调 kimi-datasource 取真实 A股数据。

拿 stock_finance_data 的 desc，解析出可用 api_name，实际调一次。
"""
import json
import subprocess
import sys

WIN_SSH = ["ssh", "-o", "BatchMode=yes", "-i", "/opt/data/home/.ssh/windows_ed25519",
           "特比欧炸@192.168.2.11"]
MCP_DIR = r"C:\Users\Tebio Zack\.kimi-code\plugins\managed\kimi-datasource"


def mcp_call(calls, timeout=600):
    reqs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                        "clientInfo": {"name": "hermes", "version": "1.0"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"}]
    for i, (name, args) in enumerate(calls, start=10):
        reqs.append({"jsonrpc": "2.0", "id": i, "method": "tools/call",
                     "params": {"name": name, "arguments": args}})
    payload = "\n".join(json.dumps(r, ensure_ascii=False) for r in reqs) + "\n"
    p = subprocess.run(WIN_SSH + [f'cd /d "{MCP_DIR}" && node ./bin/kimi-datasource.mjs'],
                       input=payload.encode("utf-8"), capture_output=True, timeout=timeout)
    out = {}
    for line in p.stdout.decode("utf-8", "replace").splitlines():
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if obj.get("id") and obj.get("id") >= 10:
            out[obj["id"]] = obj
    return out, p.stderr.decode("utf-8", "replace")


if __name__ == "__main__":
    res, err = mcp_call([("get_data_source_desc", {"name": "stock_finance_data"})])
    for k, v in res.items():
        txt = json.dumps(v, ensure_ascii=False)
        print(f"--- id {k} len {len(txt)}")
        print(txt[:5000])
    if err.strip():
        print("STDERR:", err[:1000])
