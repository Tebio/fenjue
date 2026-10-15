#!/usr/bin/env python3
# 红队聚焦验证（评审卡 t_cb4b33fd）：协同过滤引擎 top 档 lift 的恐慌日/深档簇日归属
# 问题：#276 判「83% 顶档非注册线领土=非深档马甲」，但那是票级重叠；真正威胁是**日级**——
# lift 是否集中在少数恐慌簇日（与深档批同一天）。本脚本重建方向 A 的 top-decile 日历序列实测。
import json, bisect, sys
import numpy as np
sys.path.insert(0, "/opt/data/fenjue/engine")
import similarity_engine as S

def main():
    F, R, didx, eidx, flags, ind, day_pct, calendar = S._load_all()
    uni5 = S._prep(F, didx, ind, day_pct, eidx, R)
    sp = bisect.bisect_left(calendar, "2023-01-01")
    li = np.where(didx < sp)[0]
    ti = np.where(didx >= sp)[0]
    pred = S._grid_predict(F, R, li, ti, use_regime=True)

    r5 = R[ti, 1]
    ok = np.isfinite(r5) & np.isfinite(pred[:, 1])
    # top decile by predicted T+5
    thr = np.nanquantile(pred[ok, 1], 0.9)
    top = ok & (pred[:, 1] >= thr)
    bot = ok & (pred[:, 1] <= np.nanquantile(pred[ok, 1], 0.1))
    ed = eidx[ti]  # 入场日 index
    um = np.array([uni5.get(int(e), np.nan) for e in ed])

    # 日历序列：每日 top 档超额
    from collections import defaultdict
    day_exc = defaultdict(list)
    for k in np.where(ok)[0]:
        day_exc[int(ed[k])].append(float(r5[k] - um[k]))
    days = sorted(day_exc)
    # top 档日组合超额
    day_top = {}
    top_idx = np.where(top)[0]
    dd = defaultdict(list)
    for k in top_idx:
        dd[int(ed[k])].append(float(r5[k] - um[k]))
    for d, v in dd.items():
        day_top[d] = float(np.mean(v))
    series = np.array([day_top[d] for d in sorted(day_top)])
    print(f"方向A T+5 top10%档: 覆盖天数={len(series)} 日均超额={100*series.mean():+.3f}pp 正日占比={100*(series>0).mean():.0f}%")

    # 集中度：总超额中前 10 天贡献
    tot = series.sum()
    srt = np.sort(series)[::-1]
    print(f"总超额={100*tot:+.1f}pp；前10日贡献={100*srt[:10].sum():+.1f}pp ({100*srt[:10].sum()/tot:.0f}%)" if tot > 0 else f"总超额={100*tot:+.1f}pp")
    print(f"前5%天数({max(1,len(srt)//20)}日)贡献占比={100*srt[:max(1,len(srt)//20)].sum()/tot:.0f}%" if tot>0 else "")

    # 深档批日重叠（批信号日→入场=次一交易日）
    batches = [b["date"] for b in json.load(open("/opt/data/fenjue/data/deep_batches_full_20260927.json"))]
    bset = set()
    for bd in batches:
        i = bisect.bisect_right(calendar, bd)
        if i < len(calendar):
            bset.add(i)  # 入场日 idx
    bset = {d for d in bset if d >= sp}
    in_days = [d for d in sorted(day_top) if d in bset]
    out_days = [d for d in sorted(day_top) if d not in bset]
    # top档事件落在深档批入场日的行数占比
    top_ed = ed[top_idx]
    inb = np.isin(top_ed, list(bset))
    print(f"深档批入场日(23-26段, {len(bset)} 个): top档行数占比={100*inb.mean():.1f}%")
    if in_days and out_days:
        a = np.array([day_top[d] for d in in_days]); b = np.array([day_top[d] for d in out_days])
        print(f"深档批日 top档日超额: n={len(a)} mean={100*a.mean():+.3f}pp | 非批日: n={len(b)} mean={100*b.mean():+.3f}pp")
        print(f"批日贡献占总超额: {100*a.sum()/tot:.0f}%" if tot > 0 else "")
    # bottom 档（引擎识别「别碰」）校验
    bot_idx = np.where(bot)[0]
    ddb = defaultdict(list)
    for k in bot_idx:
        ddb[int(ed[k])].append(float(r5[k] - um[k]))
    sb = np.array([np.mean(v) for v in ddb.values()])
    print(f"bottom10%档: 天数={len(sb)} 日均超额={100*sb.mean():+.3f}pp（应<0 才算真识别）")

if __name__ == "__main__":
    main()
