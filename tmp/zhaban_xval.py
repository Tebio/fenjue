"""炸板重建交叉验证（2026-09-22）：我日K自建判定 vs 东财真实炸板池 15 天。

我方判定：high ≥ round(昨收×1.10,2) 且 收盘 < 涨停价 且非一字锁死（低<涨停）。
东财 CSV：日期+代码 为实际炸板名单。
逐日比：交集率（对我方/对东财）、漏网（东财有我无）、误报（我有东财无）逐日清单。
"""
import csv
import json
import sys

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

ROOT = "/opt/data/fenjue"
stocks = lp.load_universe()
names = {str(s["code"]).zfill(6): s.get("name", "")
         for s in json.loads(open(f"{ROOT}/data/main_board_codes.json").read())["stocks"]}

zb = list(csv.DictReader(open("/opt/data/cache/documents/doc_b364eeff9511_zb_pool_eastmoney_20260902_20260922.csv", encoding="utf-8-sig")))
em_by_day = {}
for r in zb:
    em_by_day.setdefault(r["日期"], set()).add(r["代码"].zfill(6))
print(f"东财炸板池 {len(zb)} 行 / {len(em_by_day)} 天")

# 我方重建（限定这 15 天）
days = sorted(em_by_day)
mine_by_day = {d: set() for d in days}
for code, d in stocks.items():
    if code[:2] not in ("60", "00"):
        continue
    nm = names.get(code, "")
    if "ST" in nm or "退" in nm:
        continue
    n = d["n"]
    for i in range(60, n - 1):
        dt = d["date"][i]
        if dt not in mine_by_day:
            continue
        pc = d["c"][i - 1]
        if pc <= 0 or d["h"][i] <= 0:
            continue
        lp_px = round(pc * 1.10 + 1e-9, 2)
        if d["h"][i] >= lp_px - 1e-9 and d["c"][i] < lp_px - 1e-9 and d["l"][i] < lp_px - 1e-9:
            mine_by_day[dt].add(code)

tot_em = tot_mine = tot_inter = 0
miss_detail = []
for dt in days:
    em = em_by_day[dt]
    mine = mine_by_day[dt]
    inter = em & mine
    tot_em += len(em)
    tot_mine += len(mine)
    tot_inter += len(inter)
    miss = em - mine
    false = mine - em
    miss_detail.append({"日期": dt, "东财": len(em), "我方": len(mine), "交集": len(inter),
                        "漏网": sorted(miss), "误报": sorted(false)})
    print(f"  {dt}: 东财{len(em):>3} 我方{len(mine):>3} 交集{len(inter):>3} "
          f"对我方{len(inter)/max(len(mine),1)*100:.0f}% 对东财{len(inter)/max(len(em),1)*100:.0f}% "
          f"漏{len(miss)} 误{len(false)}")

print(f"\n═══ 总计：东财 {tot_em}，我方 {tot_mine}，交集 {tot_inter} ═══")
print(f"对我方一致率 {tot_inter/tot_mine*100:.1f}% | 对东财一致率 {tot_inter/tot_em*100:.1f}%")
all_miss = [c for d in miss_detail for c in d["漏网"]]
all_false = [c for d in miss_detail for c in d["误报"]]
print(f"漏网 TOP: {[(c, names.get(c, '')) for c in sorted(set(all_miss))[:10]]}")
print(f"误报 TOP: {[(c, names.get(c, '')) for c in sorted(set(all_false))[:10]]}")
json.dump({"逐日": miss_detail, "合计": {"东财": tot_em, "我方": tot_mine, "交集": tot_inter}},
          open(f"{ROOT}/data/zhaban_xval_20260922.json", "w"), ensure_ascii=False, indent=1)
print("saved data/zhaban_xval_20260922.json")
