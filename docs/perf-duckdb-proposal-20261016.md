# 数据层迁移提案：big_kcache JSON → Parquet/DuckDB（可行性评估，不实施）

任务卡 t_05a4241d ④ / AGENTS #279。只做评估，**不实施**。实测底座：`engine/perf_io_bench.py`（可复跑），原始数字 `data/perf_io_bench_20261016.json`。

## 实测数字（400 只样本 → 3377 只线性外推，机器有并发负载，绝对值偏保守、比值可靠）

| 口径 | 400 只 | 外推全量 3377 只 | 备注 |
|---|---|---|---|
| JSON 逐个加载（现 load_universe 方式） | 18.29s | ~154s | 任务书基线 82s 是生产实测（跳过 <300 bar 的票+无并发）；样本外推口径不同，两者都列 |
| Parquet(zstd) + pandas 读 | 2.08s | **~18s** | 含 groupby 拆回 dict 形状 |
| DuckDB 全量拉取 | 9.09s | ~77s | fetchall 到 python 对象慢；DuckDB 的价值不在全量拉，在过滤/聚合下推 |
| 体积 | 84.5MB | 675MB → **~135MB（压缩比 5.0x）** | JSON→parquet/zstd |

结论：**加载 82s → 估 10~20s（4~8 倍），磁盘 675MB → ~135MB**。加速比真实但不改变任何研究结论的性质——省的是每次实验台启动的等待，不是算力瓶颈（瓶颈在 KNN/扫描循环，已由 ①② 处理）。

## INTERFACES.md 冻结契约影响面（不实施的第一原因）

- `docs/plan/INTERFACES.md` 状态 **FROZEN**：路径/字段/单位变更须 DECISIONS.md 新增条目 + 用户签字 + 所有消费方同批改。
- 消费面实测：`grep -rl 'big_kcache' engine/ scripts/ *.py` = **154 个文件**直接按 `data/big_kcache/<code>.json` 路径 `json.loads` 消费。改存储格式 = 154 个消费点同批改，违反「只许追加字段」「改动须同批」的现实成本极高。
- JSON 单文件形态同时是**生产链日更接口**（新浪/baostock 增量追加单票文件）与调试接口（肉眼可读、jq 可查）。parquet 单一文件则追加写要整文件重写或分区化，日更链（kcache 全量更新/分片班）全部要改。

## 若未来要做的推荐形态（仅记录，非提案实施）

1. **只加不换**：新增 `data/kcache.parquet`（或按年分区 `data/kcache_parquet/year=YYYY/`）作为**派生只读层**，由日更链末尾从 JSON 再生；JSON 保持唯一权威源。研究脚本（law_pipeline.load_universe、similarity build、factor_census）加 `--fast-io` 旁路读 parquet。零冻结契约变更（新增产物不动旧路径）。
2. 校验纪律：派生层每次再生后与 JSON 源对账（行数/逐票尾 bar 收盘），对不上拒绝覆盖。
3. DuckDB 定位为**即席查询引擎**（跨票横截面过滤/聚合），不是存储层；存储层 parquet 就够。
4. 预期收益落到体验：factor_census 类全宇宙实验台启动 69s 矩阵建成中 IO 占比约一半，可压到 ~40s；load_universe 82s → ~15s。

## 判词

收益真实但小（分钟级/次），改动面大（154 消费点 + 日更链 + 冻结契约），**维持「不实施」**。触发重估的条件：宇宙扩到全市场含科创/北交（>5000 只）或分钟级数据入库（体积×240），届时 JSON 形态会真的撑不住。
