"""妖段段龄派生器（2026-09-25，「基于现状改进」落地①）。

从 data/regime_timeline_hcap.json 派生「当日 regime + 段内第几天」，
落盘 data/regime_age.json 供作战单/门距/面板读取。
证据（tmp/age_gate_test.py，9270 事件）：妖股期首板信号 段龄1-2 T5 43.7%/+0.39%
vs 发酵期3-5 T5 34.2%/-1.59% vs 退潮6+ T5 36.0%/-0.68%，三段同向。
段龄≥3 的妖股期信号应降权。
"""
import json
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
tl = json.loads((ROOT / "data/regime_timeline_hcap.json").read_text())

cur_r, age = None, 0
ages = {}
for x in tl:
    if x["regime"] != cur_r:
        cur_r, age = x["regime"], 1
    else:
        age += 1
    ages[x["date"]] = {"regime": cur_r, "age": age}

latest = tl[-1]["date"]
out = {"latest": latest, "today": ages[latest], "ages": ages}
(ROOT / "data/regime_age.json").write_text(json.dumps(out, ensure_ascii=False))
t = ages[latest]
phase = "启动期" if t["age"] <= 2 else ("发酵期" if t["age"] <= 5 else "退潮期")
print(f"{latest} regime={t['regime']} 段龄第{t['age']}天（{phase}）")
