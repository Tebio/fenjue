# 券商成交明细 CSV 模板规范（MID-01 输入件，对接 INTERFACES.md I4）

> 用途：用户每周从券商 App 导出成交明细，喂给 `engine/broker_reconcile.py` 做逐笔对账。
> 本文件是**操作与映射规范**；字段语义以 `docs/plan/INTERFACES.md` I4 为准（冻结，改它走变更流程）。

## 1. 导出方法

| 券商 | 路径 | 注意 |
|---|---|---|
| 东方财富 | 交易 → 查询 → 历史成交 → 导出（选「成交明细」，区间=上周一到上周五） | 导出为 CSV；佣金列名是「佣金」或「手续费」 |
| 同花顺 | 交易 → 查询 → 历史成交 → 导出 | 金额列名是「发生金额」；编码常为 GBK |

编码坑：同花顺/部分券商导出 GBK，导入器已自适应（utf-8-sig → gbk 顺序探测），**不要在 Excel 里另存**（可能改千分位/日期格式）。

## 2. 落盘与命名（私有，不进 git）

```
data/private/broker_trades/<YYYYMMDD>_<来源>.csv
例：data/private/broker_trades/20261016_eastmoney.csv
```

`data/private/` 已 gitignore（I7 私有面）。YYYYMMDD = 导出日（BJT）。

## 3. 规范字段（canonical）与列名映射

必需语义字段：日期 / 代码 / 方向 / 价格 / 数量 / 金额 / 佣金 / 印花税 / 过户费。
推荐字段：时间 / 名称 / 其他费用。

| canonical | 含义 | 东财常见列名 | 同花顺常见列名 |
|---|---|---|---|
| date | 成交日期 YYYY-MM-DD/YYYYMMDD/2026/10/16 均可 | 成交日期 | 成交日期 |
| time | 成交时间（可选） | 成交时间 | 成交时间 |
| code | 6 位代码（容忍 SH600001 / sz002384 前缀） | 证券代码 | 证券代码 |
| name | 证券名称（可选，展示用） | 证券名称 | 证券名称 |
| side | 买/卖 | 买卖标志 | 买卖方向 / 交易类型 / 业务名称 |
| price | 成交价格（元） | 成交价格 / 成交均价 | 成交价格 |
| shares | 成交数量（股，整数） | 成交数量 | 成交数量 |
| amount | 成交金额（元，容忍千分位） | 成交金额 | 发生金额 |
| commission | 佣金（元） | 佣金 / 手续费 | 佣金 |
| stamp_tax | 印花税（元，卖出方收） | 印花税 | 印花税 |
| transfer_fee | 过户费（元） | 过户费 | 过户费 |
| other_fee | 其他费用（可选） | 其他费用 / 规费 | 其他费用 |

方向取值别名：买入 / 证券买入 / 买 / BUY → buy；卖出 / 证券卖出 / 卖 / SELL → sell。

## 4. 对账运行

```bash
cd /opt/data/fenjue
.venv/bin/python engine/broker_reconcile.py data/private/broker_trades/20261016_eastmoney.csv
# 报告（私有）：data/private/recon/reconcile_report_<YYYYMMDD>.json
# stdout 同时打印晨报可读摘要
# 自测（合成数据，不碰真实文件）：
.venv/bin/python engine/broker_reconcile.py --selftest
```

## 5. 反例（导入器必须显式报错，不得静默跳行）

- 缺必需列（如无「佣金」列）→ 报错列出缺失字段与已识别表头
- 编码既不是 UTF-8 也不是 GBK → 报错
- 数字带千分位（10,000.50）/ 货币符号 → 自动清洗，清洗失败报错
- 同一笔（日期,代码,方向,价格,数量）出现两次 → 去重并在报告 warnings 中列出

## 6. 节奏

每周五收盘后（或周末）导出一次 → 落 `data/private/broker_trades/` → 跑对账 → 晨报摘要进周报。
连续两周无新 CSV 时，盘前自检应提示「对账单未导入」（后续接 dq 断言层，非本 v1 范围）。
