#!/usr/bin/env python3
"""engine/regime_daily_append.py — regime 权威时间轴日更（2026-09-20 立）。

起因（脏数据实锤）：a-stock MCP get_main_board_pool 退化（limit=5000 只回 233 行），
周期仪 15:40 直播路径本周涨停数全错（9/17 报 17 vs 官方 47；9/18 报 28 vs 官方 77），
regime_log 徽标（平淡期）与 hcap 闸门时间轴（妖股期）同一天的标签打架。
而 hcap 时间轴此前无人日更（#28 已烂过一次）。

设计：每交易日 18:35（kcache 增量刷新后）从 big_kcache + cap_hist 离线全量重算当日
分类（规则与 regime_backtest_hcap/regime_meter 完全一致），幂等 upsert 进
  1. data/regime_timeline_hcap.json（闸门/G3 权威源）
  2. data/regime_log.jsonl（面板徽标源，覆盖同日 meter 直播条目，标 corrected）
meter 的 15:40 直播保留为盘中参考，当日权威值以本脚本为准。

用法：python regime_daily_append.py [YYYY-MM-DD]   # 默认=指数最新交易日；可补历史日
"""
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from regime_backtest_hcap import cap_at, load_sectors   # 复用 PIT 市值与行业映射（铁律：抄现成）

ROOT = Path("/opt/data/fenjue")
KCACHE = ROOT / "data" / "big_kcache"
TIMELINE = ROOT / "data" / "regime_timeline_hcap.json"
RLOG = ROOT / "data" / "regime_log.jsonl"


def day_stats(day: str) -> dict | None:
    """离线全量计算某日分类输入。当日零涨停返回 None（与全量重建同语义：跳过零板日）。"""
    boards, downs = [], []
    names = {}
    nf = ROOT / "data/main_board_codes.json"
    if nf.exists():
        names = {str(s["code"]).zfill(6): s.get("name", "")
                 for s in json.loads(nf.read_text()).get("stocks", [])}
    for f in sorted(KCACHE.glob("*.json")):
        if f.stem == "000001":
            continue
        try:
            ks = json.loads(f.read_text())
        except Exception:
            continue
        if len(ks) < 2 or ks[-1]["date"] > day:
            # 历史补跑：需定位当日 bar
            pass
        # 找当日 bar（末 bar 快路径 + 日期索引慢路径）
        j = len(ks) - 1 if ks and ks[-1]["date"] == day else next(
            (k for k in range(len(ks) - 1, -1, -1) if ks[k]["date"] == day), None)
        if j is None or j < 1:
            continue
        pc, tc = float(ks[j - 1]["close"]), float(ks[j]["close"])
        if pc <= 0:
            continue
        pct = (tc - pc) / pc * 100
        if pct >= 9.8:
            boards.append({"code": f.stem, "name": names.get(f.stem, ""),
                           "cap": cap_at(f.stem, day) or 0, "pct": round(pct, 2)})
        elif pct <= -9.8:
            downs.append(f.stem)
    if not boards and not downs:
        return None
    n = len(boards)
    if n == 0:
        # 零板日：与重建语义一致跳过（重建 timeline 只含 day_boards 键）
        return None
    small = sum(1 for b in boards if (b["cap"] or 999) < 100)
    small_ratio = small / n

    def chain(sec):
        if any(k in sec for k in ("计算机", "通信", "电子", "光学", "元件", "半导体", "消费电子", "软件")):
            return "AI电子链"
        return sec

    sectors = load_sectors()
    secs = Counter(chain(sectors.get(b["code"], "其他")) for b in boards)
    known = {k: v for k, v in secs.items() if k != "其他"}
    conc = max(known.values()) / n if known else 0
    idx = json.loads((ROOT / "data/index_sh000001.json").read_text())
    ip = 0.0
    for i in range(1, len(idx)):
        if idx[i]["date"] == day and float(idx[i - 1]["close"]) > 0:
            ip = (float(idx[i]["close"]) / float(idx[i - 1]["close"]) - 1) * 100
            break
    nd = len(downs)
    if n >= 60 and conc >= 0.22:
        regime = "主线期"
    elif n >= 40 and small_ratio >= 0.65 and conc < 0.22:
        regime = "妖股期"
    elif nd >= 20 or (n < 30 and ip < -1.0):
        regime = "恐慌期"
    else:
        regime = "平淡期"
    return {"date": day, "regime": regime, "boards_n": n, "downs": nd,
            "small%": round(small_ratio, 2), "conc": round(conc, 2), "idx": round(ip, 2),
            "boards": boards, "top_sectors": secs.most_common(5)}


