"""云峰喊单对账（2026-09-22）：每个持仓回合的真实价格路径。

回合表 = 手工从帖子时间轴整理（yunfeng_events.json），字段：
  code, name, in_date（首次提及/买入帖）, out_date（离场帖，无则=None）, note（他自己宣称的盈亏）
口径：
  他本人≈in_date 当日收盘（帖子多在盘中，无法精确到分钟，收盘近似）
  粉丝跟单=in_date 次日开盘（盘后看到帖子的最早可执行点）
  出场=out_date 当日收盘（若宣称当日出局）或窗口末
  另报：入场后 20 日内最大涨幅（max_gain）、最大回撤（max_dd）
"""
import json
import sys

EPISODES = [
    ("002490", "山东墨龙", "2026-03-06", None, "盘前喊「牛已放出」"),
    ("002498", "汉缆股份", "2026-03-06", None, "同日第二只"),
    ("002298", "中电鑫龙", "2026-03-11", None, ""),
    ("002261", "拓维信息", "2026-03-11", None, ""),
    ("002335", "科华数据", "2026-03-11", None, ""),
    ("002015", "协鑫能科", "2026-03-12", None, ""),
    ("000890", "法尔胜", "2026-03-17", None, "满仓99%"),
    ("601016", "节能风电", "2026-03-24", "2026-03-26", "自称拿下20%"),
    ("002413", "雷科防务", "2026-03-26", None, ""),
    ("603601", "再升科技", "2026-03-30", "2026-04-22", "首吃两板后反复"),
    ("000070", "特发信息", "2026-04-02", None, "满仓，自称浮盈4万+"),
    ("600488", "津药药业", "2026-04-07", None, ""),
    ("002565", "顺灏股份", "2026-04-07", "2026-04-10", "自称快吃上10厘米"),
    ("002342", "巨力索具", "2026-04-10", None, ""),
    ("002364", "中恒电气", "2026-04-14", None, ""),
    ("002580", "圣阳股份", "2026-04-15", "2026-04-24", "龙头切换卡位，低吸吃肉"),
    ("002361", "神剑股份", "2026-04-16", None, ""),
    ("600330", "天通股份", "2026-04-28", "2026-04-29", "自称挑战首次亏损"),
    ("002297", "博云新材", "2026-04-29", "2026-04-30", "高开赚钱落袋"),
    ("600487", "亨通光电", "2026-05-07", None, ""),
    ("600198", "大唐电信", "2026-05-11", "2026-05-12", "自称+9%后二板炸板落袋"),
    ("000066", "中国长城", "2026-05-15", "2026-05-26", "自称亏~20%（挑战以来最大）"),
    ("000725", "京东方A", "2026-05-25", None, "长城调仓过来"),
    ("002579", "中京电子", "2026-05-28", None, "自称吃肉回血"),
    ("001696", "宗申动力", "2026-06-15", "2026-06-16", "水下低吸次日兑现（帖写昨天低吸）"),
    ("600110", "诺德股份", "2026-06-16", "2026-07-17", "7/17自称亏几十个点留底仓"),
]

KC = "/opt/data/fenjue/data/big_kcache"


def load(code):
    try:
        ks = json.load(open(f"{KC}/{code}.json"))
        return {k["date"]: k for k in ks}, [k["date"] for k in ks]
    except Exception:
        return {}, []


def next_day(dates, d):
    for x in dates:
        if x > d:
            return x
    return None


def day_or_next(dates, d):
    for x in dates:
        if x >= d:
            return x
    return None


print(f"{'票':<8}{'入场':<12}{'出场':<12}{'他口径%':>8}{'粉丝口径%':>9}{'20日max%':>9}{'20日min%':>9}  备注")
rows = []
for code, name, d_in, d_out, note in EPISODES:
    ks, dates = load(code)
    if not ks:
        print(f"{name} 无kcache"); continue
    di = day_or_next(dates, d_in)
    if not di:
        continue
    # 他口径：入场日收盘 → 出场日收盘（无出场帖则窗口+20日末）
    do = day_or_next(dates, d_out) if d_out else None
    i0 = dates.index(di)
    win_end = dates[min(i0 + 20, len(dates) - 1)]
    # 出场日确定：out 帖当日收盘；无则窗口末
    de = do if do else win_end
    his = ks[de]["close"] / ks[di]["close"] - 1
    # 粉丝口径：次日开盘 → 出场日收盘
    dn = next_day(dates, di)
    fol = (ks[de]["close"] / ks[dn]["open"] - 1) if dn and dn <= de else None
    seg = [k for k in dates[i0: min(i0 + 21, len(dates))]]
    mx = max(ks[d]["high"] for d in seg) / ks[di]["close"] - 1
    mn = min(ks[d]["low"] for d in seg) / ks[di]["close"] - 1
    rows.append({"code": code, "name": name, "in": di, "out": de, "his": his,
                 "follower": fol, "max_gain": mx, "max_dd": mn, "note": note})
    print(f"{name:<8}{di:<12}{de:<12}{his * 100:>+7.1f}%{('*' + f'{fol * 100:+.1f}%') if fol is not None else '—':>9}{mx * 100:>+8.1f}%{mn * 100:>+8.1f}%  {note}")

json.dump(rows, open("/opt/data/fenjue/tmp/yunfeng_accounting.json", "w"), ensure_ascii=False, indent=1)

# 全仓连环复合（他口径，满仓单票轮动=他自己的仓位模式）
import math
chain = [r["his"] for r in rows if r["in"] < "2026-07"]
comp = math.prod(1 + r for r in chain)
wins = sum(1 for r in chain if r > 0)
print(f"\n═══ 全仓连环复合（他口径，{len(chain)} 回合）═══")
print(f"复合倍数: {comp:.2f}x | 胜率 {wins}/{len(chain)} | 宣称 30w→150w=5.0x")
