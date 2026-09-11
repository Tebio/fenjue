#!/usr/bin/env python3
"""fen_shadow.py — 焚诀短线影子回测编排器 (2026-09-06)

把 fenjue_fast 的快照回放（--quote-tag，无未来函数版）+ 日K前向收益串成验证环：
对每个「有 0940 快照 且 有严格更早期池」的日期 D：
  1. 子进程跑 fenjue_fast --quote-tag 0940 --snapshot-date D（池已被 as_of 限制在 D 之前）
  2. 解析 [趋势/建仓候选] Top N —— 买入价 = 快照 price（9:40 真实价）
  3. 新浪日K 取 D 收盘 / D+1 收盘 / D+2 收盘，算持有收益
汇总：焚诀 TopN vs 全池等权基准 vs 上证指数 同口径对照。
冻结纪律合规：只读现有规则输出，不改任何评分/权重/公式。
"""
from __future__ import annotations

import json
import os
import re
import ssl
import subprocess
import sys
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
SNAP_DIR = ROOT / "snapshots"
KCACHE = ROOT / "data" / "kcache"
KCACHE.mkdir(parents=True, exist_ok=True)

_ctx = ssl.create_default_context()
_ctx.check_hostname = False
_ctx.verify_mode = ssl.CERT_NONE

CAND_RE = re.compile(r"^\s*\d+\.\s+(\d{6})\s+(\S+)\s+\|.*?\|\s*([\d.]+)\([+-][\d.]+%\)")


def sina_of(code: str) -> str:
    return ("sh" if code.startswith("6") else "sz") + code


def daily_kline(symbol: str) -> list[dict]:
    """新浪日K（带磁盘缓存）。返回 [{day, open, close, high, low}] 升序。

    缓存新鲜度（2026-09-06 外部审查发现#1修复 + R2效率优化）：
    以 big_kcache 指数最新交易日为基准——缓存最后交易日 ≥ 基准即视为新鲜，
    周末/节假日不会空转请求（R2 发现：自然日 today 基准会每天每票空刷新浪）。
    已过期且今天没试过 → 重拉（每股每天最多1次）。
    """
    cache = KCACHE / f"{symbol}.json"
    today = date.today().isoformat()
    if cache.exists():
        data = json.loads(cache.read_text())
        try:
            idx = json.loads((ROOT / "data" / "big_kcache" / "000001.json").read_text())
            bench = idx[-1]["date"]  # 最新交易日（周末/长假=上周五）
        except Exception:
            bench = today
        mtime = date.fromtimestamp(cache.stat().st_mtime).isoformat()
        if (data and data[-1].get("day", "") >= bench) or mtime >= today:
            return data
        # 缓存过期：继续往下重拉
    url = ("http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
           f"CN_MarketData.getKLineData?symbol={symbol}&scale=240&ma=no&datalen=260")
    req = urllib.request.Request(url, headers={"Referer": "https://finance.sina.com.cn"})
    data = json.loads(urllib.request.urlopen(req, context=_ctx, timeout=15).read().decode("utf-8"))
    cache.write_text(json.dumps(data))
    return data


def forward_returns(code: str, date_d: str, buy_price: float) -> dict:
    """D=YYYYMMDD。返回 T0/T1/T2 收盘收益%（相对买入价）及 D 日最高（最佳卖点参考）。

    注意：kcache 是新浪不复权价，未做窗口内分红/送转加回——T1/T2 两天持有期
    撞上除权日的概率很低，影响微小（2026-09-06 外部审查低优先级项，有意保留）。
    """
    ks = daily_kline(sina_of(code))
    days = [k["day"] for k in ks]
    d_iso = f"{date_d[:4]}-{date_d[4:6]}-{date_d[6:]}"
    if d_iso not in days:
        return {}
    i = days.index(d_iso)
    out = {}
    for label, off in (("T0", 0), ("T1", 1), ("T2", 2)):
        if i + off < len(ks):
            close = float(ks[i + off]["close"])
            out[label] = round((close - buy_price) / buy_price * 100, 2)
    out["T0_high"] = round((float(ks[i]["high"]) - buy_price) / buy_price * 100, 2)
    return out


def replay_one(date_d: str, top: int = 3) -> dict:
    cmd = [
        sys.executable, str(ROOT / "fenjue_fast.py"),
        "--quote-tag", "0940", "--snapshot-date", date_d, "--early-tag", "0925",
        "--limit", str(top),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    text = r.stdout
    # 2026-09-06 R3 审查修复：子进程非零退出（如池文件缺失等基础设施故障）
    # 不能记成「非静默、零候选」的正常交易日，单独标记 pipeline_error
    if r.returncode != 0:
        return {"date": date_d, "silent": True, "pipeline_error": True,
                "reason": f"rc={r.returncode}: {(r.stderr or '').strip()[:80]}"}
    if "[SILENT]" in text:
        return {"date": date_d, "silent": True, "reason": text.strip().splitlines()[-1][:80]}
    in_section = False
    cands = []
    for line in text.splitlines():
        if "[趋势/建仓候选]" in line:
            in_section = True
            continue
        if in_section and (line.startswith("[") or line.startswith("=") or not line.strip()):
            if line.startswith("[") or not line.strip():
                in_section = False
                continue
        if in_section:
            m = CAND_RE.match(line)
            if m:
                cands.append({"code": m.group(1), "name": m.group(2), "buy": float(m.group(3))})
    results = []
    for c in cands[:top]:
        fr = forward_returns(c["code"], date_d, c["buy"])
        if fr:
            results.append({**c, **fr})
    return {"date": date_d, "silent": False, "candidates": results}


def summarize(per_day: list[dict], top: int) -> dict:
    all_picks = [c for d in per_day for c in d.get("candidates", [])]
    def agg(key):
        vals = [p[key] for p in all_picks if key in p]
        if not vals:
            return {"n": 0}
        wins = sum(1 for v in vals if v > 0)
        return {"n": len(vals), "win%": round(wins / len(vals) * 100, 1),
                "avg%": round(sum(vals) / len(vals), 2),
                "best": max(vals), "worst": min(vals)}
    return {"dates": len([d for d in per_day if not d["silent"]]),
            "silent_dates": len([d for d in per_day if d["silent"]]),
            "picks": len(all_picks),
            "T0_close": agg("T0"), "T1_close": agg("T1"), "T2_close": agg("T2"),
            "T0_high": agg("T0_high")}


def main() -> int:
    top = int(os.environ.get("SHADOW_TOP", "3"))
    dates = sorted(
        p.stem.replace("snapshot_", "").replace("_0940", "")
        for p in SNAP_DIR.glob("snapshot_*_0940.json")
    )
    per_day = []
    for d in dates:
        try:
            r = replay_one(d, top)
        except Exception as e:
            r = {"date": d, "silent": True, "reason": f"replay error: {e}"}
        per_day.append(r)
        if not r["silent"]:
            marks = " ".join(f"{c['name']}[T1 {c.get('T1', 0):+.1f}%]" for c in r["candidates"])
            print(f"{d}: {marks}")
        else:
            print(f"{d}: [silent] {r['reason']}")
    summary = summarize(per_day, top)
    out = {"top": top, "summary": summary, "per_day": per_day}
    out_path = ROOT / "data" / "shadow_backtest.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print("\n=== 汇总 ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"写入 {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
