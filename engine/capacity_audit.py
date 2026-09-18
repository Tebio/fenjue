#!/usr/bin/env python3
"""G7 容量重审：对注册表全部主张跑「槽位10 资金曲线」，2026-09-18 立
用法：python3 engine/capacity_audit.py [--slots 10] [--seeds 3]
输出：data/capacity_audit_YYYYMMDD.jsonl（逐条落盘，可断点续跑）+ stdout 表
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp  # noqa: E402
import yaml  # noqa: E402

ROOT = "/opt/data/fenjue"
ap = argparse.ArgumentParser()
ap.add_argument("--slots", type=int, default=10)
ap.add_argument("--seeds", type=int, default=3)
ap.add_argument("--k", type=int, default=5)
args = ap.parse_args()

today = (datetime.now(timezone.utc) + timedelta(hours=8)).date().isoformat().replace("-", "")
OUT = f"{ROOT}/data/capacity_audit_{today}.jsonl"
done = set()
if os.path.exists(OUT):
    for line in open(OUT, encoding="utf-8"):
        try:
            done.add(json.loads(line)["id"])
        except Exception:
            pass
print("已完成:", len(done), flush=True)

reg = yaml.safe_load(open(f"{ROOT}/data/claims_registry.yaml", encoding="utf-8"))
claims = [c for c in reg["claims"] if c.get("detector") in lp.REGISTRY]
skip = [c["id"] for c in reg["claims"] if c.get("detector") not in lp.REGISTRY]
print(f"可测主张 {len(claims)} 条；跳过（external/缺 detector）：{skip}", flush=True)

stocks = lp.load_universe()
lp.build_xsection(stocks)
print("universe:", len(stocks), flush=True)

rows = []
for c in claims:
    if c["id"] in done:
        continue
    det = c["detector"]
    fn = lp.REGISTRY[det]
    sigs = lp._collect_sigs(fn, stocks)
    n_sig = sum(len(v) for v in sigs.values())
    cap1 = lp.capacity_sim(sigs, stocks, slots=args.slots, seeds=args.seeds, cluster_k=1)
    capk = lp.capacity_sim(sigs, stocks, slots=args.slots, seeds=args.seeds, cluster_k=args.k)
    rec = {"id": c["id"], "detector": det, "n_signal": n_sig,
           "pos_direction": c.get("pos_direction"), "entry": c.get("entry", "next_open"),
           "槽10_K1": cap1, f"槽10_K{args.k}": capk,
           "G7": bool(cap1 and cap1["年化%"] > 0),
           "G7_K": bool(capk and capk["年化%"] > 0)}
    with open(OUT, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    rows.append(rec)
    print(f"  {c['id']:28s} {det:20s} 信号{n_sig:7d} "
          f"K1 年化{(cap1 or {}).get('年化%', 0):+7.2f}% 回撤{(cap1 or {}).get('回撤%', 0):+7.1f}% 笔{(cap1 or {}).get('笔数', 0):6.0f} "
          f"| K{args.k} 年化{(capk or {}).get('年化%', 0):+7.2f}% 回撤{(capk or {}).get('回撤%', 0):+7.1f}% "
          f"→ G7 {'✅' if rec['G7'] else '❌'}{'/✅K' if rec['G7_K'] else ''}", flush=True)

# 汇总（含历史）
allrec = [json.loads(l) for l in open(OUT, encoding="utf-8")] if os.path.exists(OUT) else []
print("\n=== G7 汇总 ===")
passk1 = [r for r in allrec if r["G7"]]
passk = [r for r in allrec if r["G7_K"]]
print(f"  原始规则过 G7：{len(passk1)}/{len(allrec)}")
print(f"  成簇日过滤(K)后过 G7：{len(passk)}/{len(allrec)}")
for r in sorted(allrec, key=lambda x: -((x.get('槽10_K1') or {}).get('年化%', -99))):
    k1 = (r.get("槽10_K1") or {}).get("年化%", 0)
    kk = (r.get(f"槽10_K{args.k}") or {}).get("年化%", 0)
    print(f"  {r['id']:28s} K1 {k1:+7.2f}%  K{args.k} {kk:+7.2f}%")
print("\nsaved", OUT)
