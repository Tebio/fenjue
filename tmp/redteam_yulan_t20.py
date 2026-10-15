#!/usr/bin/env python3
# 红队聚焦验证（评审卡 t_cb4b33fd）：玉兰路买入事件 T+20 的日历时间归属
# 问题：AGENTS #275 记「玉兰路上榜=最强出货信号 T20 -9.19pp 双向对称」，但研究只给了 T5 的日历 t_NW(-1.0)。
# 本脚本补 T+20 日历时间 NW t + 抱团日集中度（前 3 日贡献占比），判定该反向信号是否稳健。
import json, math, statistics as st, sys
from collections import defaultdict
sys.path.insert(0, "/opt/data/fenjue/engine")
import law_pipeline as lp
import lhb_follow_study as L

def main():
    seat_rows, org_rows, all_rows, days = L.collect_events()
    yl = [r for r in seat_rows if r["seat"] == "玉兰路" and (r["net_wan"] or 0) > 0]
    print(f"玉兰路买入事件(净买>0): {len(yl)} 起, 窗口 {L.WIN_START}..{L.WIN_END}", flush=True)

    stocks = lp.load_universe()
    idx = L.build_index(stocks)
    uni_mean = L.universe_daily_mean(stocks)

    # 主板过滤与事件前向收益
    ev_by_date = defaultdict(list)
    skipped = 0
    for r in yl:
        d = stocks.get(r["code"])
        if not d:
            skipped += 1; continue
        i = idx[r["code"]].get(r["date"])
        if i is None or i < 65:
            skipped += 1; continue
        fr = L.fwd_returns(d, i)
        if not fr or fr[20] is None:
            skipped += 1; continue
        ed = d["date"][i + 1]
        ev_by_date[ed].append(fr[20])
    print(f"可测事件 {sum(len(v) for v in ev_by_date.values())}，跳过 {skipped}（创业板/科创/北交所或窗口尾）", flush=True)

    # 全事件池级
    allr = [x for v in ev_by_date.values() for x in v]
    print(f"池级 T+20: n={len(allr)} mean={100*st.mean(allr):+.2f}% win={100*sum(1 for x in allr if x>0)/len(allr):.1f}%")

    # 日历时间组合 NW t（市场均值口径，比 C2 宽但正是「抱团日归属」要测的）
    res = L.day_cluster_t(ev_by_date, uni_mean[20], 20)
    print("日历时间(超额=事件日组合-全宇宙):", json.dumps(res, ensure_ascii=False))

    # 抱团日集中度：每日超额贡献
    series = {d: st.mean(v) - uni_mean[20][d] for d, v in ev_by_date.items() if d in uni_mean[20]}
    tot = sum(series.values())
    srt = sorted(series.items(), key=lambda kv: kv[1])  # 最负在前
    print(f"事件日数 {len(series)}，总超额 {100*tot:+.1f}pp")
    neg = [x for x in srt if x[1] < 0]
    print(f"负贡献日 {len(neg)}/{len(series)}")
    top3 = srt[:3]
    print("最毒 3 日:", [(d, f"{100*v:+.1f}pp", len(ev_by_date[d])) for d, v in top3])
    if tot < 0:
        share = sum(v for _, v in top3) / tot
        print(f"最毒3日占总负贡献比: {100*share:.0f}%")
    # H1/H2 分段
    h1 = [v for d, v in series.items() if d < L.MID]; h2 = [v for d, v in series.items() if d >= L.MID]
    print(f"H1(<{L.MID}): 天数{len(h1)} 日均{100*st.mean(h1):+.2f}pp | H2: 天数{len(h2)} 日均{100*st.mean(h2):+.2f}pp")

if __name__ == "__main__":
    main()
