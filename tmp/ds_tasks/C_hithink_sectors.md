# 任务C：HiThink 同花顺板块成分周更管线

## 背景
销「板块概念群聚合」欠账：体系缺股票→概念板块映射，需每周拉取同花顺指数目录+成分股落盘。

## 已实测验证的 API（2026-09-13 实测可用，勿猜别的端点）
- Base: https://fuyao.aicubes.cn，认证头 `X-api-key: <HITHINK_API_KEY>`（key 从 /opt/data/.env 读，代码里禁止打印/落盘 key）
- 指数目录：GET /api/a-share-index/catalog/ths-index-list
  实测返回 {code:0, data:{timestamp, item:[{thscode:"885431.TI",name:"新能源汽车"},...]}}——
  实测 size=3 参数被忽略、一次返回大批量，代码须同时兼容分页（size/page+pagination）和一次性全量两种形态
- 成分股：GET /api/a-share-index/constituents/ths-stock-list?thscode=886042.TI
  实测返回 {code:0, data:{timestamp, item:[{thscode:"000021.SZ",ticker:"000021",name:"深科技"},...]}}
  单次只接受一个指数（不接受逗号）
- 错误形态：{code:404, message:"Route not found"}；限流未实测，按 0.3s/请求自律+失败重试3次指数退避

## 交付物
新文件 engine/hithink_sectors.py，完整可运行：
1. 拉全量指数目录 → data/hithink/sectors/catalog_YYYYMMDD.json（含拉取日期）
2. 逐个拉成分股 → data/hithink/sectors/constituents/<thscode>.json（断点续跑：已存在且当日的跳过）
3. 建反向映射 data/hithink/sectors/stock_sectors_YYYYMMDD.json：
   {6位代码: [{"thscode","name"},...]}（key 用 ticker 6位，不含后缀）
4. stdout 汇报：指数总数/成功拉取成分数/覆盖股票数/最大的10个板块（按成分数）/每只票平均所属板块数
5. 看门狗纪律：目录拉取失败（code!=0）→ 报错退出非0；成分个别失败→记 warn 继续，最后报失败清单

## 约束
- stdlib only（json/urllib或subprocess+curl 均可，参考风格附后），禁 requests 等第三方库
- 全程速率自律 0.3s/请求；预计指数数千个，须打印进度（每200个一行）
- 文件头注释写明端点实测日期与口径

## 附：既有 hithink_daily.py 风格参考（认证/分页/落盘惯例）
```python
#!/usr/bin/env python3
"""engine/hithink_daily.py — HiThink 官方数据日更落盘（向前积累，绕过其1年历史深度限制）

每日落盘（data/hithink/<date>/）：
  limit-up-pool / limit-down-pool / limit-break-pool / limit-up-ladder / dragon-tiger(all/org/hot_money)
参数纪律（2026-09-12 实测）：池子用 date_ms=（交易日-1天）UTC零点毫秒戳；龙虎榜用 date=YYYY-MM-DD。
无数据（非交易日/未就绪）安静退出（看门狗），错误才出声。
"""
import json, os, subprocess, sys, time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
OUT = ROOT / "data/hithink"
KEY = None
for line in Path("/opt/data/.env").read_text().splitlines():
    if line.startswith("HITHINK_API_KEY="):
        KEY = line.split("=", 1)[1].strip()
assert KEY, "HITHINK_API_KEY missing"

BASE = "https://fuyao.aicubes.cn"


def get(path):
    r = subprocess.run(["curl", "-sL", "--max-time", "20", "-H", f"X-api-key: {KEY}", BASE + path],
                       capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"})
    return json.loads(r.stdout)


def get_paged(path):
    """池子类端点分页拉全（size≤200，2026-09-12 实测 1003 越界）。"""
    sep = "&" if "?" in path else "?"
    items, page = [], 1
    meta = None
    while True:
        r = get(f"{path}{sep}size=200&page={page}")
        if r.get("code") != 0:
            return r
        data = r.get("data") or {}
        meta = data.get("pagination", {})
        items.extend(data.get("item", []))
        if page >= meta.get("pages", 1):
            break
        page += 1
        time.sleep(0.3)
    if meta:
        r["data"]["item"] = items
    return r


def main():
    d = os.environ.get("HT_DATE") or date.today().isoformat()
    dt_ = date.fromisoformat(d)
    # 实测映射（2026-09-12 内容级交叉验证）：date_ms = 交易日 16:00 BJT（收盘）= 当日 08:00 UTC
    date_ms = int(datetime.combine(dt_, datetime.min.time(), tzinfo=timezone.utc).timestamp()
                  * 1000 + 8 * 3600 * 1000)
    outdir = OUT / d
    outdir.mkdir(parents=True, exist_ok=True)
    wrote = 0
    targets = {
        "limit_up_pool": f"/api/a-share/special-data/limit-up-pool?date_ms={date_ms}",
        "limit_down_pool": f"/api/a-share/special-data/limit-down-pool?date_ms={date_ms}",
        "limit_break_pool": f"/api/a-share/special-data/limit-break-pool?date_ms={date_ms}",
        "limit_up_ladder": "/api/a-share/special-data/limit-up-ladder",
        "lhb_all": f"/api/a-share/special-data/dragon-tiger-list?board_type=all&date={d}",
        "lhb_org": f"/api/a-share/special-data/dragon-tiger-list?board_type=org&date={d}",
        "lhb_hot": f"/api/a-share/special-data/dragon-tiger-list?board_type=hot_money&date={d}",
    }
    for name, path in targets.items():
        try:
            r = get_paged(path) if "pool" in name else get(path)
            if r.get("code") != 0:
                print(f"WARN {name}: code={r.get('code')} {r.get('message')}")
                continue
            data = r.get("data") or {}
            n = data.get("pagination", {}).get("total") or data.get("count") or len(data.get("item", []))
            if not n and "ladder" not in name:
                continue  # 空=非交易日/未就绪，安静跳过
            (outdir / f"{name}.json").write_text(json.dumps(r, ensure_ascii=False))
            wrote += 1
            time.sleep(0.3)
        except Exception as e:
            print(f"ERR {name}: {e}")
    if wrote:
        print(f"hithink daily {d}: {wrote}/7 落盘 → {outdir}")
    if not wrote and not os.environ.get("HT_DATE"):
        pass  # 非交易日静默


if __name__ == "__main__":
    main()

```
