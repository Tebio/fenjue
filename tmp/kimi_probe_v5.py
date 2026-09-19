#!/usr/bin/env python3
"""Kimi 数据源端到端实测 v5：干净 ESM driver，等异步响应落盘。"""
import json
import subprocess

SSH = ["ssh", "-o", "BatchMode=yes", "-i", "/opt/data/home/.ssh/windows_ed25519",
       "特比欧炸@192.168.2.11"]
WIN = r"C:\Users\Tebio Zack"
MCP_DIR = WIN + r"\.kimi-code\plugins\managed\kimi-datasource"
TMP = WIN + r"\AppData\Local\Temp\kimi_probe"

DRIVER = r'''
import { spawn } from 'node:child_process';
import fs from 'node:fs';

const [reqsPath, outPath, mcpCwd] = process.argv.slice(2);
const reqs = JSON.parse(fs.readFileSync(reqsPath, 'utf8'));
const child = spawn(process.execPath, ['bin/kimi-datasource.mjs'],
                    { cwd: mcpCwd, stdio: ['pipe', 'pipe', 'pipe'] });

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
    try {
      const obj = JSON.parse(line);
      results.push(obj);
      if (obj.id !== undefined) pending.delete(obj.id);
    } catch {}
  }
});
child.stderr.on('data', d => results.push({ stderr: d.toString('utf8').slice(0, 500) }));

const sleep = ms => new Promise(r => setTimeout(r, ms));
const t0 = Date.now();
for (const r of reqs) {
  child.stdin.write(JSON.stringify(r) + '\n');
  if (r.id !== undefined) pending.add(r.id);
  await sleep(400);
}
while (pending.size > 0 && Date.now() - t0 < 170000) await sleep(1000);
await sleep(2000);
fs.writeFileSync(outPath, JSON.stringify(results, null, 1), 'utf8');
child.kill();
process.exit(0);
'''

REQS = [
    {"jsonrpc": "2.0", "id": 1, "method": "initialize",
     "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                "clientInfo": {"name": "hermes", "version": "1.0"}}},
    {"jsonrpc": "2.0", "method": "notifications/initialized"},
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
    print("push driver:", push(DRIVER, TMP + r"\driver.mjs"))

    cmd = f'cd /d "{TMP}" && node driver.mjs "{TMP}\\reqs.json" "{TMP}\\out5.json" "{MCP_DIR}"'
    p = subprocess.run(SSH + [cmd], capture_output=True, timeout=400)
    print("driver rc", p.returncode, p.stderr.decode("utf-8", "replace")[:400])

    p2 = subprocess.run(SSH + [
        f'powershell -NoProfile -Command "[Console]::OutputEncoding=[Text.Encoding]::UTF8; $f=\'{TMP}\\out5.json\'; if(Test-Path $f){{$s=Get-Content $f -Raw; $s.Substring(0,[Math]::Min(5000,$s.Length))}} else {{\'NOFILE\'}}"'
    ], capture_output=True, timeout=180)
    print("=== OUT ===")
    print(p2.stdout.decode("utf-8", "replace")[:5200])
