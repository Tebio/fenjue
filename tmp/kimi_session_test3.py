#!/usr/bin/env python3
"""Kimi Code 会话 API 测试：curl.exe 版。创建会话→发 prompt→读回复。"""
import json
import subprocess
import time

SSH = ["ssh", "-o", "BatchMode=yes", "-i", "/opt/data/home/.ssh/windows_ed25519",
       "特比欧炸@192.168.2.11"]
TMP = r"C:\Users\Tebio Zack\AppData\Local\Temp\kimi_bridge"
BASE = "http://127.0.0.1:5646/api/v1"


def ssh(cmd, inp=None, timeout=120):
    p = subprocess.run(SSH + [cmd], input=inp, capture_output=True, timeout=timeout)
    return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")


def push_json(obj, name):
    rc, _, _ = ssh(
        'powershell -NoProfile -Command "$t=[Console]::In.ReadToEnd(); '
        f"[IO.File]::WriteAllText('{TMP}\\\\{name}', $t, (New-Object Text.UTF8Encoding $false))\"",
        inp=json.dumps(obj, ensure_ascii=False).encode("utf-8"))
    return rc


def curl(method, path, body_file=None, timeout=60):
    cmd = (f'curl.exe -s -m {timeout} -X {method} "{BASE}{path}" '
           f'-H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json"')
    if body_file:
        cmd += f' --data @"{TMP}\\\\{body_file}"'
    # TOKEN 环境变量在远端设
    full = (f'cmd /c "set /p TOKEN=<"C:\\Users\\Tebio Zack\\.kimi-code\\server.token" & {cmd}"')
    return ssh(full, timeout=timeout + 30)


if __name__ == "__main__":
    ssh(f'mkdir "{TMP}" 2>nul & echo ok', timeout=60)

    # 1) 创建会话
    push_json({"title": "hermes-bridge", "metadata": {"cwd": r"C:\Users\Tebio Zack"}}, "sess.json")
    rc, out, err = curl("POST", "/sessions", "sess.json")
    print("create:", out[:500])
    sid = None
    try:
        j = json.loads(out)
        sid = (j.get("data") or {}).get("id") or (j.get("data") or {}).get("session_id")
    except Exception as e:
        print("parse fail", e)
    print("sid:", sid)
    if not sid:
        raise SystemExit(1)

    # 2) 发 prompt
    push_json({"content": "只回复两个字：收到。不要调用任何工具。"}, "prompt.json")
    rc, out, err = curl("POST", f"/sessions/{sid}/prompts", "prompt.json")
    print("prompt:", out[:400])

    # 3) 轮询状态 + 读消息
    for wait in (15, 20, 30):
        time.sleep(wait)
        rc, out, _ = curl("GET", f"/sessions/{sid}/status")
        print(f"status(+{wait}s):", out[:200])
        if '"idle"' in out or '"completed"' in out or '"done"' in out:
            break
    rc, out, _ = curl("GET", f"/sessions/{sid}/messages")
    print("messages:", out[:2000])
