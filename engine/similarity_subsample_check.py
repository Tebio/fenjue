#!/usr/bin/env python3
"""学习集 1/4 抽样的近似无损验证：方向 A 的 10 万行测试子样本上，
全量学习集 vs 1/4 抽样学习集的 pred5 相关性。corr>0.99 = 近似无损。"""
import sys, bisect
import numpy as np

sys.path.insert(0, "/opt/data/fenjue/engine")
import similarity_engine as se

z = np.load(se.FEAT_NPZ)
F, R, didx = z["F"], z["R"], z["didx"]
cal = z["calendar"].tolist()
sp = bisect.bisect_left(cal, "2023-01-01")
li_full = np.where(didx < sp)[0]
ti = np.where(didx >= sp)[0]
rng = np.random.default_rng(11)
ti_sub = np.sort(rng.choice(ti, 100000, replace=False))

Xl_f, Xt = se._standardize(F[li_full, :se.NCONT], F[ti_sub, :se.NCONT])
Xl_f = np.concatenate([Xl_f, F[li_full, se.NCONT:]], 1)
Xt = np.concatenate([Xt, F[ti_sub, se.NCONT:]], 1)
li_q = li_full[::4]
Xl_q, _ = se._standardize(F[li_q, :se.NCONT], F[ti_sub[:2], :se.NCONT])
Xl_q = np.concatenate([Xl_q, F[li_q, se.NCONT:]], 1)

print("全量学习集预测…", flush=True)
p_full = se._knn_predict(Xl_f, R[li_full], Xt)
print("1/4 学习集预测…", flush=True)
p_quart = se._knn_predict(Xl_q, R[li_q], Xt)
m = np.isfinite(p_full[:, 1]) & np.isfinite(p_quart[:, 1])
c = np.corrcoef(p_full[m, 1], p_quart[m, 1])[0, 1]
print(f"pred5 全量 vs 1/4 抽样: corr={c:.4f} (n={m.sum()})")
base = se._stats(R[ti_sub, 1])
t_full = se._decile_table(p_full[:, 1], R[ti_sub, 1], base["mean%"])
t_quart = se._decile_table(p_quart[:, 1], R[ti_sub, 1], base["mean%"])
print("全量 top-bottom:", t_full["top-bottom_pp"], "单调", t_full["单调步数(9为全单调)"])
print("1/4  top-bottom:", t_quart["top-bottom_pp"], "单调", t_quart["单调步数(9为全单调)"])