def upsert_timeline(entry: dict) -> str:
    tl = json.loads(TIMELINE.read_text())
    rec = {"date": entry["date"], "regime": entry["regime"], "boards": entry["boards_n"],
           "downs": entry["downs"], "small%": entry["small%"], "conc": entry["conc"],
           "idx": entry["idx"]}
    old = next((t for t in tl if t["date"] == entry["date"]), None)
    action = "unchanged"
    if old:
        if old.get("regime") != rec["regime"] or old.get("boards") != rec["boards"]:
            old.update(rec)
            action = f"corrected {old.get('regime')}→{rec['regime']}"
    else:
        tl.append(rec)
        tl.sort(key=lambda t: t["date"])
        action = "appended"
    TIMELINE.write_text(json.dumps(tl, ensure_ascii=False, indent=2))
    return action


def upsert_log(entry: dict) -> str:
    lines = [json.loads(x) for x in RLOG.read_text().splitlines() if x.strip()]
    rec = {"date": entry["date"], "regime": entry["regime"],
           "stats": {"limit_ups": entry["boards_n"], "limit_downs": entry["downs"],
                     "small_cap_board_ratio": entry["small%"],
                     "top_sector_concentration": entry["conc"], "index_pct": entry["idx"],
                     "top_sectors": entry["top_sectors"]},
           "boards": entry["boards"],
           "source": "regime_daily_append(kcache离线全量)", "corrected": True}
    action = "appended"
    for i, r in enumerate(lines):
        if r.get("date") == entry["date"]:
            old_regime = r.get("regime")
            lines[i] = rec
            action = f"corrected {old_regime}→{rec['regime']}" if old_regime != rec["regime"] else "refreshed"
            break
    else:
        lines.append(rec)
    RLOG.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in lines) + "\n")
    return action


def coverage(day: str) -> float:
    """big_kcache 中当日 bar 覆盖率（2026-09-21 实锤：baostock 断链只更了 328/3377，
    下游把 10 涨停当全天 → 垃圾 regime。低于 80% 拒绝写盘——实盘完整覆盖天花板≈91%
    （186 退市+停牌）。哨兵阈值防半更新/断链）。"""
    tot = hit = 0
    for f in KCACHE.glob("*.json"):
        if f.stem == "000001":
            continue
        tot += 1
        try:
            ks = json.loads(f.read_text())
            if ks and ks[-1]["date"] == day:
                hit += 1
        except Exception:
            pass
    return hit / tot if tot else 0.0


def _intended_day() -> str:
    """目标判定日=最近已收盘的交易日（2026-09-22 事故：kcache 1h 超时被杀在 90%，
    19:35/19:45 下游 cron 拿日历尾 9/21 比对→95% 票已更到 9/22→闸误判 5% 覆盖率拒判。
    日历要等 kcache 收尾 update_index 才含今天（鸡生蛋），所以：
    今天是工作日且已收盘且日历未含今天 → 看今天覆盖率：够=今天（交易日），
    不够但昨天够且相隔≤4天=假日回退昨天；都不够=今天（让闸报错）。"""
    from datetime import date as _date, datetime, timedelta, timezone
    bjt = datetime.now(timezone.utc) + timedelta(hours=8)
    today = bjt.date().isoformat()
    idx = json.loads((ROOT / "data/index_sh000001.json").read_text())
    last = idx[-1]["date"]
    if today <= last:
        return last
    if bjt.weekday() >= 5 or bjt.hour < 16:
        return last
    if coverage(today) >= 0.8:
        return today
    gap = (_date.fromisoformat(today) - _date.fromisoformat(last)).days
    if coverage(last) >= 0.8 and gap <= 4:
        return last  # 假日
    return today  # 交易日但数据不全 → 闸会报


def main():
    if len(sys.argv) > 1:
        days = sys.argv[1:]
    else:
        days = [_intended_day()]
    for day in days:
        cov = coverage(day)
        if cov < 0.8:
            print(f"🚨 {day}: big_kcache 覆盖率仅 {cov:.0%}（<80%），数据不全拒绝落盘——kcache 可能断链/被超时截断，速查")
            sys.exit(1)
        st = day_stats(day)
        if st is None:
            print(f"{day}: 零板日/无数据，与重建语义一致跳过")
            continue
        a1 = upsert_timeline(st)
        a2 = upsert_log(st)
        print(f"{day}: {st['regime']} | 涨停{st['boards_n']} 跌停{st['downs']} "
              f"小市值{st['small%']:.0%} 链集中{st['conc']:.2f} 指数{st['idx']:+.2f}% "
              f"| timeline:{a1} log:{a2}")


if __name__ == "__main__":
    main()