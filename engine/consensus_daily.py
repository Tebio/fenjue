"""一致预期每日快照（2026-09-23，BACKLOG#17 前置——攒「预告时点的预期值」）。

逻辑：读 data/pead_events.json（东财业绩预告），取最近 LOOKBACK_DAYS 天内 NOTICE_DATE 的
股票（去重、剔已快照），用 consensus_forecast.fetch 抓一致预期 EPS，
落盘 data/consensus_snapshots/<NOTICE_DATE>.json（按预告日归档，一文件一日，重复跑幂等跳过）。
预警线：快照是「当前一致预期」，公告后分析师会修正——所以必须在预告后第一个交易日快照，
差一天预期值就可能已变。跑批时间：每交易日 18:30 BJT。
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "/opt/data/fenjue/engine")
from consensus_forecast import fetch

ROOT = Path("/opt/data/fenjue")
SNAP = ROOT / "data" / "consensus_snapshots"
SNAP.mkdir(exist_ok=True)
LOOKBACK_DAYS = 3  # 覆盖周末/假日断档


def main():
    pead = json.loads((ROOT / "data/pead_events.json").read_text())
    events = pead if isinstance(pead, list) else pead.get("events") or pead.get("rows") or []
    # 最近 N 天有预告的票（NOTICE_DATE 字段实测存在）
    from datetime import date, timedelta
    cutoff = (date.today() - timedelta(days=LOOKBACK_DAYS)).isoformat()
    recent = {}
    for e in events:
        nd = str(e.get("NOTICE_DATE") or e.get("notice_date") or "")[:10]
        code = str(e.get("SECURITY_CODE") or e.get("code") or "").zfill(6)
        if nd >= cutoff and code:
            recent.setdefault(nd, {})[code] = e.get("FORECASTTYPE") or e.get("forecast_type") or ""
    total_new = 0
    for nd in sorted(recent):
        fp = SNAP / f"{nd}.json"
        snap = json.loads(fp.read_text()) if fp.exists() else {}
        codes = [c for c in recent[nd] if c not in snap]
        for code in codes:
            try:
                rows = fetch(code)
                if rows:
                    snap[code] = {"forecast_type": recent[nd][code], "consensus": rows,
                                  "snapshotted_at": time.strftime("%Y-%m-%d %H:%M")}
                    total_new += 1
            except Exception as ex:
                snap[code] = {"error": str(ex)[:100]}
            time.sleep(1.2)  # 同花顺温和限流
        fp.write_text(json.dumps(snap, ensure_ascii=False, indent=1))
        print(f"{nd}: 新增 {len([c for c in codes if c in snap and 'consensus' in snap[c]])} 只（累计 {len(snap)}）")
    print(f"DONE 快照新增 {total_new} 只")


if __name__ == "__main__":
    main()
