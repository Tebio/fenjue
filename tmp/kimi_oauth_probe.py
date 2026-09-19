#!/usr/bin/env python3
"""Kimi Code OAuth 刷新可行性验证。

凭据文件：{access_token, refresh_token, expires_at, scope:kimi-code, token_type:Bearer, expires_in:900}
OAuth host：https://auth.kimi.com
先探测标准 OIDC 发现文档与 token 端点，再用 refresh_token 换新 token。
"""
import json
import subprocess
import sys

SSH = ["ssh", "-o", "BatchMode=yes", "-i", "/opt/data/home/.ssh/windows_ed25519",
       "特比欧炸@192.168.2.11"]
CRED = r"C:\Users\Tebio Zack\.kimi-code\credentials\kimi-code.json"


def win_pwsh(script, timeout=120):
    p = subprocess.run(SSH + [f'powershell -NoProfile -Command "{script}"'],
                       capture_output=True, timeout=timeout)
    return p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")


if __name__ == "__main__":
    # 1) 探测 OIDC 发现文档（Windows 端联网）
    for url in ["https://auth.kimi.com/.well-known/openid-configuration",
                "https://auth.kimi.com/.well-known/oauth-authorization-server"]:
        out, err = win_pwsh(
            f"try {{ (Invoke-WebRequest -UseBasicParsing '{url}' -TimeoutSec 20).Content }} "
            f"catch {{ 'ERR: ' + $_.Exception.Message }}")
        print(f"=== {url}")
        print(out.strip()[:1500])
        print()

    # 2) 提取 refresh_token 长度（不打印内容）
    out, err = win_pwsh(
        "$c = Get-Content '" + CRED + "' -Raw | ConvertFrom-Json; "
        "'access_len=' + $c.access_token.Length + ' refresh_len=' + $c.refresh_token.Length + "
        "' expires_at=' + $c.expires_at")
    print("=== creds meta:", out.strip())
