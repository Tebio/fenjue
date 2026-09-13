# 任务F：HiThink 同花顺板块指数历史日线回填

## 背景
板块成分映射已落盘（390指数/5571票）。现需板块指数的历史日K，供「板块维度回测/风格切换研究」用。

## 已实测验证的 API（2026-09-13，勿猜别的）
- GET /api/a-share-index/prices/historical?thscode={code}&interval=1d&start={ms}&end={ms}
- 参数：interval 仅支持 1d；start/end 为毫秒 Unix 戳；**end-start 超过10年返回 code=1003**
- 返回：{code:0, data:{thscode, interval, adjust:null, item:[{date_ms,volume,turnover,open_price,high_price,low_price,close_price},...]}}
- 认证/限速/错误形态：与附后源码相同（X-api-key 头从 /opt/data/.env 读，禁止打印或落盘 key）

## 交付物
新文件 engine/hithink_index_history.py，完整可运行：
1. 读 data/hithink/sectors/ 最新 catalog_*.json 拿全部指数 thscode+name
2. 逐指数拉 2019-01-01 至今日日线 → data/hithink/index_hist/<thscode>.json
   落盘格式 {thscode, name, fetch_date, item:[{date:"YYYY-MM-DD",open,high,low,close,volume,turnover},...]}
   （date_ms 转 YYYY-MM-DD，注意是 UTC 戳——按 UTC 日期转换即可，板块指数不涉及盘中时区问题）
3. 增量模式：已有文件则只拉「文件最后日期+1天」起的新数据并合并去重
4. 速率 0.3s/请求+失败3次指数退避；每50个打印进度；结尾汇报：成功/失败/总bar数/日期覆盖范围
5. 看门狗：catalog 缺失 → 报错退出码2

## 约束
stdlib only（json/subprocess+curl/time/pathlib/datetime）；支持断点续跑。

## 附：engine/hithink_daily.py 源码（认证/纪律惯例）
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
