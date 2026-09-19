#!/usr/bin/env python3
"""dispatch_loser250.py — 给 Kimi Code 派 LOSER250_OS20 一致预期+业绩点评任务。

流程：新会话 → 设模型 → 发任务书 → 轮询至完成 → 拉回回复与产出文件。
产出文件约定：C:\\Users\\Tebio Zack\\kimi-out\\loser250_consensus_20260918.md
"""
import base64
import json
import re
import subprocess
import sys
import time

sys.path.insert(0, "/opt/data/scripts")
import kimi_bridge as kb

TMP = r"C:\Users\Tebio Zack\AppData\Local\Temp\kimi_bridge"
OUT_WIN = r"C:\Users\Tebio Zack\kimi-out\loser250_consensus_20260918.md"

STOCKS = [
    ("2026-09-15", "605188"), ("2026-09-15", "603983"), ("2026-09-02", "000545"),
    ("2026-08-31", "600363"), ("2026-08-26", "002731"), ("2026-08-24", "603382"),
    ("2026-08-20", "002896"), ("2026-08-19", "605286"), ("2026-08-19", "603887"),
    ("2026-08-19", "603767"), ("2026-08-19", "603666"), ("2026-08-19", "603662"),
    ("2026-08-19", "603166"), ("2026-08-19", "003021"), ("2026-08-19", "002965"),
    ("2026-08-19", "002743"), ("2026-08-19", "002402"), ("2026-08-19", "002229"),
    ("2026-08-19", "002031"), ("2026-08-10", "002194"),
]


def push_b64(text, win_path):
    b64 = base64.b64encode(text.encode("utf-8")).decode()
    kb.ssh_run(f'powershell -NoProfile -Command "[IO.File]::WriteAllText(\'{win_path}.b64\', \'{b64}\')"')
    kb.ssh_run(f'powershell -NoProfile -Command "[IO.File]::WriteAllBytes(\'{win_path}\', [Convert]::FromBase64String((Get-Content \'{win_path}.b64\' -Raw).Trim()))"')


def ps_read(win_path):
    return kb.ps_read(win_path)  # 桥内已解包：str 或 None


def api(method, path, obj=None):
    if obj is not None:
        push_b64(json.dumps(obj, ensure_ascii=False), TMP + r"\body.json")
        r = kb.ssh_run(f'powershell -NoProfile -ExecutionPolicy Bypass -File "{TMP}\\kb_call.ps1" -Method {method} -Path "{path}" -BodyFile "{TMP}\\body.json"', timeout=120)
    else:
        r = kb.ssh_run(f'powershell -NoProfile -ExecutionPolicy Bypass -File "{TMP}\\kb_call.ps1" -Method {method} -Path "{path}"', timeout=90)
    return r[1] if isinstance(r, tuple) else r  # ssh_run 返回 (rc, out, err)


def main():
    kb.ensure_fresh_token()
    # 确保 Windows 侧 kb_call.ps1 存在（幂等部署）
    helper = r'''param([string]$Method, [string]$Path, [string]$BodyFile = "")
$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$t = (Get-Content 'C:\Users\Tebio Zack\.kimi-code\server.token' -Raw).Trim()
$h = @{ Authorization = "Bearer $t" }
$u = "http://127.0.0.1:5646/api/v1$Path"
try {
  if ($BodyFile -ne "") {
    $b = [IO.File]::ReadAllBytes($BodyFile)
    $r = Invoke-WebRequest -UseBasicParsing -Method $Method -Uri $u -Headers $h -ContentType 'application/json' -Body $b -TimeoutSec 90
  } else {
    $r = Invoke-WebRequest -UseBasicParsing -Method $Method -Uri $u -Headers $h -TimeoutSec 30
  }
  Write-Output $r.Content
} catch {
  Write-Output ("ERR " + $_.Exception.Message)
  if ($_.ErrorDetails.Message) { Write-Output $_.ErrorDetails.Message }
}
'''
    push_b64(helper, TMP + r"\kb_call.ps1")

    stocks_txt = "\n".join(f"| {d} | {c}.{'SH' if c.startswith('6') else 'SZ'} |" for d, c in STOCKS)
    prompt = f"""你是机构金融分析师。请使用你已安装的 institutional-finance-kit 插件里的「业绩点评 earnings-review」和「一致预期地图 consensus-map」技能，完成以下任务。

# 任务
对下面 20 只 A 股逐一做基本面快评。这些票是我们量化策略（MA60 下方跌停+250 日输家+超跌 20%）近期的命中票，我们要看它们的基本面与一致预期画像。

| 信号日 | 代码 |
|---|---|
{stocks_txt}

# 每只要输出的字段
1. 股票名称
2. 最新一期财报（报告期、营收同比、归母净利同比，用业绩点评技能的口径）
3. 一致预期：覆盖家数、FY1 归母净利一致预期、FY1 最高/最低值（算分歧度）
4. 一句话定性（估值状态/业绩趋势/有无明显风险点）

# 数据纪律（严格遵守你们 data-routing 技能的要求）
- 覆盖家数 <3 家不出一致预期数字，标「覆盖不足」
- 财报锚定 period_end_date，禁用自然年映射
- 拿不到的字段一律写 null，禁止编造或推测
- 标注每个数字的来源数据源

# 交付
把完整结果写成 markdown 表格，保存到文件：{OUT_WIN}
最后回复一行：DONE + 已覆盖家数达标的票数和总票数。"""

    print("== create session", flush=True)
    out = api("POST", "/sessions", {"title": "hermes-loser250-consensus", "metadata": {"cwd": r"C:\Users\Tebio Zack"}, "agent_config": {"model": "kimi-code/k3"}})
    print(out[:200], flush=True)
    sid = json.loads(out)["data"]["id"]
    print("sid:", sid, flush=True)

    print("== set profile", flush=True)
    print(api("POST", f"/sessions/{sid}/profile", {"agent_config": {"model": "kimi-code/k3"}})[:150], flush=True)

    print("== send prompt", flush=True)
    print(api("POST", f"/sessions/{sid}/prompts", {"content": [{"type": "text", "text": prompt}]})[:200], flush=True)

    print("== poll", flush=True)
    reason = ""
    for i in range(80):  # 最长 ~20 分钟
        time.sleep(15)
        st = api("GET", f"/sessions/{sid}")
        m = re.search(r'"last_turn_reason":"(\w+)"', st)
        busy = '"busy":true' in st
        if i % 4 == 0:
            print(f"poll{i} busy={busy} reason={m.group(1) if m else '-'}", flush=True)
        if not busy and m:
            reason = m.group(1)
            break

    print("final reason:", reason, flush=True)
    msg = api("GET", f"/sessions/{sid}/messages")
    texts = re.findall(r'"text":"((?:[^"\\]|\\.)*)"', msg)
    reply = ""
    for t in texts:
        d = t.encode().decode("unicode_escape", errors="replace")
        if "system-reminder" not in d and "业绩点评" not in d[:50]:
            reply = d
    print("ASSISTANT TAIL:", reply[-600:], flush=True)

    # 拉回产出文件
    raw = ps_read(OUT_WIN)
    if raw:
        with open("/opt/data/fenjue/tmp/loser250_consensus_20260918.md", "w", encoding="utf-8") as f:
            f.write(raw)
        print("OUTFILE saved, len:", len(raw), flush=True)
    else:
        print("OUTFILE missing", flush=True)
    print("SESSION_ID:", sid, flush=True)


if __name__ == "__main__":
    main()
