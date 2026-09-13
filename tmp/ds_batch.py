#!/usr/bin/env python3
"""tmp/ds_batch.py — DeepSeek V4.1 flash 攒批执行器（2026-09-13 清欠账批）

攒批制纪律：每周一批封顶；DS 只产出代码/设计，不碰数据；K3 审查+实跑+验收。
用法：python3 tmp/ds_batch.py   # 顺序跑完 tmp/ds_tasks/*.md 规格，产出同名 .out.md
"""
import json, sys, time, urllib.request
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
TASKS = ROOT / "tmp/ds_tasks"

key = base = model = None
for line in open("/opt/data/.env"):
    if line.startswith("DEEPSEEK_API_KEY="): key = line.strip().split("=", 1)[1]
    if line.startswith("CUSTOM_BASE_URL="): base = line.strip().split("=", 1)[1]
    if line.startswith("HERMES_INFERENCE_MODEL="): model = line.strip().split("=", 1)[1]

SYSTEM = """你是量化执行工程师，为焚诀A股研究体系写代码。铁律（违反任何一条=废品）：
1. 零未来函数：信号日只能用当日及之前的数据；入场日不得用出场之后的信息。
2. T+1 物理合规：买入日不可卖出；任何模拟盘输出前过「出场日>入场日」硬断言。
3. 净口径：手续费 0.0015/边。
4. 前复权价算比率安全，绝对价位跨分红期不可比（用不复权或 ratio）。
5. 只输出完整可运行的 Python 文件（stdlib+json，禁新依赖），不要解释性废话。
6. 文件头注释写清：口径、数据源路径、输出路径、已知限制。
7. 路径常量：ROOT="/opt/data/fenjue"，数据在 ROOT+"/data"。
8. 随机对照必须带（seed 固定）。"""


def call(task_file: Path) -> str:
    spec = task_file.read_text()
    body = {"model": model, "messages": [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": spec}], "max_tokens": 32000, "temperature": 0.2}
    req = urllib.request.Request(base.rstrip("/") + "/chat/completions",
                                 data=json.dumps(body).encode(),
                                 headers={"Authorization": "Bearer " + key,
                                          "Content-Type": "application/json"})
    for attempt in range(3):
        try:
            r = json.load(urllib.request.urlopen(req, timeout=280))
            return r["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"  retry {attempt}: {e}", flush=True)
            time.sleep(5 * (attempt + 1))
    return "FAILED"


def main():
    for tf in sorted(f for f in TASKS.glob("*.md") if not f.name.endswith(".out.md")):  # 防把产出当任务书重跑（2026-09-13 实战踩过）
        out = tf.with_suffix(".out.md")
        if out.exists():
            print(f"skip {tf.name} (done)", flush=True)
            continue
        print(f"→ {tf.name} ({len(tf.read_text())} chars)", flush=True)
        t0 = time.time()
        resp = call(tf)
        out.write_text(resp)
        print(f"  done in {time.time()-t0:.0f}s, {len(resp)} chars → {out.name}", flush=True)


if __name__ == "__main__":
    main()
