# SPEC · TAX-01 费率与税费唯一真源 `engine/taxfee/`（P0，1.5 天）

## 目标
把所有"算钱"的常数与规则收进一个模块：**佣金、印花税、过户费、最低佣金、红利税（按持有期）**。
之后全仓库任何地方算成本都必须调它；`0.15` 这类字面量在 `lines/`、`portfolio/` 里出现即视为 bug。

## 非目标
- 不建模滑点（滑点属于执行层，`recon/` 用实测回填）
- 不做税筹优化建议（只做**如实计算**，策略侧怎么用另说）

## 现状证据
- `engine/entryexit_matrix.py:116` → `COST = 0.15  # 双边印花税+佣金`（平口径）
- `engine/limitup_capture_t0.py:82` → `FEE_RT = 0.001  # 买佣金0.025% + 卖佣金0.025%+印花0.05%`（真实费目）
- `engine/sept_50k_sim.py:6` → 提到"佣金 5 元×2 + 印花税 + 滑点"
- 含 `0.15` 的文件 **109 个**（两套口径并存 → 跨结论不可横向比）
- `engine/dividend_core_satellite.py:41` 自述"**红利税未建模**"

## 接口契约（demo，未实现）
```python
# engine/taxfee/__init__.py
from dataclasses import dataclass

@dataclass(frozen=True)
class FeeSchedule:
    commission_rate: float = 0.00025   # 佣金，双边
    commission_min: float = 5.0        # 单笔最低 5 元
    stamp_sell: float = 0.0005         # 印花税，仅卖出
    transfer_rate: float = 0.00001     # 过户费（沪深现行口径，按需校准）

def buy_fee(amount: float, sched: FeeSchedule = FeeSchedule()) -> float: ...
def sell_fee(amount: float, sched: FeeSchedule = FeeSchedule()) -> float: ...
def roundtrip_cost(amount: float, sched: FeeSchedule = FeeSchedule()) -> float:
    """返回「双边费用/成交额」的比例；小单会被最低佣金显著抬高"""

def dividend_tax(holding_days: int, gross_dividend: float) -> float:
    """A 股红利税按持有期：不满 1 个月 20%、1 个月至 1 年 10%、超过 1 年 0%"""
```

## 需要回填的真实数字（开工时校准并写进 docstring）
- 佣金费率（他券商的真实费率，默认按 0.025% 但必须核）
- 最低佣金 5 元是否适用于他的账户
- 过户费口径（沪深是否都收、比例）
- 红利税三档的**实际扣缴时点**（卖出时补扣 / 分红到账时预扣）与持有期起算规则

## 验收（正反例）
- 正例：`buy_fee(20000) == 5.0`（20000×0.025%=5.0，等于最低值边界）
- 正例：`buy_fee(5000) == 5.0`（**最低佣金生效**：按率算只有 1.25 元）
- 正例：`roundtrip_cost(20000)` ≈ 0.00075~0.0008（双边佣金+印花税），`roundtrip_cost(5000)` ≈ 0.0021（**成本翻倍**）
- 正例：`dividend_tax(20, 1000) == 200`、`dividend_tax(200, 1000) == 100`、`dividend_tax(400, 1000) == 0`
- 反例：任何负数金额、0 金额必须 `raise ValueError`
- 对照：`limitup_capture_t0.py` 在 2 万元档下，新模块输出与它的 `FEE_RT=0.001` 差异必须被解释（差额来源=最低佣金/过户费）

## 迁移清单（分批，完成勾选）
1. `entryexit_matrix.py`（基准口径，影响所有历史结论 → **必须双跑对照并记录差异**）
2. `pead_pool_sim.py` / `dividend_sim*.py` / `sim_tournament.py` / `allocation_sim.py`
3. 各 `lines/*` 生产脚本（出票/记账路径）
4. 其余零散脚本（脚本化扫描：`grep -rl "0.15" engine/ scripts/`）

迁移产出：`data/口径迁移台账.jsonl`（文件 / 旧值 / 新值 / 差异 pp / 日期）

## 风险
- **红利税影响股息锚线的税后买入线**：4.5% 毛息率在不满 1 年时 ≈4.05% → 需要与 `lines/dividend_anchor.py` 一起重算（另立条目）
- 历史结论使用平口径 0.15%：迁移后数字会变，**必须逐一标注是否改判**，不能静默更新
