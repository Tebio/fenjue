# DATA-01 数据面监控机（data_health）施工报告

2026-10-20 · 执行：Hermes（kimi-k3）· spec：docs/plan/specs/DATA-01-data-health.md（唯一真源）

---

## 1. 交付清单（全部实跑验证，命令与输出见 §4）

| 产物 | 路径 | 说明 |
|---|---|---|
| 时效判定唯一出处 | `engine/freshness_core.py`（237 行） | STATUSES 六态 / trading_days_between / extract_date / assess / load_registry / validate_registry |
| 声明式注册表 | `data/datasets_registry.yaml` | 一期 10 个真实在用数据集，七字段齐全 + consumers 封闭清单 + mandatory 必注册集 |
| 监控机 | `engine/data_health.py`（229 行） | check_all + main，四输出 + 幂等 state + 报告段 + 看门狗 stdout |
| 作战单接线 | `engine/ops_briefing.py`（+10 行，.bak 已留） | try/except 包裹，仅 fatal 时渲染一行，缺失静默跳过 |
| golden case | `tests/golden/_cases.py` + `oracle/data_health_snapshot.json` | 冻结注册表声明与四条协议不变量 |
| 协议断言 | `tests/test_golden_master.py::test_data_health_protocol` | (a)(b)(c)(d) + 状态词表 + 配置错误路径 |
| 四输出 | `data/data_health.json` / `data_health_state.json` / `data_health_report.md` / `data/health/2026-10-20.json` | INTERFACES I0：UTF-8 无 BOM、原子写、_meta 带 version/date/generated_at(+08:00) |

未改任何既有数据产物；未动 `engine/k4_*.py`、`data/big_kcache/`、`data/emotion_series.jsonl`、`data/regime_*.json*`、`cron/`；未新增 cron job；未 git commit/push；全程未联网（交易日历只读本地缓存 `data/trade_calendar/2026.json`）。

## 2. 设计取舍（每条附理由）

1. **滞后只按官方交易日历算，且只读本地缓存**。`trading_days_between` 直接读
   `data/trade_calendar/<year>.json`，**故意不调** `trade_calendar.trading_days()`——后者
   缓存过期会 import baostock 联网，违反本卡「严禁联网抓数」。日历缓存缺失/为空/损坏 →
   raise CalendarUnavailable → main 兜底 exit 2（基建错误）。不许猜节假日（#330-B 同款纪律）。
2. **status 六态与退出码三分**：0=无 fatal；1=fatal_lag/missing/unregistered（cron 报红）；
   2=配置错误（fatal 无 blocks 等）或基建错误（日历不可用）。`unknown_date` 不进 exit 1——
   spec 退出码契约只点名 fatal_lag/missing；它进报告 ⚠️ 段与状态机。这是 spec 字面解读，
   若要让「fatal 级数据集日期解析失败」也报红，改 FATAL_STATUSES 一处即可，留作裁决点。
3. **default ref-date = 最近已收盘交易日**（交易日 16:00 BJT 前取前一交易日）。9:25 作战单
   盘前消费时若基准取「今天」，昨晚数据必被误判滞后 1 天 = 每日假 fatal。spec 没写默认值，
   这是本卡自定语义，已写进 `_meta.ref_source` 可查。
4. **目录模式取「最近写入的 ≤25 个文件末 bar 日期最大值」**（spec 风险 2：本期只看末端日期，
   不看覆盖率；覆盖率闸留在 regime 侧）。kcache 的新浪 schema 日期字段是 `day` 不是 `date`，
   语法 `dir:last_bar:day` 支持。
5. **consumers 封闭清单放在注册表头部**。spec 协议断言 (c) 说 blocks 必须 ∈「spec 的消费者
   清单」，但 DATA-01 spec 正文没有机器可读的清单（只有散文里的 深档名单/影子盘/周期仪/
   9:25 作战单/20:40 面板/line_health/晨报）。我把这套词汇落成 yaml 的 `consumers:` 段
   （12 个，注释标明对应模块），golden 断言 (c) 以它为封闭世界。这是对 spec 的最小补全，
   未改 spec 文件本身。
6. **注册 10 个数据集的选择**：mandatory 5（spec 钉死）+ index_sh000001（regime 判定与日历
   回退基准）+ regime_log（面板徽标源，#330-B 事故现场）+ xrules_state（作战单第 3 段）
   + line_health（监控机的监控）+ watch_pool（状态制，updated 不保证每日动，故 max_lag=1/
   severity=info）。宁少勿滥（spec 风险 4）；gold_current 的 entry_day 是月度语义、
   pead_pool_state 按公告日驱动，都不适合日频时效判定，未注册。
