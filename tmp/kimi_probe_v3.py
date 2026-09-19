#!/usr/bin/env python3
"""Kimi 数据源实测 v3：用 Node driver 保持 stdin 打开，等待异步响应。

v2 教训：node MCP server 收到请求后向后端 API 发 HTTP，返回是异步的；
stdin 一关闭进程就退出，只留下 initialize 的回包。
改成：写一个 Node driver，逐条发请求、保持 stdin、等响应写到文件。
"""
import json
import subprocess

SSH = ["ssh", "-o", "BatchMode=yes", "-i", "/opt/data/home/.ssh/windows_ed25519",
       "特比欧炸@192.168.2.11"]
WIN = r"C:\Users\Tebio Zack"
MCP_DIR = WIN + r"\.kimi-code\plugins\managed\kimi-datasource"
TMP = WIN + r"\AppData\Local\Temp\kimi_probe"

DRIVER = r'''
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const reqs = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const outPath = process.argv[3];

const child = spawn(process.execPath, ['bin/kimi-datasource.mjs'],
                    { cwd: process.argv[4], stdio: ['pipe','pipe','pipe'] });

let buf = '';
const results = [];
const pending = new Set();

child.stdout.on('data', d => {
  buf += d.toString('utf8');
  let idx;
  while ((idx = buf.indexOf('\n')) >= 0) {
    const line = buf.slice(0, idx).trim();
    buf = buf.slice(idx + 1);
    if (!line) continue;
    let obj;
    try { obj = JSON.parse(line); } catch (e) { continue; }
    results.push(obj);
    if (obj.id !== undefined) pending.delete(obj.id);
  }
});

function done() {
  fs.writeFileSync(outPath, JSON.stringify(results, null, 1), 'utf8');
  try { child.kill(); } catch (e) {}
  process.exit(0);
}

(async () => {
  const t0 = Date.now();
  for (const r of reqs) {
    child.stdin.write(JSON.stringify(r) + '\n');
    if (r.id !== undefined) pending.add(r.id);
    await new Promise(res => setTimeout(res, 400));
  }
  // 等待所有带 id 的响应，最多 180 秒
  while (pending.size > 0 && Date.now() - t0 < 180000) {
    await new Promise(res => setTimeout(res, 1000));
  }
  // 再多等一会儿收尾
  await new Promise(res => setTimeout(res, 2000));
  done();
})();
'''

REQS = [
    {"jsonrpc": "2.0", "id": 1, "method": "initialize",
     "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                "clientInfo": {"name": "hermes", "version": "1.0"}}},
    {"jsonrpc": "2.0", "method": "notifications/initialized"},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
     "params": {"name": "get_data_source_desc", "arguments": {"name": "stock_finance_data"}}},
]


def push(text, win_path):
    p = subprocess.run(SSH + [
        f'powershell -NoProfile -Command "$t=[Console]::In.ReadToEnd(); [IO.File]::WriteAllText(\'{win_path}\', $t, (New-Object Text.UTF8Encoding $false))"'
    ], input=text.encode("utf-8"), capture_output=True, timeout=180)
    return p.returncode


if __name__ == "__main__":
    subprocess.run(SSH + [f'mkdir "{TMP}" 2>nul & echo ok'], capture_output=True, timeout=60)
    print("push reqs:", push(json.dumps(REQS, ensure_ascii=False), TMP + r"\reqs.json"))
    print("push driver:", push(DRIVER, TMP + r"\driver.js"))

    cmd = (f'cd /d "{TMP}" && node driver.js "{TMP}\\reqs.json" "{TMP}\\out.json" "{MCP_DIR}"')
    p = subprocess.run(SSH + [cmd], capture_output=True, timeout=600)
    print("driver rc", p.returncode, p.stderr.decode("utf-8", "replace")[:400])

    # 读回
    p2 = subprocess.run(SSH + [
        f'powershell -NoProfile -Command "$f=\'{TMP}\\out.json\'; if(Test-Path $f){{$s=Get-Content $f -Raw; $s.Substring(0,[Math]::Min(6000,$s.Length))}} else {{\'NOFILE\'}}"'
    ], capture_output=True, timeout=180)
    print("=== OUT ===")
    print(p2.stdout.decode("utf-8", "replace")[:6200])
