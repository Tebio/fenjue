#!/usr/bin/env python3
"""金股原始数据抓取（含 公告日期 / 组合时间 / 研究机构，用于 PIT 检验）。

背景（2026-10-19 发现）：`fetch_month(mo)` 的 mo 实为**公告月**，一次查询返回的是
「上月末发布的下一月组合」——chunks_info 明确写 `公告日期等于YYYY年M月`。
例：查 2026年9月 的 230 条里，组合时间 是 202610（10 月组合）。故缓存文件名的月份
≠ 组合所属月份，过去按「缓存月=组合月」做的择时口径全部偏移了一个月。

本脚本按公告月全量翻页落盘原始行，供 engine/gold_pit_study.py 按 组合时间 重新归月。
用法：.venv/bin/python engine/gold_raw_fetch.py 2026-08 2026-09 2026-10
"""
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
RAW = ROOT / "data" / "gold_raw"
RAW.mkdir(exist_ok=True)
CLI = ROOT.parent / ".iwencai-skillhub/skills/hithink-insresearch-query/scripts/cli.py"

env = {}
for line in (ROOT.parent / ".env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        env[k] = v


def fetch(mo, force=False):
    fp = RAW / f"{mo}.json"
    if fp.exists() and not force:
        return json.loads(fp.read_text())
    y, m = mo.split("-")
    rows, page = [], 1
    total = None
    while True:
        r = subprocess.run(["python3", str(CLI), "--query", f"{y}年{int(m)}月 券商金股",
                            "--page", str(page), "--limit", "50"],
                           capture_output=True, text=True, env=env, timeout=90)
        try:
            d = json.loads(r.stdout)
        except Exception:
            print(f"{mo} page{page} 非 JSON（配额耗尽/接口异常）：{r.stdout[:80]}")
            break
        total = d.get("code_count")
        got = d.get("datas") or []
        rows.extend(got)
        if not d.get("has_more") or not got or page >= 12:
            break
        page += 1
        time.sleep(2.5)
    fp.write_text(json.dumps(rows, ensure_ascii=False))
    print(f"{mo}: 落盘 {len(rows)} 条（接口 code_count={total}），{page} 页")
    return rows


if __name__ == "__main__":
    months = sys.argv[1:] or ["2026-08", "2026-09", "2026-10"]
    for mo in months:
        fetch(mo, force=True)
        time.sleep(3)
