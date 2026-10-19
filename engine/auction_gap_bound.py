"""Rigorous worst-case bound: can the 27 quota-blocked gap events flip #282④'s direction?

Setup
  known: 104 events (58/65 event days) -> ret1/ret5/vr/unmatched all known
  gap:    27 events (7 event days)     -> ret1/ret5 KNOWN (big_kcache); vr/unmatched UNKNOWN

Registered claims (AGENTS #282④ / #295), T+5 net of 0.15%:
  C1  {vr > median}  beats  {vr <= median}
  C2  {unmatched >= 0}  beats  {unmatched < 0}

Robustness question: does there EXIST an admissible assignment of the 27 unknown
vr / unmatched values that reverses C1 / C2?

C1 admissible set = "top-k threshold split": high must be the largest values, so
    high = (top-k known by vr)  ∪  g of the gap events,     k + g <= floor(N/2)
and the adversary may choose WHICH g gap events (=> the g lowest-return ones, to drag
high down and lift low up). The gap events' vr values are free, so any k+g <= floor(N/2)
is realisable (place g values high, 27-g low).
C2: gap signs free -> parametrise by which a gap events go to the nonneg group; the
adversary picks the a highest-return gap events for the neg group etc. Enumerate subsets
directly via sorted prefix sums.
"""
import json
import statistics as st
from itertools import combinations
from pathlib import Path
import sys

ROOT = Path("/opt/data/fenjue")
sys.path.insert(0, str(ROOT / "engine"))

CUR = json.loads((ROOT / "data" / "auction_deep_strength_20261017.json").read_text())
known = CUR["events"]
GAP = json.loads(Path("/opt/data/cache/scratch/gap_events.json").read_text())["events"]
NG = len(GAP)
kv = sorted([r for r in known if r.get("vr") is not None], key=lambda r: r["vr"])
N = len(kv) + NG
CAP = N // 2
print("known n=%d  gap n=%d  N(vr)=%d  cap|high|=%d" % (len(known), NG, N, CAP))
G5s = sorted(r["ret5"] for r in GAP)
G1s = sorted(r["ret1"] for r in GAP)
pre5 = [0.0]; pre1 = [0.0]
for x in G5s:
    pre5.append(pre5[-1] + x)
for x in G1s:
    pre1.append(pre1[-1] + x)
T5, T1 = pre5[-1], pre1[-1]


def sweep(key_hi_sums5, key_hi_sums1, key_all5, key_all1, nk):
    """Adversarial min of (high - low) over top-k splits with gap subsets."""
    b5 = b1 = None
    for k in range(0, nk + 1):
        for g in range(0, NG + 1):
            nh = k + g
            # N = 101 known + 27 gap = 128; a median split of a continuous variable puts
            # exactly N/2 = 64 values strictly above the median (ties aside).
            if nh != CAP:
                continue
            nl = nk - k + (NG - g)
            if nl == 0:
                continue
            # adversary puts the g LOWEST-return gap events into high
            mh5 = (key_hi_sums5[k] + pre5[g]) / nh
            ml5 = (key_all5 - key_hi_sums5[k] + (T5 - pre5[g])) / nl
            mh1 = (key_hi_sums1[k] + pre1[g]) / nh
            ml1 = (key_all1 - key_hi_sums1[k] + (T1 - pre1[g])) / nl
            if b5 is None or (mh5 - ml5) < b5[0]:
                b5 = (mh5 - ml5, k, g, mh5, ml5)
            if b1 is None or (mh1 - ml1) < b1[0]:
                b1 = (mh1 - ml1, k, g, mh1, ml1)
    return b5, b1


# suffix sums of the top-k known by vr
nk = len(kv)
s5 = [0.0] * (nk + 1)
s1 = [0.0] * (nk + 1)
for i in range(1, nk + 1):
    s5[i] = s5[i - 1] + kv[-i]["ret5"]
    s1[i] = s1[i - 1] + kv[-i]["ret1"]
A5, A1 = sum(r["ret5"] for r in kv), sum(r["ret1"] for r in kv)

b5, b1 = sweep(s5, s1, A5, A1, nk)
print("\n=== C1 vr (top-k threshold split, cap %d) ===" % CAP)
print("  T+5 adversarial min: k=%d known-high + g=%d gap-high => high %.2f%% (n=%d) vs low %.2f%% (n=%d) diff %+.2fpp -> %s"
      % (b5[1], b5[2], 100 * b5[3], b5[1] + b5[2], 100 * b5[4], nk - b5[1] + NG - b5[2],
         100 * b5[0], "HOLDS" if b5[0] > 0 else "CAN FLIP"))
