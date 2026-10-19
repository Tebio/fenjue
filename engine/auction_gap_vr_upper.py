"""Sharpen the gap bound with a HARD, free-data upper bound on the gap events' vr.

vr = 竞价量 / mean(vol[T-5..T-1]).  The auction volume is part of the day's total
volume, so   竞价量 <= vol[entry_day]   =>   vr_true <= vr_upper := vol[entry]/den5.

vr_upper is computable for the 27 gap events from big_kcache alone (no 问财 quota).
If vr_upper < median for most gap events, they MUST land in the low group, which
converts the "adversarial can flip" result into a constrained statement.

Also: the auction PCT of a gap event is known from big_kcache (open/prev_close-1).
"""
import json
import statistics as st
from pathlib import Path
import sys

ROOT = Path("/opt/data/fenjue")
sys.path.insert(0, str(ROOT / "engine"))

CUR = json.loads((ROOT / "data" / "auction_deep_strength_20261017.json").read_text())
MED = CUR["vr_median"]
GAP = json.loads(Path("/opt/data/cache/scratch/gap_events.json").read_text())["events"]
KC = ROOT / "data" / "big_kcache"
EV = json.loads((ROOT / "data" / "auction_confirm_events_20261016.json").read_text())["DEEP"]
meta = {(e["code"], e["entry_date"]): e for e in EV}


def kc(code):
    p = KC / f"{code}.json"
    return json.loads(p.read_text()) if p.exists() else None


print("median vr = %.4f" % MED)
rows = []
for r in GAP:
    ks = kc(r["code"])
    if not ks:
        continue
    dts = [k["date"] for k in ks]
    s, e = r["signal"], r["entry"]
    if s not in dts or e not in dts:
        continue
    j, i = dts.index(s), dts.index(e)
    if j < 5:
        continue
    den5 = sum(k["volume"] for k in ks[j - 5:j]) / 5
    vup = ks[i]["volume"] / den5 if den5 > 0 else None
    pc = ks[j]["close"]
    gap_pct = (ks[i]["open"] / pc - 1) if pc > 0 else None
    m = meta.get((r["code"], e), {})
    rows.append({"code": r["code"], "signal": s, "entry": e, "ret5": r["ret5"],
                 "vr_upper": vup, "gap_known": m.get("gap"), "gap_calc": gap_pct})

up = [x["vr_upper"] for x in rows if x["vr_upper"] is not None]
print("gap events with vr_upper: %d / %d" % (len(up), len(rows)))
below = [x for x in up if x < MED]
print("vr_upper < median : %d  (these MUST be in the low group)" % len(below))
print("vr_upper >= median: %d  (ambiguous: could be either side)" % (len(up) - len(below)))
if up:
    print("vr_upper stats: min=%.4f p25=%.4f med=%.4f p75=%.4f max=%.4f"
          % (min(up), st.quantiles(up, n=4)[0], st.median(up), st.quantiles(up, n=4)[2], max(up)))

# consequence: the forced-low subset is known; the ambiguous remainder is swept
forced = [x for x in rows if x["vr_upper"] is not None and x["vr_upper"] < MED]
amb = [x for x in rows if x["vr_upper"] is not None and x["vr_upper"] >= MED]
kv = [r for r in CUR["events"] if r.get("vr") is not None]
hi = [r for r in kv if r["vr"] > MED]
lo = [r for r in kv if r["vr"] <= MED]
print("\nknown high n=%d %.2f%% | known low n=%d %.2f%%"
      % (len(hi), 100 * st.mean([r["ret5"] for r in hi]),
         len(lo), 100 * st.mean([r["ret5"] for r in lo])))
for tag, extra in [("+forced-low only", forced), ("+all gap -> low (block)", rows)]:
    mh = st.mean([r["ret5"] for r in hi])
    ml = (sum(r["ret5"] for r in lo) + sum(r["ret5"] for r in extra)) / (len(lo) + len(extra))
    print("  %-24s high %.2f%% vs low %.2f%% => %+.2fpp" % (tag, 100 * mh, 100 * ml, 100 * (mh - ml)))

# worst case restricted to admissible: ambiguous ones may go high, forced ones cannot
best = None
for g in range(0, len(amb) + 1):
    # choose the g lowest-return ambiguous events to go high (adversarial)
    amb_sorted = sorted(amb, key=lambda x: x["ret5"])
    h = hi + amb_sorted[:g]
    l = lo + forced + amb_sorted[g:]
    if not h or not l:
        continue
    # median constraint: |high| <= N/2 with N = 101 + 27
    if len(h) > (len(kv) + len(rows)) // 2:
        continue
    d = st.mean([r["ret5"] for r in h]) - st.mean([r["ret5"] for r in l])
    if best is None or d < best[0]:
        best = (d, g, len(h), len(l))
print("\n=== constrained adversarial (forced-low respected) ===")
print("  min(high-low) = %+.2fpp  at g=%d (high n=%d, low n=%d) -> %s"
      % (100 * best[0], best[1], best[2], best[3],
         "HOLDS" if best[0] > 0 else "CAN FLIP"))

out = {"_meta": {"card": "t_2bcb8552", "kind": "gap_vr_upper_bound",
                 "method": "vr_upper = vol[entry_day] / mean(vol[T-5..T-1]) ; 竞价量 <= 全日量",
                 "median_vr": MED, "gap_events": len(rows),
                 "n_vr_upper_below_median": len(below),
                 "n_vr_upper_ambiguous": len(up) - len(below)},
       "vr_upper_stats": {"min": round(min(up), 4), "median": round(st.median(up), 4),
                          "max": round(max(up), 4)} if up else None,
       "block_gap_to_low_diff_pp": round(100 * (st.mean([r["ret5"] for r in hi]) -
                                                (sum(r["ret5"] for r in lo) + sum(r["ret5"] for r in rows)) /
                                                (len(lo) + len(rows))), 2),
       "constrained_adversarial_min_diff_pp": round(100 * best[0], 2),
       "constrained_claim_holds": bool(best[0] > 0),
       "rows": rows}
p = ROOT / "data" / "auction_deep_strength_gapbound_vr_20261016.json"
p.write_text(json.dumps(out, ensure_ascii=False, indent=1))
print("-> %s" % p)
