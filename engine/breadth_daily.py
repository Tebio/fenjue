"""市场温度（均线多头占比）日更（2026-09-29 立）。

终审结论（tmp/breadth_final.py，滚动250日分位无前视）：
冰点档(≤10%分位) T+10 64%/+0.81%（6/7年赢基线）；过热档(≥90%分位) T+10 42%/-0.41%（8年中6年跑输当年基线）。
定位=仓位调节环境传感器（减仓侧更强），不做个股信号。
产物 data/breadth_daily.json：{date: {total, bull, bull_pct}} 只增量追加当日（幂等），
分位由读侧（env_state）按滚动250日现算。cron 每交易日 18:55 BJT（kcache 增量后）。
"""
import glob
import json
import sys
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
OUT = ROOT / "data" / "breadth_daily.json"


def compute(day=None):
    """算指定日（默认=big_kcache 最新公共日期）的多头占比"""
    total = bull = 0
    latest = None
    for fp in glob.glob(str(ROOT / "data/big_kcache/*.json")):
        code = fp.split("/")[-1].split(".")[0]
        if code[0] not in "06" or code.startswith(("300", "301", "688")):
            continue
        bars = json.load(open(fp))
        if not bars:
            continue
        if latest is None or bars[-1]["date"] > latest:
            latest = bars[-1]["date"]
        target = day or bars[-1]["date"]
        if bars[-1]["date"] != target:
            continue
        if len(bars) < 61:
            continue
        c = [b["close"] for b in bars]
        i = len(c) - 1
        m5, m10 = sum(c[i - 4:i + 1]) / 5, sum(c[i - 9:i + 1]) / 10
        m20, m60 = sum(c[i - 19:i + 1]) / 20, sum(c[i - 59:i + 1]) / 60
        total += 1
        if m5 > m10 > m20 > m60:
            bull += 1
    if total < 1000:
        raise SystemExit(f"[SILENT] 覆盖不足（{total} 只），不落盘")
    return target, total, bull


def main():
    day = sys.argv[1] if len(sys.argv) > 1 else None
    data = json.loads(OUT.read_text()) if OUT.exists() else {}
    target, total, bull = compute(day)
    if target in data:
        print(f"{target} 已在库，跳过")
        return
    data[target] = {"total": total, "bull": bull, "bull_pct": round(bull / total, 4)}
    OUT.write_text(json.dumps(data))
    print(f"{target}: 多头占比 {bull}/{total} = {bull / total * 100:.1f}%")


if __name__ == "__main__":
    main()
