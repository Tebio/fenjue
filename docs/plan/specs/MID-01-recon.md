# SPEC · MID-01 券商成交导入与逐笔对账 `engine/recon/`（P1，2.5 天）

## 目标
把**账户真值**接进来：导入券商对账单（成交/费用/税费/持仓），与信号与影子账本逐笔对齐，
输出**差异清单**。这是"研究结论到底兑现了多少"的唯一闭环。

## 非目标
- 不自动下单（手工执行不变）
- 不做税务申报

## 现状证据
- `券商/成交回报/实际成交/reconcile` 全仓库**零命中**（51 处"对账"命中全是 `sim_audit.py` 的**模拟内**对账）
- 结果：无 P&L 归因、无法回答成交价 vs 信号价差异、无法发现"应下未下"
- 已知实例：影子账本记 9:25 挂单买入，但**是否成交、成交价多少**无记录（`engine/dashboard_build.py` 的 FILL_NOTE 自述"fill 实测：五单 4 只早盘封死尾盘买不进"＝纸面口径）

## 输入（模板：用户每周导出一次）
券商对账单 CSV / Excel，至少含：
```
成交日期, 证券代码, 证券名称, 买卖标志, 成交价格, 成交数量, 成交金额, 手续费, 印花税, 过户费, 其他费用, 成交时间
```
持仓对账单（可选但推荐）：`证券代码, 持仓数量, 成本价, 市值`

## 接口契约（demo，未实现）
```python
# engine/recon/import_broker.py
def load_broker_trades(csv_path: str) -> list[dict]:
    """字段名容错（不同券商列名不同），返回统一结构；utf-8-sig/GBK 自适应"""

# engine/recon/reconcile.py
DIFF_KINDS = ("missed_signal",   # 有信号未下单
              "extra_trade",     # 无信号却成交
              "price_gap",       # 成交价 vs 信号价偏离超阈值
              "partial_fill",    # 成交数量不足
              "fee_gap",         # 实际费用 vs taxfee 预期
              "tax_gap",         # 红利税实际扣缴 vs 预期
              "position_gap")    # 账本持仓 vs 券商持仓

def reconcile(day: str, trades: list[dict], ledger, signals) -> dict:
    """返回 {date, diffs: [{kind, code, expected, actual, delta_yuan, note}], summary}"""
```

## 验收（正反例）
- 正例：用**一周真实对账单**跑通，差异全部落到 7 类枚举之一（无 "other" 兜底超过 10%）
- 正例：`fee_gap` 能把 `taxfee` 与实际扣费对不上几毛钱的账户解释清楚（含最低佣金）
- 正例：输出可直接被 `attribution.py`（MID-02）消费
- 反例：CSV 缺列 / 编码错 / 数额带千分位 → 必须给出明确报错，不得静默跳过行
- 反例：同一笔成交重复导入两次 → 必须按 `(日期,代码,方向,价格,数量)` 去重并告警

## 依赖 / 风险
- 依赖：`TAX-01`（费用口径对照）、`PORT-01`（账本持仓）
- 风险：**用户手工导出是脆弱环节** → 第一版就要定"导出模板 + 存放路径 + 命名规范"，
  并在盘前自检里提示"本周对账单还没导入"
- 风险：对账差异可能牵出"人工偏离"（没跟信号）→ 喂给 `MID-03` 记录原因

## 工期
导入 1 天 + 对账 1 天 + 一周真实数据核对 0.5 天
