#!/usr/bin/env python3
# engine/guba_rank_fetch.py — 东财股吧人气榜历史批量拉取（RES-09 数据源）
# 端点: emappdata.eastmoney.com/stockrank/getHisList  yearType=5 = 近 366 历日(含周末) 日频人气排名
# 免鉴权公开端点, 实测 ~8 req/s 无限流; 断点续跑(已存在且含最新交易日的文件跳过)
# 用法: python engine/guba_rank_fetch.py [--limit N] [--force]
import json, sys, time, glob
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parent.parent
KC = ROOT / "data" / "big_kcache"
OUT = ROOT / "data" / "guba_rank"
OUT.mkdir(exist_ok=True)
URL = "https://emappdata.eastmoney.com/stockrank/getHisList"
PAYLOAD_BASE = {"appId": "appId01", "globalId": "786e4c21-70dc-435a-93bb-38",
                "marketType": "", "yearType": "5"}

def sec_code(code: str) -> str:
    return ("SH" if code.startswith("6") else "SZ") + code

def fetch_one(sess, code):
    p = dict(PAYLOAD_BASE, srcSecurityCode=sec_code(code))
    r = sess.post(URL, json=p, timeout=15)
    d = r.json()
    rows = d.get("data") or []
    return [[x["calcTime"], int(x["rank"])] for x in rows]

def main():
    limit, force = None, "--force" in sys.argv
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    codes = sorted(Path(fp).stem for fp in glob.glob(str(KC / "*.json")))
    if limit:
        codes = codes[:limit]
    sess = requests.Session()
    done = fail = skip = 0
    t0 = time.time()
    for i, code in enumerate(codes):
        fp = OUT / f"{code}.json"
        if fp.exists() and not force:
            try:
                old = json.loads(fp.read_text())
                if old.get("rows") and old["rows"][-1][0] > time.strftime("%Y-%m-%d"):
                    skip += 1
                    continue
                rows = fetch_one(sess, code)
                if rows:
                    # 按日期键合并: 同日值以「最新一次抓取」为准（盘中值 vs 23:00 定稿值会变）
                    m = {r[0]: r[1] for r in old["rows"]}
                    m.update({r[0]: r[1] for r in rows})
                    merged = sorted([d, v] for d, v in m.items())
                    fp.write_text(json.dumps({"code": code, "rows": merged}))
                    done += 1
                else:
                    fail += 1
                continue
            except Exception:
                pass
        try:
            rows = fetch_one(sess, code)
            if not rows:
                fail += 1
                continue
            fp.write_text(json.dumps({"code": code, "rows": rows}))
            done += 1
        except Exception as e:
            fail += 1
            print(f"[WARN] {code} {type(e).__name__}: {e}")
            time.sleep(2)
        if (i + 1) % 200 == 0:
            print(f"progress {i+1}/{len(codes)} done={done} skip={skip} fail={fail} "
                  f"elapsed={time.time()-t0:.0f}s", flush=True)
        time.sleep(0.06)
    print(f"DONE total={len(codes)} done={done} skip={skip} fail={fail} "
          f"elapsed={time.time()-t0:.0f}s", flush=True)

if __name__ == "__main__":
    main()
