"""What of the 65-day full sample is EXACTLY determined without 问财 quota?

All 205 DEEP events' returns are computable from big_kcache. The 27 gap events lack only
their auction fields (vr / unmatched). So:
  - FULL-SAMPLE 全组 means/win-rates: EXACT (all returns known)
  - vr / unmatched SPLITS: only bounded (see auction_gap_bound.py)
This script nails down the exact part and the honest range for the rest.
"""
import json
import statistics as st
from pathlib import Path
import sys

ROOT = Path("/opt/data/fenjue")
sys.path.insert(0, str(ROOT / "engine"))
from costs import FLAT_RT  # noqa: E402

FEE = FLAT_RT
CUR = json.loads((ROOT / "data" / "auction_deep_strength_20261017.json").read_text())
known = CUR["events"]
GAP = json.loads(Path("/opt/data/cache/scratch/gap_events.json").read_text())["events"]
ALL = known + GAP
print("known n=%d  gap n=%d  full n=%d" % (len(known), len(GAP), len(ALL)))


def agg(rows, tag):
    r1 = [r["ret1"] for r in rows]
    r5 = [r["ret5"] for r in rows]
    by = {}
    for r in rows:
        by.setdefault(r["entry"], []).append(r["ret5"])
    dm = [st.mean(v) for v in by.values()]
    d = {"tag": tag, "n": len(rows), "n_days": len(by),
         "T1_mean_pct": round(100 * st.mean(r1), 2),
         "T1_win_pct": round(100 * sum(1 for x in r1 if x > 0) / len(r1), 1),
         "T5_mean_pct": round(100 * st.mean(r5), 2),
         "T5_win_pct": round(100 * sum(1 for x in r5 if x > 0) / len(r5), 1),
         "day_eq_T5_pct": round(100 * st.mean(dm), 2),
         "day_eq_T5_win_pct": round(100 * sum(1 for x in dm if x > 0) / len(dm), 1)}
    print("  %-14s n=%3d days=%2d  T+1 %+6.2f%%/%4.1f%%   T+5 %+6.2f%%/%4.1f%%   day-eq T+5 %+6.2f%%/%4.1f%%"
          % (tag, d["n"], d["n_days"], d["T1_mean_pct"], d["T1_win_pct"],
             d["T5_mean_pct"], d["T5_win_pct"], d["day_eq_T5_pct"], d["day_eq_T5_win_pct"]))
    return d


print("\n=== EXACT (no auction fields needed) ===")
full = agg(ALL, "62/65 full")
k58 = agg(known, "58/65 known")
gp = agg(GAP, "7-day gap")
print("\n  => 全组 T+5 从 58 日版 %+.2f%% 抬到全量 %+.2f%%（%+.2fpp）; 胜率 %.1f%% -> %.1f%%"
      % (k58["T5_mean_pct"], full["T5_mean_pct"], full["T5_mean_pct"] - k58["T5_mean_pct"],
         k58["T5_win_pct"], full["T5_win_pct"]))
print("  => 全组 T+1 %+.2f%% -> %+.2f%%;日等权 T+5 %+.2f%% -> %+.2f%%"
      % (k58["T1_mean_pct"], full["T1_mean_pct"], k58["day_eq_T5_pct"], full["day_eq_T5_pct"]))

out = {"_meta": {"card": "t_2bcb8552", "kind": "exact_full_sample_agg",
                 "note": ("全部 131 事件的收益均可从 big_kcache 直接算出；缺的只是 27 个缺口事件的"
                          "竞价字段（vr/unmatched），故全组口径精确、分组口径只可界定"),
                 "gap_days": sorted({r["entry"] for r in GAP})},
       "exact": {"full_62of65": full, "known_58of65": k58, "gap_7days": gp},
       "bounded_only": {"vr_split": "见 auction_deep_strength_gapbound_20261016.json",
                        "unmatched_split": "同上"}}
p = ROOT / "data" / "auction_deep_full_sample_exact_20261016.json"
p.write_text(json.dumps(out, ensure_ascii=False, indent=1))
print("-> %s" % p)