print("  T+1 adversarial min: k=%d g=%d => high %.2f%% vs low %.2f%% diff %+.2fpp -> %s"
      % (b1[1], b1[2], 100 * b1[3], 100 * b1[4], 100 * b1[0],
         "HOLDS" if b1[0] > 0 else "CAN FLIP"))
cur_hi = [r for r in kv if r["vr"] > CUR["vr_median"]]
cur_lo = [r for r in kv if r["vr"] <= CUR["vr_median"]]
print("  sanity current split: high %.2f%% (n=%d) low %.2f%% (n=%d)"
      % (100 * st.mean([r["ret5"] for r in cur_hi]), len(cur_hi),
         100 * st.mean([r["ret5"] for r in cur_lo]), len(cur_lo)))

# ---------------- C2 unmatched: sign split, subset enumeration ----------------
uni = [r for r in known if isinstance(r["unmatched"], (int, float))]
kn = [r for r in uni if r["unmatched"] >= 0]
kg = [r for r in uni if r["unmatched"] < 0]
Sn5, Sg5 = sum(r["ret5"] for r in kn), sum(r["ret5"] for r in kg)
Sn1, Sg1 = sum(r["ret1"] for r in kn), sum(r["ret1"] for r in kg)
# adversary: put the a HIGHEST-return gap events into the neg group (lift neg, drag nonneg)
b2 = b2t1 = None
for a in range(0, NG + 1):
    # nonneg gets the (27-a) lowest-return gap events
    s_n_5 = pre5[NG - a]
    s_g_5 = T5 - pre5[NG - a]
    s_n_1 = pre1[NG - a]
    s_g_1 = T1 - pre1[NG - a]
    nh, nl = len(kn) + (NG - a), len(kg) + a
    mh5, ml5 = (Sn5 + s_n_5) / nh, (Sg5 + s_g_5) / nl
    mh1, ml1 = (Sn1 + s_n_1) / nh, (Sg1 + s_g_1) / nl
    if b2 is None or (mh5 - ml5) < b2[0]:
        b2 = (mh5 - ml5, a, mh5, ml5)
    if b2t1 is None or (mh1 - ml1) < b2t1[0]:
        b2t1 = (mh1 - ml1, a, mh1, ml1)
print("\n=== C2 unmatched (sign split; known nonneg %d / neg %d) ===" % (len(kn), len(kg)))
print("  T+5 worst (a=%d gap->neg) => nonneg %.2f%% vs neg %.2f%% diff %+.2fpp -> %s"
      % (b2[1], 100 * b2[2], 100 * b2[3], 100 * b2[0], "HOLDS" if b2[0] > 0 else "CAN FLIP"))
print("  T+1 worst (a=%d) => diff %+.2fpp -> %s"
      % (b2t1[1], 100 * b2t1[0], "HOLDS" if b2t1[0] > 0 else "CAN FLIP"))

# ---------------- C3 day-equal-weight ----------------
def dayeq(rows):
    d = {}
    for r in rows:
        d.setdefault(r["entry"], []).append(r["ret5"])
    return st.mean([st.mean(v) for v in d.values()]), len(d)


gdm, gdn = dayeq(GAP)
him, hid = dayeq(cur_hi)
lom, lod = dayeq(cur_lo)
print("\n=== C3 day-equal-weight (de-clustered) ===")
print("  known vr-high %.2f%% (%d d) | vr-low %.2f%% (%d d) | gap %.2f%% (%d d)"
      % (100 * him, hid, 100 * lom, lod, 100 * gdm, gdn))
# day-eq gap values range over the 7 day means; adversary assigns whole days
gday_vals = sorted(st.mean(v) for v in
                   {d: [r["ret5"] for r in GAP if r["entry"] == d] for d in {r["entry"] for r in GAP}}.values())
worst_hi = (him * hid + sum(gday_vals)) / (hid + gdn)     # all 7 days -> high
worst_lo = (lom * lod + sum(gday_vals)) / (lod + gdn)     # all 7 days -> low
print("  worst(all 7 gap days -> vr-high arm): %.2f%% vs %.2f%% => %+.2fpp -> %s"
      % (100 * worst_hi, 100 * lom, 100 * (worst_hi - lom), "HOLDS" if worst_hi > lom else "CAN FLIP"))
print("  worst(all 7 gap days -> vr-low  arm): %.2f%% vs %.2f%% => %+.2fpp -> %s"
      % (100 * him, 100 * worst_lo, 100 * (him - worst_lo), "HOLDS" if him > worst_lo else "CAN FLIP"))