7. **severity 分级**：fatal 只给「断供=下游结论不可信」的 5 个（big_kcache/emotion_series/
   regime_timeline_hcap/ops_state/index_sh000001）；regime_log/xrules_state/line_health 给
   warn（自带告警或不挡主链）；watch_pool 给 info。
8. **幂等 state 照抄 line_health threats 段形态**：`fatal_active` 跨重跑持续标志位——新增
   触发才告警，同日重跑不重复计数不重复吵，连续多日同故障不每天吵，恢复后再断才重新告警。
   （初版用「昨日 status」判新增，同日重跑会重复告警，实跑抓出后改成现形态，见 §5 坑 1。）
9. **ops_briefing 只在有 fatal 时渲染一行**（D-11 只异常推送），全绿时不占作战单版面。
   try/except 包裹 + jload 默认 {}，三重 fail-soft。
10. **golden 冻结「声明」不冻结「日期」**：oracle 里是注册表七字段 + 四条不变量布尔；
    解析出的日期每天前进，冻结 = 每天红。不变量翻转（数据集断供/表达式失效）才会翻红，
    这正是协议断言的本职。

## 3. 注册表选型理由

- **yaml 而非 json/py**：与 claims_registry.yaml 同构（line_health 的形态锚），人改机器读都
  成熟；注释能力必需（每个数据集要写清「为什么这个 severity」）。
- **七字段契约**（path/date_expr/cadence/max_lag/severity/blocks/owner）逐字按 spec；
  `mandatory` 必注册集实现 spec 协议断言 (d) 的「防新数据集绕过注册」——缺了出
  unregistered 伪条目 + exit 1。
- **cadence 一期只用 `daily`**（每交易日）。周末/假日滞后由交易日计数天然吸收
  （周五数据 vs 周一基准 lag=1，但 default ref-date 盘前会取周五，不误报）。

## 4. 四组实跑证据（命令 + 真实 stdout）

### 4.1 正例：`--ref-date 2026-10-19`

```
$ .venv/bin/python engine/data_health.py --ref-date 2026-10-19   # 经 data01_run.py 测量包装
=== STDOUT ===
（空——看门狗纪律：无新增 fatal 零输出）
=== exit_code=0 elapsed=0.36s peak_rss=20.0MB ===
```

`data/data_health.json` 关键字段（真实读取）：

```
big_kcache               status=ok     date=2026-10-19 lag=0 max_lag=0 sev=fatal
emotion_series           status=ok     date=2026-10-19 lag=0 max_lag=0 sev=fatal
index_sh000001           status=ok     date=2026-10-19 lag=0 max_lag=0 sev=fatal
kcache                   status=ok     date=2026-10-19 lag=0 max_lag=0 sev=warn
line_health              status=ok     date=2026-10-19 lag=0 max_lag=0 sev=warn
ops_state                status=ok     date=2026-10-19 lag=0 max_lag=0 sev=fatal
regime_log               status=ok     date=2026-10-19 lag=0 max_lag=0 sev=warn
regime_timeline_hcap     status=ok     date=2026-10-19 lag=0 max_lag=0 sev=fatal
watch_pool               status=ok     date=2026-10-19 lag=0 max_lag=1 sev=info
xrules_state             status=stale  date=2026-10-16 lag=1 max_lag=0 sev=warn
summary: {ok:9, stale:1, fatal_lag:0, missing:0, unregistered:0, unknown_date:0, total:10}
各项计数之和 10 == 注册表条目数 10 ✓
```

验收点全中：`big_kcache.status==ok 且 lag==0` ✓；`emotion_series.status==ok`（2131 行，
末端 2026-10-19）✓。`xrules_state` 判 stale 是**事实**不是误报：10-19 kcache 三班全挂时
X规则线覆盖率闸正确拒判（state 停 10-16），补数后未重跑——监控机第一天上岗就抓到一条
真实滞后。耗时 0.36s / 峰值 20.0MB（上限 60s / 300MB，余量两个数量级）。
同日重跑×2 验证幂等：stdout 均空、exit 均 0、state history 当日记录被覆盖不重复计数 ✓。

### 4.2 反例 A：fatal/max_lag=0/路径不存在的假数据集

临时注册表 `registry_A.yaml`（生产 yaml 复制 + fake_missing_ds），`--outputs-dir` 沙盒落盘，
生产产物零污染：

