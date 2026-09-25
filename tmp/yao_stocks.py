"""妖股样本研究（2026-09-25，用户 Q2：金螳螂/百合花/金健米业——为什么是它们）。

定义：妖股 = 20 个交易日内涨幅 ≥80% 且含 ≥4 个涨停；对照 = 同期首板但 20 日涨幅 <30%。
特征（首板前一日可知）：流通市值(cap_hist)、股价、前 20 日涨幅、MA60 位置、
距 250 日高点、量比（首板日量/前 20 日均量）、前期横盘天数。
对照组与妖股组同 regime 同月份抽样（1:3），比较特征分布。
"""
import collections
import json
import statistics as st
import sys

sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp

ROOT = "/opt/data/fenjue"
stocks = lp.load_universe()

def is_lu(c, c_prev):
    return c_prev > 0 and c / c_prev - 1 >= 0.098

cases = {"002081": "金螳螂", "603823": "百合花", "600127": "金健米业"}
# ① 点名三只的妖段解剖
print("═══ 点名票妖段解剖 ═══")
for code, nm in cases.items():
    d = stocks.get(code)
    if not d:
        continue
    n = d["n"]
    for i in range(260, n - 20):
        # 妖段：未来 20 日涨幅 ≥80% 且含 ≥4 涨停，且当日为启动点（前 5 日无涨停）
        fwd = d["c"][i + 20] / d["c"][i] - 1
        lu_n = sum(1 for j in range(i, i + 21) if is_lu(d["c"][j], d["c"][j - 1]))
        prior_lu = any(is_lu(d["c"][j], d["c"][j - 1]) for j in range(i - 5, i))
        if fwd >= 0.8 and lu_n >= 4 and not prior_lu:
            cap = None
            try:
                cap_h = json.load(open(f"{ROOT}/data/cap_hist/{code}.json"))
                cap = next((x.get("cap") for x in reversed(cap_h) if x.get("date", "") <= d["date"][i]), None)
            except Exception:
                pass
            print(f"{nm}({code}) 启动日 {d['date'][i]}: 收 {d['c'][i]:.2f} 流通市值 {cap and round(cap/1e8, 1)}亿 "
                  f"前20日 {d['c'][i]/d['c'][i-20]-1:+.1%} MA60位置 {d['c'][i]/d['ma60'][i]-1:+.1%} "
                  f"距250日高 {d['c'][i]/max(d['c'][i-250:i])-1:+.1%} 后20日 {fwd:+.0%} 含{lu_n}板")
            break  # 每只取第一个妖段

# ② 全样本：妖段组 vs 对照组
yao, ctrl = [], []
for code, d in stocks.items():
    if code[:2] not in ("60", "00"):
        continue
    n = d["n"]
    for i in range(280, n - 21):
        c = d["c"]
        if c[i - 1] <= 0:
            continue
        lu_today = is_lu(c[i], c[i - 1])
        prior_lu = any(is_lu(c[j], c[j - 1]) for j in range(i - 10, i))
        if not lu_today or prior_lu:
            continue
        fwd20 = c[i + 20] / c[i] - 1
        lu_n = sum(1 for j in range(i, i + 21) if is_lu(c[j], c[j - 1]))
        feat = {
            "code": code, "date": d["date"][i],
            "price": c[i],
            "prior20": c[i] / c[i - 20] - 1,
            "ma60_pos": c[i] / d["ma60"][i] - 1 if d["ma60"][i] else 0,
            "dist_high250": c[i] / max(c[i - 250:i]) - 1,
            "vol_ratio": d["v"][i] / (st.mean(d["v"][i - 20:i]) or 1),
        }
        if fwd20 >= 0.8 and lu_n >= 4:
            yao.append(feat)
        elif fwd20 < 0.3:
            ctrl.append(feat)
print(f"\n妖段组 {len(yao)}，对照组 {len(ctrl)}")

def cmp(key, lb):
    ya = sorted(r[key] for r in yao)
    ct = sorted(r[key] for r in ctrl)
    if not ya or not ct:
        return
    mid = lambda x: x[len(x)//2]
    print(f"  {lb:<14} 妖股中位 {mid(ya):>8.2f} vs 对照中位 {mid(ct):>8.2f}")

print("\n═══ 妖股 vs 对照（特征中位数） ═══")
cmp("price", "股价")
cmp("prior20", "前20日涨幅")
cmp("ma60_pos", "MA60位置")
cmp("dist_high250", "距250日高点")
cmp("vol_ratio", "首板量比")

for key, cuts in (("price", (3, 5, 10, 20)), ("vol_ratio", (1.5, 2, 3, 5)), ("prior20", (-0.1, 0, 0.1, 0.3))):
    print(f"\n{key} 分层的妖股率:")
    allr = sorted(yao + ctrl, key=lambda r: r[key])
    n = len(allr)
    lo = float("-inf")
    for cut in list(cuts) + [float("inf")]:
        seg = [r for r in allr if lo <= r[key] < cut]
        if len(seg) >= 30:
            rate = sum(1 for r in seg if r in yao) / len(seg)
            print(f"  [{lo:.1f},{cut:.1f}): n={len(seg)} 妖股率 {rate*100:.1f}%")
        lo = cut

json.dump({"yao": yao, "ctrl_sample": ctrl[:3000]}, open(f"{ROOT}/data/yao_stocks_20260925.json", "w"), ensure_ascii=False)
print("\nsaved data/yao_stocks_20260925.json")
