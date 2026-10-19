#!/usr/bin/env python3
"""基金共同持股网络 · 数据拉取（东财 RPT_MAINDATA_MAIN_POSITIONDETAILS，ORG_TYPE_CODE=1 基金）
产物: data/fund_cohold/positions/<Q>.jsonl  每行 {p,s,f,fn,nr,mc}
断点幂等: 每季一文件 + .done 标记; 6 线程并发, page 级重试。
用法: .venv/bin/python engine/fund_cohold_pull.py
"""
import json, os, subprocess, sys, threading, time
from queue import Queue

ROOT = "/opt/data/fenjue"
OUT = f"{ROOT}/data/fund_cohold/positions"
QUARTERS = ["2021-06-30", "2021-12-31", "2022-06-30", "2022-12-31",
            "2023-06-30", "2023-12-31", "2024-06-30", "2024-09-30",
            "2024-12-31", "2025-03-31", "2025-06-30", "2025-09-30",
            "2025-12-31", "2026-03-31", "2026-06-30"]
BASE = ("https://datacenter-web.eastmoney.com/api/data/v1/get"
        "?sortColumns=HOLDER_CODE,NETASSET_RATIO&sortTypes=1,-1"
        "&pageSize=500&reportName=RPT_MAINDATA_MAIN_POSITIONDETAILS"
        "&columns=SECUCODE,SECURITY_CODE,HOLDER_CODE,HOLDER_NAME,NETASSET_RATIO,HOLD_MARKET_CAP"
        "&source=WEB&client=WEB")
WORKERS = 6


def fetch(q, page):
    url = f"{BASE}&pageNumber={page}&filter=(REPORT_DATE%3D%27{q}%27)(ORG_TYPE_CODE%3D%221%22)"
    for attempt in range(8):
        r = subprocess.run(["curl", "-s", "--max-time", "40", url],
                           capture_output=True, text=True)
        try:
            res = (json.loads(r.stdout) or {}).get("result") or {}
            if res.get("data") is not None:
                return res
        except Exception:
            pass
        time.sleep(1.5 * (attempt + 1))
    return None


def pull_quarter(q):
    fp = f"{OUT}/{q}.jsonl"
    if os.path.exists(fp + ".done"):
        print(f"[SKIP] {q}", flush=True); return True
    done = set()
    if os.path.exists(fp):
        with open(fp) as f:
            for line in f:
                try: done.add(json.loads(line)["p"])
                except Exception: pass
    first = fetch(q, 1)
    if first is None:
        print(f"[FAIL] {q} page1", flush=True); return False
    total, count = first["pages"], first.get("count")
    lock = threading.Lock()
    f = open(fp, "a" if done else "w")

    def writer(page, rows):
        with lock:
            for r in rows:
                f.write(json.dumps({"p": page, "s": r["SECURITY_CODE"], "f": r["HOLDER_CODE"],
                                    "fn": r.get("HOLDER_NAME"), "nr": r.get("NETASSET_RATIO"),
                                    "mc": r.get("HOLD_MARKET_CAP")}, ensure_ascii=False) + "\n")
            done.add(page)

    if 1 not in done:
        writer(1, first["data"])
    todo = Queue()
    for p in range(2, total + 1):
        if p not in done:
            todo.put(p)
    failed = []

    def worker():
        while True:
            try: page = todo.get_nowait()
            except Exception: return
            res = fetch(q, page)
            if res is None:
                with lock: failed.append(page)
            else:
                writer(page, res["data"])
            time.sleep(0.05)

    threads = [threading.Thread(target=worker) for _ in range(WORKERS)]
    t0 = time.time()
    for t in threads: t.start()
    for t in threads: t.join()
    f.close()
    if failed:
        print(f"[RETRY-LATER] {q} failed pages={failed[:8]}", flush=True); return False
    seen = set()
    with open(fp) as fh:
        for line in fh:
            try: seen.add(json.loads(line)["p"])
            except Exception: pass
    if len(seen) < total:
        print(f"[INCOMPLETE] {q} {len(seen)}/{total}", flush=True); return False
    open(fp + ".done", "w").write("ok")
    print(f"[DONE] {q} pages={total} count={count} elapsed={time.time()-t0:.0f}s", flush=True)
    return True


def main():
    os.makedirs(OUT, exist_ok=True)
    pending = list(QUARTERS)
    round_n = 0
    while pending and round_n < 4:
        round_n += 1
        still = []
        for q in pending:
            if not pull_quarter(q):
                still.append(q)
        pending = still
        if pending:
            print(f"[round {round_n}] 剩余未完成 {pending}, 30s 后重试", flush=True)
            time.sleep(30)
    if pending:
        print(f"ABORT: 未完成 {pending}", flush=True); sys.exit(1)
    print("ALL_QUARTERS_DONE", flush=True)


if __name__ == "__main__":
    main()