```
$ .venv/bin/python engine/data_health.py --ref-date 2026-10-19 \
    --registry .../registry_A.yaml --outputs-dir .../dh_out_a2   # 第 1 跑
【数据面告警 2026-10-20】（ref=2026-10-19）
[数据断供] fake_missing_ds：missing（路径不存在：data/__definitely_not_here__.json）
→ 静默污染下游：深档名单；owner=反例A（验收用假条目）——监控机只告警不自动补数
=== exit_code=1 ===
$ （同参第 2 跑，幂等）=== STDOUT ===（空）=== exit_code=1 ===
```

沙盒 `data_health.json`：`items.fake_missing_ds.status == "missing"` ✓；
沙盒 `data_health_report.md` 🚨 段含 `- **fake_missing_ds** \`missing\`` ✓；退出码 1 ✓。

### 4.3 反例 B：`date_expr` 写成 `"[-1].nope"`

```
$ .venv/bin/python engine/data_health.py --ref-date 2026-10-19 --registry .../registry_B.yaml ...
=== exit_code=0 ===（unknown_date 不进 exit 1，见 §2-2 裁决点）
```

沙盒 `data_health.json`：`items.regime_timeline_hcap.status == "unknown_date"`，
`date == None`，reason=`date_expr '[-1].nope' 解析不出 YYYY-MM-DD（表达式写错或产物结构变了）`
——**没有**降级成 ok ✓；报告 ⚠️ 段含 unknown_date ✓。

### 4.4 反例 C：fatal 条目 blocks 为空

```
$ .venv/bin/python engine/data_health.py --ref-date 2026-10-19 --registry .../registry_C.yaml ...
【数据面监控·配置错误】big_kcache: severity=fatal 但 blocks 为空——fatal 必须声明阻塞面，否则告警无人认领
=== exit_code=2 ===
```

✓ 引擎拒绝开工，零写盘。

### 4.5 golden + 全量 pytest

```
$ .venv/bin/python -m tests.golden.record data_health_snapshot
[record] ✅ data_health_snapshot → tests/golden/oracle/data_health_snapshot.json (4328 B, 0.2s)

$ .venv/bin/python -m pytest tests/test_golden_master.py -q -k data_health
2 passed, 10 deselected in 0.95s        （REAL_EXIT=0）

$ .venv/bin/python -m pytest tests/test_golden_master.py -q
1 failed, 11 passed in 15.08s
  FAILED test_factor_census_registry_frozen - assert 25 == 24（stage1 因子数 +knn_vote）
```

唯一失败 = **既存问题**（#329 已记账：因子注册表 25 vs 断言 24，与 DATA-01 无关，未动）。

### 4.6 ops_briefing 三态冒烟（OPS_DATE=2026-10-20）

| 场景 | 结果 |
|---|---|
| 现役 data_health.json（无 fatal） | 作战单正常渲染，无断供行，exit 0 ✓ |
| 换成反例 A 的 json（含 fake fatal） | 渲染 `🚨 数据面断供：fake_missing_ds[missing] —— 相关下游结论先别信…`，exit 0 ✓ |
| data_health.json 移走（缺失） | 作战单照常完整渲染，静默跳过，exit 0 ✓ |

测后已恢复生产 `data_health.json` 并重跑正例刷新四输出。

### 4.7 默认 ref-date 与 plan_lint

```
$ .venv/bin/python engine/data_health.py --report   # BJT 11:57（<16:00）
# 数据面监控 · 2026-10-20（体检基准 ref=2026-10-19，auto(最近已收盘交易日)）✓ 盘前自动取前一交易日

$ .venv/bin/python docs/plan/tools/plan_lint.py
✅ 全绿（2 个 P2 缺 spec 警告为既存：OPT-02 / DOC-01）
```

## 5. 与 build_daily_state.freshness() 的对照（spec 验收-对照）

方法：直接 `from build_daily_state import freshness` 调**它的真实实现**，与 `freshness_core.assess`
跑同一基准日（脚本 `/opt/data/cache/scratch/data01_compare.py`，两边都不重实现）：

```
--- ref=2026-10-19 ---                          --- ref=2026-10-20（合成滞后基准）---
big_kcache           ours=ok        bds=（无调用点）   ours=fatal_lag lag=1  bds=（无调用点）
ops_state            ours=ok        bds=ok             ours=fatal_lag lag=1  bds=stale
regime_timeline_hcap ours=ok        bds=ok             ours=fatal_lag lag=1  bds=stale
emotion_series       ours=ok        bds=（无调用点）   ours=fatal_lag lag=1  bds=（无调用点）
```