# ---------------- C0: block assignment (realistic worst case) ----------------
# The gap events come from the same signal population, so the honest worst case is
# "every one of the 27 gap events lands on the losing side", not a tie-heavy
# degenerate split that puts a single event above the median.
blk = {}
ch = [r for r in kv if r["vr"] > CUR["vr_median"]]
cl = [r for r in kv if r["vr"] <= CUR["vr_median"]]
for tag, hi, lo in [("vr", ch, cl)]:
    mh5 = st.mean([r["ret5"] for r in hi])
    ml5 = (sum(r["ret5"] for r in lo) + T5) / (len(lo) + NG)
    mh1 = st.mean([r["ret1"] for r in hi])
    ml1 = (sum(r["ret1"] for r in lo) + T1) / (len(lo) + NG)
    blk[tag] = {"T5_diff_pp": round(100 * (mh5 - ml5), 2), "T5_high_pct": round(100 * mh5, 2),
                "T5_low_pct": round(100 * ml5, 2), "T1_diff_pp": round(100 * (mh1 - ml1), 2)}
    print("\n=== C0 vr BLOCK assignment (all 27 gap -> losing side) ===")
    print("  high %.2f%% vs low+gap %.2f%% => %+.2fpp (T+5) / %+.2fpp (T+1)"
          % (100 * mh5, 100 * ml5, 100 * (mh5 - ml5), 100 * (mh1 - ml1)))
mnn = [r for r in uni if r["unmatched"] >= 0]
mng = [r for r in uni if r["unmatched"] < 0]
b5u = st.mean([r["ret5"] for r in mnn])
b5d = (sum(r["ret5"] for r in mng) + T5) / (len(mng) + NG)
print("  unmatched: nonneg %.2f%% vs neg+gap %.2f%% => %+.2fpp"
      % (100 * b5u, 100 * b5d, 100 * (b5u - b5d)))
blk["unmatched"] = {"T5_diff_pp": round(100 * (b5u - b5d), 2),
                    "T5_nonneg_pct": round(100 * b5u, 2), "T5_neg_pct": round(100 * b5d, 2)}

out = {
    "_meta": {"card": "t_2bcb8552", "kind": "gap_robustness_bound",
              "question": "can the 27 quota-blocked gap events flip #282④'s direction?",
              "method": ("adversarial sweep over ALL admissible assignments of the 27 unknown "
                         "vr/unmatched values; each gap event's return is known from big_kcache, "
                         "so the adversary may also pick WHICH gap events land in which group"),
              "known_n": len(known), "gap_n": NG, "N_with_vr": N, "cap_high": CAP,
              "gap_days": sorted({r["entry"] for r in GAP}),
              "gap_segment_T5_pct": round(100 * T5 / NG, 2),
              "gap_segment_T5_win_pct": round(100 * sum(1 for r in GAP if r["ret5"] > 0) / NG, 1)},
    "C0_block_assignment_realistic_worst": blk,
    "C1_vr": {"T5_adversarial_min_diff_pp": round(100 * b5[0], 2),
              "T5_worst_high_pct": round(100 * b5[3], 2), "T5_worst_low_pct": round(100 * b5[4], 2),
              "T5_worst_k_known_high": b5[1], "T5_worst_g_gap_high": b5[2],
              "T1_adversarial_min_diff_pp": round(100 * b1[0], 2),
              "claim_holds_for_every_admissible_assignment": bool(b5[0] > 0 and b1[0] > 0)},
    "C2_unmatched": {"T5_adversarial_min_diff_pp": round(100 * b2[0], 2),
                     "T5_worst_nonneg_pct": round(100 * b2[2], 2),
                     "T5_worst_neg_pct": round(100 * b2[3], 2),
                     "T1_adversarial_min_diff_pp": round(100 * b2t1[0], 2),
                     "claim_holds_for_every_admissible_assignment": bool(b2[0] > 0 and b2t1[0] > 0)},
    "C3_day_eq": {"high_pct": round(100 * him, 2), "low_pct": round(100 * lom, 2),
                  "gap_pct": round(100 * gdm, 2),
                  "worst_diff_pp": round(100 * min(worst_hi - lom, him - worst_lo), 2),
                  "claim_holds": bool((worst_hi - lom) > 0 and (him - worst_lo) > 0)},
    "current_58d": {"vr_high_T5_pct": 13.31, "vr_low_T5_pct": 0.55,
                    "unmatched_nonneg_T5_pct": 12.41, "unmatched_neg_T5_pct": 3.30},
}
p_out = ROOT / "data" / "auction_deep_strength_gapbound_20261016.json"
p_out.write_text(json.dumps(out, ensure_ascii=False, indent=1))
print("\n-> %s" % p_out)
