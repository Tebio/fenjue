#!/usr/bin/env python3
"""engine/perf_io_bench.py — 数据层 IO 基准：big_kcache JSON vs parquet/DuckDB（AGENTS #279④ 提案的实测底座）

只对样本子集实测后线性外推，不迁移任何生产数据。样本=big_kcache 前 400 只。
口径对齐 load_universe：json.loads + 字段抽列成 dict-of-lists。
产出：data/perf_io_bench_20261016.json

用法：.venv/bin/python engine/perf_io_bench.py [n_stocks]
"""
import glob, json, sys, time
from pathlib import Path

ROOT = Path("/opt/data/fenjue")
KC = ROOT / "data/big_kcache"
OUT = ROOT / "data/perf_io_bench_20261016.json"
TMP_PARQUET = Path("/opt/data/cache/scratch/kcache_bench.parquet")


def load_json(files):
    t0 = time.time()
    stocks = {}
    for fp in files:
        ks = json.loads(open(fp).read())
        stocks[Path(fp).stem] = {k: [r[k2] for r in ks] for k, k2 in
                                 [("c", "close"), ("o", "open"), ("h", "high"), ("l", "low"),
                                  ("date", "date")]}
        stocks[Path(fp).stem]["v"] = [r.get("volume", 0) for r in ks]
    return stocks, time.time() - t0


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 400
    files = sorted(glob.glob(str(KC / "*.json")))[:n]
    res = {"样本股票数": n}

    stocks, t_json = load_json(files)
    res["json_加载s"] = round(t_json, 2)
    json_bytes = sum(Path(f).stat().st_size for f in files)
    res["json_体积MB"] = round(json_bytes / 1e6, 1)

    import pandas as pd
    rows = []
    for code, d in stocks.items():
        m = len(d["date"])
        rows.append(pd.DataFrame({"code": code, "date": d["date"], "open": d["o"],
                                  "high": d["h"], "low": d["l"], "close": d["c"],
                                  "volume": d["v"]}, index=range(m)))
    df = pd.concat(rows, ignore_index=True)
    t0 = time.time()
    df.to_parquet(TMP_PARQUET, compression="zstd", index=False)
    res["parquet_写入s"] = round(time.time() - t0, 2)
    res["parquet_体积MB"] = round(TMP_PARQUET.stat().st_size / 1e6, 1)

    t0 = time.time()
    df2 = pd.read_parquet(TMP_PARQUET)
    stocks2 = {c: g for c, g in df2.groupby("code")}
    res["parquet_pandas_加载s"] = round(time.time() - t0, 2)

    import duckdb
    t0 = time.time()
    con = duckdb.connect()
    recs = con.execute(f"SELECT * FROM '{TMP_PARQUET}' ORDER BY code, date").fetchall()
    res["duckdb_全量拉取s"] = round(time.time() - t0, 2)
    res["duckdb_行数"] = len(recs)

    total_files = len(glob.glob(str(KC / "*.json")))
    res["全量文件数"] = total_files
    res["外推_json_全量加载s"] = round(t_json / n * total_files, 1)
    res["外推_parquet_全量加载s"] = round(res["parquet_pandas_加载s"] / n * total_files, 1)
    res["体积压缩比"] = round(json_bytes / TMP_PARQUET.stat().st_size, 1)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