逐条解释（差异必须为空或写出理由）：
1. **ops_state / regime_timeline_hcap**（bds 有调用点的两项）：两个基准日下**映射后完全一致**。
   映射规则：bds 只有 ok/stale/missing/unknown_date 四态且无严重级；我们的 `fatal_lag` 对
   severity=fatal 条目 ≡ bds `stale`（同一物理事实「日期 < 基准」，我们多带了分级与交易日
   lag 数值）。字符串比较（bds）与交易日历 lag（我们）在 max_lag=0 时等价：date≥ref ⇔ lag=0。
2. **big_kcache / emotion_series**：bds **没有**这两个调用点——差异 = bds 的覆盖缺口，
   正是 DATA-01 要补的洞（spec 现状证据 1/3：kcache 冻三天下游照跑、emotion_series 断供
   无人知晓）。不是口径分歧。
3. bds 的 24 处调用本期**只看不改**（spec 非目标），P1 收编时把它们逐个指向 freshness_core
   并保留各自 date_field 语义即可（映射关系已在本节验证）。

## 6. 踩到的坑（实跑抓出，非想象）

1. **幂等 state 初版重复告警**：用「昨日 status」判新增触发，同日重跑覆盖当日记录后「昨日」
   变空 → 同一 fatal 每次重跑都告警。实跑反例 A 第 2 跑抓出。改成 line_health threats 段的
   `fatal_active` 持续标志位后，第 2 跑零输出、exit 仍 1。
2. **`generated_at` 时区标错**：`datetime.now(utc)+8h` 是可变时区把戏——钟点移了但 tz 标签
   还是 +00:00，违反 INTERFACES I0「ISO8601 带时区」。改 `timezone(timedelta(hours=8))`，
   现在输出 `2026-10-20T11:57:56+08:00`。（line_health 有同款 wart，未动它，记 P1。）
3. **kcache 日期字段不是 `date`**：新浪 schema 用 `day`，且 21 个文件里 18 个停在 10-13
   （3 个 10-19）——目录模式取最大值语义下整体=10-19 ok，但「部分文件停更」这一事实被
   max 掩盖，与 blindspot-2026check 的「僵尸待裁决」记录一致，故 severity=warn 并在报告
   明细里可见单文件层面不管。P1 退市/停更白名单时一并处理。
4. **verify.sh 在本容器跑不起来**（既存，非本卡引入）：解释器发现只试
   `/opt/hermes/.venv/bin/python` 与 `python3`（3.14.7，site-packages 空，无 yaml/numpy，
   正是 #330 的 ABI 环境），两个都没有 pyyaml → 直接退出 1。本卡全部验证改用
   `.venv/bin/python` 单跑 plan_lint/py_compile/pytest 完成。是否把 fenjue venv 加进
   verify.sh 候选列表，属基建改动，留给用户裁决（改它超出 DATA-01 的「唯一改动既有文件
   是 ops_briefing」声明，故未动）。
5. tests/golden/_cases.py 与 test_golden_master.py 两个既有文件的修改未预存 .bak（约束 3
   的「等」字漏了它们）；两者均在 git 跟踪内，`git diff` 即回滚路径，且改动是纯追加
   （一个 case + 一个测试函数）。ops_briefing.py 与 backlog.yaml 的 .bak 已按约束预存。

## 7. 遗留项（明确没做/不确定的）

1. **生成端未接线**：本卡只造了监控机与两个消费面（作战单渲染行已接；20:40 面板读
   data_health_report.md 是自然消费，无需改 dashboard）。**谁来每天跑 data_health.py 未定**
   ——新增/改 cron 需用户裁决（权限边界）。候选：挂进既有 18:35 regime_daily_append 班末尾
   或 20:40 面板班开头。没跑过任何 cron 实挂。
2. **P1 候选**（spec 非目标，未做）：build_daily_state 24 处 freshness 收编到 freshness_core；
   退市/停牌 186 只白名单与覆盖率指标化（本期只看末端日期）；熔断泛化（fatal 时给下游一个
   机器可读的「别信我」信号，现在只有人读报告）；seam 指标化。
3. **unknown_date 是否进 exit 1** 是 §2-2 的裁决点，目前按 spec 字面不进。
4. **trade_calendar 缓存只有偶数年**（2020/2022/2024/2026）：若某数据集末端日期落到无缓存
   年份，trading_days_between 会 raise → exit 2（按「不许猜」设计如此，不是 bug，但第一次
   遇到时会被当成基建错误报警，届时补对应年份缓存即可）。
5. **xrules_state 当前 stale（lag=1，末端 10-16）** 是真实状态，是否重跑 xrules_daily 由用户
   决定——监控机纪律是只告警不自动重跑。
6. line_health.py 的 `bjt_now()` 同款时区 wart 未修（不在本卡范围）。
