"""Sensitivity: on known days only 104/178 queried events had auction data returned
(问财 found ~58%). The 27 gap events' RETURNS are known, but their auction fields may
not be retrievable. So the full-sample group mean ranges over how many of the 27 turn
out to have data. Report the range honestly.
"""
import json
import statistics as st
from itertools import combinations
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
CUR = json.loads((ROOT / "data" / "auction_deep_strength_20261017.json").read_text())
known = CUR["events"]
GAP = json.loads(Path("/opt/data/cache/scratch/gap_events.json").read_text())["events"]

# find rate on known days (from the PIT cache)
import glob
found = tot = 0
for f in glob.glob(str(ROOT / "data/research/auction_deep/*.json")):
    for it in json.loads(Path(f).read_text()).get("items", []):
        tot += 1
        if it.get("found") and it.get("auction_volume") is not None:
            found += 1
rate = found / tot
print("known-day find rate: %d/%d = %.1f%%" % (found, tot, 100 * rate))

K = [r["ret5"] for r in known]
G = sorted(r["ret5"] for r in GAP)
kmean = st.mean(K)
print("known T+5 mean %.2f%% (n=%d)" % (100 * kmean, len(K)))
print("\nfull-sample 全组 T+5 mean vs #gap events actually retrievable:")
for f in sorted({0, 5, 8, 11, round(rate * len(G)), 16, 20, len(G)}):
    if f > len(G):
        continue
    # best case: the f most favourable gap events are the retrievable ones
    hi = st.mean(K + G[len(G) - f:]) if f else kmean
    lo = st.mean(K + G[:f]) if f else kmean
    print("  f=%2d (%.0f%% of gap): T+5 %.2f%% .. %.2f%%   win%% %.1f .. %.1f"
          % (f, 100 * f / len(G), 100 * lo, 100 * hi,
             100 * sum(1 for x in K + G[:f] if x > 0) / (len(K) + f),
             100 * sum(1 for x in K + G[len(G) - f:] if x > 0) / (len(K) + f)))

out = {"_meta": {"card": "t_2bcb8552", "kind": "find_rate_sensitivity",
                 "known_day_find_rate": round(rate, 4), "known_found": found, "known_queried": tot,
                 "note": "缺口 27 事件的收益已知，但竞价字段能否取到取决于问财命中率"},
       "rows": [{"f": f, "T5_mean_lo_pct": round(100 * st.mean(K + G[:f]), 2) if f else round(100 * kmean, 2),
                 "T5_mean_hi_pct": round(100 * st.mean(K + G[len(G) - f:]), 2) if f else round(100 * kmean, 2)}
                for f in range(0, len(G) + 1)]}
p = ROOT / "data" / "auction_deep_find_rate_sensitivity_20261016.json"
p.write_text(json.dumps(out, ensure_ascii=False, indent=1))
print("-> %s" % p)
