---
name: morning-briefing
description: 按持仓出开盘前决策早报（HTML + PDF），首次 full、日常 fast 增量。触发：跑早报/生成早报/早报/开盘前简报/今日决策报告/morning brief
---

# Morning Briefing（持仓早报）

## 文件结构
```
morning-briefing/
  SKILL.md                        ← 主文件（执行逻辑，本文件）
  paths.py                        ← 路径与凭证解析（三段：env → ~/.config/morning-briefing/ → skill 目录）
  fd_client.py                    ← finance-data 统一取数入口（候选解析 + fd() 子进程封装；覆盖场景一律走这里，直连仅兜底）
  module_spec.py                  ← **模块标准**：M1–M6 要什么字段/数据哪来/怎么渲染
  run_data.py                     ← **取数 runner**：六个 fetcher 跑一遍，落盘即登记
  registry.py                     ← **数据登记**：取数落盘顺手写三块（信源/时间/口径）
  registry_check.py               ← 出报后对表：版面上的数字能不能指回登记
  brief_format.py                 ← 版面规则（幂等的一道 pass）
  positions.py                    ← 持仓 SSOT 解析与校验
  onboarding.py                   ← **首轮引导**：无真实持仓时问板块/标的/权重并写盘（--status 判断要不要问）
  positions.example.yaml          ← DEMO 持仓（**跨市场**：A股2 / 港股2 / 美股2），用户复制到 ~/.config 后改
  portfolio.py                    ← 组合层：多周期收益 / 贡献度 / 集中度 / 持仓盈亏
  flows.py                        ← 资金行为面：主力净流入 / 龙虎榜 / 大宗 / 两融 / 股东增减持
                                     + 市场级雷达：行业与个股净流入流出 TOP / 龙虎榜全榜 / 机构席位
  tape.py                         ← 盘口面：内外盘(主动买占比) / 量比 / 换手 / 振幅 / 收盘位置 / 委比（三市场 + 台股都有）
  snapshot.py                     ← 每期快照 + 7 天窗口增量（「昨天到今天多了什么」的唯一来源）
                                     + 历史版本归档；归档那一步顺手出 PDF
  export_pdf.py                   ← HTML → PDF（headless Chrome + 打印覆盖样式，A4 横向）
  events.py                       ← 持仓事件流：SEC 8-K·Form 4 / A股公告（带类型分级）
  deepdive.py                     ← 个股 deep dive：分财年估值阶梯 / 增长轨迹 / 高管增减持方向与金额
  data_pipeline.py                ← 数据拉取 + 时间戳自检 + Sanity Check + 组合层
  pe_engine.py                    ← 估值引擎（真 PE 分位 + 价格分位，两个字段分开）
  search_finance.py               ← **卖方研报检索**：走公网数据源网关，无端点可配；出参无评级字段
  narrative.py                    ← **叙事层**：M5 主线 Deep Dive + 子块 B + M6 事件日历；
                                     正文只许写 {{fact_id}}，裸数字一律拦下
  macro_monthly.py                ← 月频宏观（CPI/PPI/PMI/M2/社融/非农），官方端点直连，零 akshare
  series.py                       ← 纯标准库序列计算 + KPI 卡 30 天轨迹线数据
  research_radar.py               ← 旧版研报雷达（要自配端点）；**新期次走 search_finance.py**
  modules.md                      ← M1–M6 输出格式 & HTML结构规则（v4.4）
  DESIGN-LANGUAGE.md                   ← 设计语言：十法则 / 色板 / 组件目录 / 中文书写规范(§5b) / 电报体中文写作规范(§5c) / 生成前自检
  reference.md                    ← 数据源索引 + 月频快照规则 + pe_snapshot手填指引
  media-sources.md                ← **Tier-1 外媒叙事源**：可达性实测表 + 检索纪律 + query 模板
  morning_brief_template.html  ← v4.2 HTML模板（K IC Memo 语法，模板与参考样例同一份）
```

**不在 skill 目录里的**（个人数据，放 `~/.config/morning-briefing/`，永远不会被同步到云端 skill 缓存）：

```
~/.config/morning-briefing/     ← 新装就用这个名字
  positions.yaml        真实持仓；没有它**先问用户**（见执行顺序 0a），不自动跑 DEMO
  pe_snapshot.json      手填 Non-GAAP EPS；没有它估值信号整列是「—」
  secrets.json          {"xueqiu_token": "..."}；也可用环境变量 XUEQIU_TOKEN
  state/                跨期状态（研报增量已读表）
```

改名前叫 `~/.config/morning-brief/`（少个 ing）。**存量用户不用搬**——`paths.py`
的 `config_dir()` 在新目录不存在、旧目录存在时自动回落旧的；两个都在则用新的。

---

## 依赖：生产路径**零第三方包**（2026-09-17 起）

跑早报只需要 **py3.9+ 标准库**，外加系统上的 `curl`。干净 venv 实测：不装任何第三方包
直接跑完整 `data_pipeline`，23 只行情 + 中国资金面 + 中债曲线 + 两融余额全部出数；
site-packages 13 MB（仅 pip 自身），而装回 pandas/numpy/yfinance/akshare/pytz
是 244 MB —— **省 231 MB**。

| 能力 | 实现 | 说明 |
|---|---|---|
| 序列计算（均线/分位/52W/TTM EPS） | `series.py` | 纯标准库，与 pandas 逐值对账（`test_series.py`） |
| 行情历史 | `fd_client.kline()` → finance-data | 付费授权源优先，免费层兜底 |
| 中国宏观（回购/国债/两融/南向） | `cn_macro.py` | 官方源优先：中国外汇交易中心、沪深交易所 |
| A股资金行为（龙虎榜/大宗/两融/股东） | `flows.py` | 东财 datacenter JSON 直连 |
| HTTP | `http_util.py` / `flows._get_json` | **curl 优先、urllib 兜底** |

**可选**（缺了只影响对应功能，不阻塞）：`pysnowball`（中概 ADR 走雪球，需 token）、
`akshare`（仅 `cn_macro.py` 的 `__main__` 对账块用）、`pandas`（仅 parity 测试用）。

⚠️ **`curl` 不是可有可无的**：东财几个端点认 **TLS 指纹**，Python 侧（requests 与 urllib
都一样）握手就被拒，改请求头没用，只有 curl 能过。没有 curl 时 A 股资金行为面整块 mask。
反过来 **FRED 拒绝浏览器 UA**（带 `Mozilla/5.0` 一律空回复，去掉才通，且失败长得像超时）
—— 所以**不设全局 UA，按源配**。

---

## 触发条件
用户说 "跑早报"、"生成早报"、"morning brief"、"早报"、"开盘前简报"、"今日决策报告"

---

## 🧭 跑一期早报 —— 四步，按顺序

先把这四步看完再动手。**第 2 步不是可选项**：M1–M4 全是价格与资金面，
而 M5 主线 Deep Dive 要的是订单、产能、认证、客户集中度这类产业事实
——**价格数据里一个都推不出来**。跳过第 2 步，M5 就会退化成「事件流 N 条」，
版面看着满、深度是空的。

### 第 1 步 · 取数字（全脚本，不联网判断）

| 跑什么 | 产出 | 给谁用 |
|---|---|---|
| `python3 run_data.py <run_dir> [--fast\|--resume\|--only a,b]` | `data/{pipeline,tape,flows,events,deepdive,pe}.json` | M1–M4 的全部数值 |
| `python3 series.py <run_dir>` | `series.json`（5×30 天） | KPI 卡右侧那条轨迹线 |
| `python3 macro_monthly.py <run_dir>` | `data/macro_monthly.json` | `meta.monthly_macro`（full 模式必填） |

**哪个字段从哪来、缺了怎么办**：`python3 module_spec.py fields`（M1–M6 的唯一定义）。
取数即登记 —— 落盘这一刻就写进 `_data_registry.json`，不事后对账。
**不要自己拼临时取数脚本**，理由见 §「取数：跑 run_data.py」。

### 第 2 步 · 检索信息（产业层，必跑）

两条通道**叠加**，不是二选一：

| 通道 | 命令 / 工具 | 拿什么 | 已知边界 |
|---|---|---|---|
| 卖方研报（**补充层**） | `python3 search_finance.py <run_dir>` | 机构／标题／发布日／正文 | 入库有滞后（实测约 2–3 周），**出参没有评级与目标价字段** |
| 公开检索（**叠加层**） | WebSearch | 研报库滞后区间内的评级与目标价变动、事件日历、宏观底色 | 二手转述，必须交叉核 |

**每期至少要搜到这三样**，缺了就在版面上写明缺什么：

1. **每条主线的两段**——①基本面：订单／产能／认证／客户集中度这类**可证事实**；
   ②风险与最该盯的一件事：一个**可证伪**的观察点（下一期能结算）。
2. **事件日历**——财报日、定期报告窗口、议息日程。日期要落到可引用来源，不凭印象写。
3. **宏观底色**——利率与政策方向。这条必须与本期 T1 数据对得上
   （例：议息隐含概率用 `pipeline.json:fomc_implied` 自己算一遍，再与外部报道对照）。

搜索纪律：一条查询 = 一个主体 + 一个具体问题（`光模块 1.6T 需求与价格`），
不要只写公司名；查到的**精确数字一律按第 3 步登记**，交叉核不出第二来源就不写那个数。
版面上的信源写「公开检索」与**具体那一篇报告**，不写取数工具名。

### 第 3 步 · 写叙事层（登记制，防编造就靠这一步）

把第 2 步的结果写进 `narrative.json`，然后

```bash
python3 narrative.py <run_dir> <narrative.json>      # 校验 + 落盘 + 登记
python3 narrative.py x <narrative.json> --check      # 只校验，不落盘
```

三条硬规矩，由脚本强制、不靠自觉：

- **正文只能写 `{{fact_id}}` 占位符，不能直接敲数字**。漏一个裸数字就报错。
- 每个 fact 三块齐全（信源／时间／口径）；**外部来源另需 `cross_check.source`**，
  核不出第二来源 → 这个数不进版面，进 `gaps`。
- 深度卡必须两段齐全（基本面 / 风险），只有一段 = 单边推介，直接判失败。

### 第 4 步 · 跑 builder

```bash
python3 build_morning_brief.py <run_dir>/brief.json                    # 结构闸 + 出 HTML
python3 brief_format.py <run_dir>/<日期>_Morning_Brief.html --spark <run_dir>/series.json
BRIEF_PDF_PAGED=1 python3 export_pdf.py <run_dir>/<日期>_Morning_Brief.html
```

三个脚本各管一段，**不要把版面规则写进生成器**：生成器只产结构化内容，
版面由 `brief_format.py` 统一固化（幂等，可重复跑），纸张由 `export_pdf.py` 决定。

---

## ✅ QA —— 四道闸，一道都不许跳

出报不是「跑完就交」。四道闸各自只回答一个问题，**互不替代**
——前三道全过，SNAPSHOT 仍然可以是一堆数字（每个数都有来源、块也在、排版也对），
所以才要第四道：

| 闸 | 命令 | 回答的问题 | 不过怎么办 |
|---|---|---|---|
| **结构** | `python3 module_spec.py check <run_dir>` | 六个模块该有的块有没有 | 补块；`REQUIRED` 缺了就是这期不合格 |
| **版面** | `python3 brief_format.py <html> --spark <series.json>` | 字号／间距／两栏／轨迹线对不对 | 看它打印的 `spark_skipped` 等统计，**统计为 0 就是没生效** |
| **数字** | `python3 registry_check.py <run_dir>` | 版面上每个数字有没有来源 | 要么补登记，要么把那个数从版面拿掉 |
| **表达** | `python3 summary_gate.py <run_dir>` | SNAPSHOT / C-ASK 是**结论**还是数字台账 | 把「谁涨了多少」换成「所以呢」；数留一两个当锚 |

`build_morning_brief.py` 自带结构闸，不过会直接拒绝交付（HTML 仍写出供查看）。

### 怎么判断闸没有白跑

闸报「全过」有两种可能：**真的干净**，或者**它根本没检查到东西**。后者更危险，
因为它长得跟前者一模一样。三条判据：

1. **看它报的计数，不只看颜色**。`registry_check` 要看「实查 N 个」是不是接近版面数字量；
   `brief_format` 要看 `spark_added` 是不是 5 条而不是空列表 —— 实测踩过：
   `--spark` 把序列名当卡片标签传进去，5 条轨迹线全落空，而命令**正常退出**。
2. **闸报 0 要做变异验证**：故意改坏一个数（或删一条登记），确认它这次报错；
   不报错说明这条规则没接上。
3. **表达闸的判据是「有没有下判断」不是「数字多不多」**。只卡数字会逼出另一种坏文体
   ——把数删光剩空话。它同时要求每条有因果/转折词，且并列的「名称+数字」不超过三组。
4. **手工登记条目数 ≠ 0**。`registry_check` 的三块校验若「没有对象可检查」，
   那是空过不是通过 —— 它会分开写，别读成绿灯。

### 闸是在**一期**上拟合出来的 —— 必须跑全语料

```bash
python3 regress.py            # 历次产物逐份跑闸 + 打印量级指纹
python3 regress.py --diff     # 只看相对基线的变化（改闸之后先跑这个）
python3 regress.py --baseline # 确认变化合理后再更新基线
```

summary_gate / render_check / registry_check 的阈值与词表，都是在某一期上拟合的
——那就是「作者的调参集」，天然测不出新规则的副作用。同型教训在 hk-ipo-lens 上
付过代价：作者用 10 家做的对照全对，拿 128 份全语料复跑才露出 4 家静默回归。
**实测有效**：补完 render_check 后跑全语料，立刻发现表达闸把黄金件误报了
——「再上一个台阶 → 10Y 重新推过 5%」是有因果的，而词表只认汉字不认箭头。

判「闸会不会误伤」看**量级变化**不只看 pass/fail：`regress.py` 逐份打印
模块/表格/卡片/深度卡/轨迹线/PE 单元/数字量的指纹，指纹塌一截就是整块没渲染。
变异验证过：抹掉 5 条轨迹线，量级闸立刻报，而 pattern 闸一条都不响。

### 改了脚本必须跑回归

```bash
python3 tests/test_brief_format.py     # 结构/版面/登记/叙事层/exec 模块契约，60+ 条断言
python3 run_data.py /tmp/x --self-test # 取数管线接线自检，不联网，秒级
```

每修一个 bug **同时补一条断言**，断言里写清「当初是怎么坏的」——
这些 bug 的共同点是**不报错**，只有断言能挡住它们第二次发生。

---

## 📂 按需加载（不要一次全读）

SKILL.md 本身要读完；**其余文件按下表在需要那一步再读**。整套读完约 93KB，
而绝大多数期次真正用得上的不到三分之一 —— 一次全读的代价是每期都付，
收益只在少数分支上出现。

| 文件 | 什么时候读 | 什么时候**不要**读 |
|------|-----------|-------------------|
| `modules.md`（37KB） | 出报那一步，且只读你这期真正要渲染的 M 段 | 取数阶段、fast 模式继承的模块 |
| `DESIGN-LANGUAGE.md`（10KB） | 要**改版面规则**时 | 日常出报 —— 版面已由 `brief_format.py` 固化，不需要每期重读设计语言 |
| `media-sources.md`（10KB） | 要做叙事检索（M2 / 研报雷达）时 | 纯增量的 fast 期，叙事层从上一份 full 继承 |
| `reference.md`（6KB） | 取数报错要查数据源口径、或手填 `pe_snapshot.json` 时 | 取数正常时 |
| `positions.example.yaml` | 只在首轮引导要给用户看示例结构时 | 已有真实 positions.yaml 时（读它只会让你把示例票当成持仓） |
| `references/legacy-full-steps.md` | 排查「以前是怎么跑的」时 | 正常期次 —— 它是历史留档，不是当前流程 |

脚本不需要读源码就能用，命令写在 §「跑一期早报」与 §「QA」里：
`run_data.py` / `series.py` / `macro_monthly.py` / `search_finance.py` / `narrative.py` /
`build_morning_brief.py` / `brief_format.py` / `export_pdf.py` /
`module_spec.py` / `registry_check.py` / `snapshot.py` / `onboarding.py`。
要改它们的行为再读源码，并且**改完先跑** `python3 tests/test_brief_format.py`。

---

## ⚡ Step 0 — 模式自动判定（不要问用户）

触发后**第一件事是扫本地缓存**（`python3 snapshot.py`），模式由缓存状态定，
**不问 Q/F** —— 用户要的是早报，不是先做道选择题：

```
无快照（第一次跑）          → full   建立基准，所有格子都算一遍
有快照（增量，日常绝大多数） → fast   默认；只重拉高频，thesis 层继承
用户显式说「跑完整/full/深度」 → full   覆盖默认
距上次 full > 5 天 或 周一   → full   基准过期，自动升级
```

**两种模式的分工（这是本 skill 的核心约定）**：

```
fast（增量，≈4 分钟）—— 只更新「今天会变」的东西
  重拉：行情与盘口 / 利率曲线 / 中港资金面 / 主力资金流 / 龙虎榜 / 宏观与个股新闻 / 事件流
  继承：核心分歧、一致预期、逐票 thesis、估值阶梯 —— **一律不重新检索**，
        从最近一份 full 原样带过来，版面标「沿用 MM/DD 判断」
  理由：thesis 是周／月尺度的判断，每天重跑一遍既费时又会让结论无谓地抖动；
        日报要回答的是「昨天到今天变了什么」，不是每天重新论证一次持仓逻辑。

full（全量，≈12 分钟）—— 重建基准
  在 fast 之上额外做：每票核心分歧重新检索（多方/空方/未决三面）、
  pe_engine + deepdive 分财年估值阶梯、研报雷达与逐票公告。
  产出的 snapshot 成为后续所有 fast 的继承基准。
```

⚠️ fast 跑 `snapshot.carry_forward()` 返回 `need_full=True`（没有 full 基准可继承）
→ **自动转 full**，不要拿更旧的东西凑，也不要让 thesis 层的格子空着。

---

## ⚙️ 数据获取规则

```
✅ 持仓名单/权重   →  positions.py（唯一真源；两个消费方不许各写一份）
✅ 组合层          →  portfolio.py（确定性；LLM 只解释不重算）
✅ 价格/技术/估值  →  data_pipeline.py（finance-data 统一入口，付费授权源优先）
✅ 利率绝对值      →  data_pipeline.py（美债 treasury.gov CSV + 中债 bond_zh_us_rate，两条曲线并列）
✅ 利率 1D/7D/30D  →  data_pipeline.py（**自然日锚定**，anchor_dates 必须写进 .fn）
✅ 中港资金面      →  data_pipeline.py（南向资金 / 两融余额 / 两市成交额；北向永久 mask）
✅ 隔夜亚洲指数    →  data_pipeline.py（骨架自带：1306.T(TPX 代理) / ^N225 / ^HSI / ^HSCE /
                      000001.SS / 399001.SZ / ^TWII / ^KS11。^TPX/^TOPX 无数据，TPX 用 ETF
                      代理，同 HSTECH 用 3067.HK 的惯例）
⏳ 股指期货/板块代理 →  ES=F·NQ=F·RTY=F 与 Hardware/Internet/Software 免费代理**待验证**，
                      验证前标「待补」，不拿 ETF 收盘价顶替期货口径
✅ Fear & Greed    →  data_pipeline.py（alternative.me API）
✅ FOMC定价        →  data_pipeline.py（Fed Funds Futures）
✅ PE估值          →  pe_engine.py（pe_snapshot.json + finance-data 一致预期；美股走 S&P，带财年标签）
✅ 资金行为面      →  flows.py（A股东财直连；港美无免费日频流 → mask）
✅ 市场资金流雷达  →  flows.py compute_flows(...)["market"]（**不按持仓过滤**，行业/个股/龙虎榜）
✅ 盘口与量能      →  tape.py（三市场 + 台股都有；委比在收盘后只是快照，口径字段自带）
✅ 7 天增量        →  snapshot.py（每期 save，下期 diff；**首期无对照就写「首期无对照」**）
✅ 持仓事件流      →  events.py（美股 SEC 直连；A股 finance-data cn.announcements 主路＋东财 ann 兜底；港股端点已变 → mask）
✅ 逐票深度        →  deepdive.py（S&P 一致预期分财年：finance-data us.consensus 主路＋直连兜底；SEC 高管增减持方向金额）
✅ 券商研报/评级   →  research_radar.py（研报检索，端点需自配）+ 个股新闻。
                      **研报原文无 access**：版面只许写「内容来自新闻检索，可能不全」，
                      不许写「研报库滞后 N 天」「窗口内 0 篇」这类内部实现细节
✅ 新闻叙事 M2     →  **先读 media-sources.md**。分两层：本地取数 skill（未随公开版提供）出个股新闻，
                      Tier-1 外媒（Bloomberg/CNBC/SCMP/KoreaHerald/Nikkei）出宏观·地缘·跨市场。
                      ⚠️ reuters/wsj/ft/apnews/economist/barrons/marketwatch **本环境 UA 被拒**，
                      放进 allowed_domains 会让整条调用 400；要原文走浏览器控制 skill（CDP，未随公开版提供）。
                      ⚠️ WebSearch **没有发布时间过滤**，每条日期必须逐条确认，确认不了就不进日报
✅ 月频宏观        →  WebSearch（到期刷新）
✅ finance-data 覆盖场景 → 一律走统一入口（fd_client.py；FINANCE_DATA_DIR →
                      ~/finance-data → ~/.kimi-code/skills/finance-data → 同级目录），
                      直连路径仅作兜底：一致预期 us/cn/hk.consensus、A股公告 cn.announcements
                      登记例外（无对应场景，保持直连）：中国宏观面 cn_macro 官方源、
                      SEC 8-K/Form 4、东财资金流/盘口、利率/FOMC/Fear&Greed

✅ 落盘          →  **一律走 registry.dump_with_registry(run_dir, name, payload)**，
                      不要再直接 json.dump 到 data/ —— 那条路径绕过登记，
                      出来的数没有三块，出报后只能靠「值撞上」倒推来源

❌ Yahoo Finance WebFetch  →  禁止（时间戳缓存不一致）
❌ WebSearch价格snippets   →  禁止（时间戳来源不明）
❌ CME FedWatch WebFetch   →  禁止（403）
❌ Motley Fool / 24-7 Wall St / Kiplinger 这一档  →  M2 有研报可用时不要再引；
   研报端点未配置/不可达时只可作新闻检索来源，且出处行必须写明层级（「内容来自新闻检索（T3 媒体），可能不全」）—— 不得与研报层级混排
```

---

## 📦 LAST_KNOWN_DATA 快照

```
模块              最后更新日    数据期    快照摘要                     触发条件
───────────────────────────────────────────────────────────────────────────────
美债/VIX/大宗      每次更新      当日      见M1/M3输出                  每次运行
Watchlist          每次更新      当日      见M4输出                     每次运行
中国PMI            [日期]        [月份]    制造业:— / 非制造:—          月末重置
中国CPI/PPI        [日期]        [月份]    CPI:—% / PPI:—%             次月10日重置
社融/M2            [日期]        [月份]    社融:—亿 / M2:—%            次月15日重置
美国非农/失业率    [日期]        [月份]    非农:—万 / 失业率:—%         月初第一周五重置
FOMC会议纪要       [日期]        [日期]    利率: 4.25-4.50%             下次会议日重置
财报日历           [日期]        本周      见M5快照                     每周一重置
```

月频快照规则详见 `reference.md`。


---

## 🧱 三道闸的细则

> 怎么跑、怎么判它没白跑 → §「QA」。本节只写每道闸**内部的规则**。

builder 出完 HTML，**依次跑这三个**，都过了才算这期早报可交付：

```bash
python3 module_spec.py    check <run_dir>     # 结构：该有的块有没有
python3 brief_format.py   <run_dir>/<date>_Morning_Brief.html
python3 registry_check.py <run_dir>           # 数字：每个数能不能指回登记
```

### 0. module_spec.py — 模块标准

M1–M6 每块「**要什么字段 / 数据哪里来 / 怎么渲染 / 缺数怎么办**」的唯一定义。
在它之前，同一个模块这期有下期没有、这期叫「读法」下期叫「解读」、估值列是「—」
却没人知道是数据缺还是没跑起来 —— 全靠人记。

- `REQUIRED` 缺了 = 这期不合格，不许交付
- `OPTIONAL` 缺了只提示，但**版面必须写明缺什么、为什么**（这一条由 modules.md 的信息缺口约定管）
- `python3 module_spec.py fields` 打印完整字段清单；写 brief.json 的脚本照着填

### 1. brief_format.py — 版面

把版面规则从「每期靠自觉」变成「一道脚本」。字号、块间距、表格与解读卡的两栏对齐、
同形状表格列宽统一、长段落切 bullet、告警条 marker、打印 A4 横向分页，全在这里。
**幂等**，重复跑不会叠加。规则改动改这个文件，不要去改某一期的 HTML。

sparkline 传 `--spark`（`{"标签": {"vals": [...], "zero_base": false}}`）才画，
且**末值必须与卡面数值一致**，对不上就跳过那张卡 —— 一条跟卡面数字打架的曲线
比没有曲线更糟。

### 2. registry.py / registry_check.py — 数字必须有来源

**登记制（取数那一刻写），不是事后对账。**

取数层每个 fetcher 的产出都经 `dump_with_registry()` 落盘，每个数值叶子当场登记三块：

```
信源  source / source_type / source_tier
时间  as_of            —— 这个数说的是哪一天的事（filled_at 是抓取时刻，两者不同）
口径  unit + computation —— 算出来的写清怎么算；原报即此值显式写 null
```

新闻/研报/WebSearch 的数字**在写进版面之前**调 `registry.register(...)` 登记；
三块缺一当场抛，不留到出报后才报。T3/T4 另需 `cross_check` —— 交叉核不出来
就别写那个精确数（定性描述不需要来源，精确数字需要）。

运行参数与诊断计数（`window_days` / `xq_ok` 这类）**不进 registry**：
它们不是数据，登记它们只会污染值空间 —— 版面上任意一个 7 都能"匹配"到 window_days=7。

出报后对表：

```bash
python3 registry.py verify <run_dir>      # 每条登记的三块齐不齐
python3 registry_check.py <run_dir>       # 版面上的数字能不能指回登记
```

`registry_check` 会分开报「登记命中」与「仅对账命中」——**只有登记命中才算真有来源**；
对账命中只能证明「这个值在取数结果里出现过」。没有 registry 文件时整体退回对账模式，
输出里会明说。

未登记的数字用 `--emit-skeleton` 吐成 `status: unfilled` 骨架（只生成空位，
不替你填来源）。填不出来源的，把那个数从版面拿掉。

#### 旧版说明（对账模式）

**这道闸是本 skill 的底线：不能编造。**

`<run_dir>/data/*.json` 里的数值自动进 registry（来源 = JSON 路径 + pulled_at）。
新闻/研报/WebSearch 读来的数字必须手工登记到 `<run_dir>/_data_registry.json`：

```json
{"entries": [
  {"value": 6640, "label": "ORCL RPO 亿美元", "tier": "T4",
   "source": "Reuters 2026-09-10 财报报道", "url": "https://…",
   "cross_check": {"source": "公司 IR 新闻稿", "url": "https://…"}}
]}
```

tier 纪律（对齐 CLAUDE.md §3a 的数据获取优先级）：

| tier | 来源 | 要求 |
|------|------|------|
| T0–T2 | 取数层 / 专用 router / 已知 URL 直取 | 单源即可 |
| T3–T4 | CDP 抓取 / WebSearch / 新闻检索 | **必须带 cross_check**，否则本闸判失败 |

对不上来源的数字，只有两条路：**补 registry 说明出处**，或者**从版面上拿掉**。
没有第三条路 —— 不许留在版面上等读者自己判断真假。

⚠️ 交叉核不出来就别写那个精确数。「甲骨文 RPO 大幅增长」不需要来源，
「RPO 6,640 亿美元」需要。定性描述不受这道闸约束，精确数字受。

回归测试：`python3 tests/test_brief_format.py`（12 条，含幂等、文本零丢失、
两栏对齐、列宽统一、打印分页、sparkline 拒画、T3/T4 闸）。改这两个脚本前先跑一遍。



---

## 🔌 取数细则：跑 run_data.py，不要自己拼临时脚本

```bash
python3 run_data.py <run_dir>            # full：events 窗口 7 天
python3 run_data.py <run_dir> --fast     # fast：events 窗口 3 天
python3 run_data.py <run_dir> --resume   # 断点续跑：已落盘的 fetcher 跳过不重拉
python3 run_data.py <run_dir> --only events,pe   # 只补跑点名步骤
```

一次跑完六个 fetcher 并**落盘即登记**：

```
data_pipeline.py → pipeline.json    利率曲线 / 中港资金面 / 行情技术面 / FOMC 定价
tape.py          → tape.json        盘口与量能
flows.py         → flows.json       资金行为面 + 市场资金流雷达
events.py        → events.json      持仓事件流
deepdive.py      → deepdive.json    分财年估值阶梯 / 高管增减持
pe_engine.py     → pe.json          估值引擎
```

⚠️ **不要再每期临时写一份 run_brief_data.py。** 那种脚本有两个老问题：
绝对路径写死（换机器就废），以及直接 `json.dump` 到 `data/` —— 绕过登记，
出来的数没有三块，出报后只能靠「值撞上」倒推来源。

单步失败**不中断**：记进 errors 继续跑下一个（早报的设计是「缺哪块标哪块」），
但失败会显式打出来，不静默跳过。跑完自动 `registry.verify`。

⚠️ **大名单一律批处理，不在对话里逐只过**（2026-09-18 起，与 hk-ipo-lens 分段落盘
续跑纪律、portfolio-review 大输入闸同口径）：几十只持仓的事件流/深挖/估值，
一律由 runner 脚本一遍跑完，**禁止在对话里逐只读、逐只改、逐只对**——逐只处理
几十只持仓会把步数烧穿（hit steps limit），出错也不可追踪。中间产物全部落盘
（`data/*.json` + registry 三块），任务被步数或时长打断时 `--resume` 重发同一条
命令断点续跑：已落盘的 fetcher 自动跳过，不从头重来、不靠记忆重建；只缺哪几步
用 `--only` 点名补跑（点 deepdive/pe 会连带重跑 pipeline——它俩要 pipeline 的
内存 tech，盘上 JSON 补不回来）。持仓达几十只或 full 全量深挖前，开跑先告知
用户本轮处理量与预期时长（fast ~4 分钟 / full ~12 分钟基线）。

自检（不联网，秒级）：`python3 run_data.py /tmp/x --self-test` —— 用桩替掉所有
fetcher，只验管线接线：产物落了没、登记了没、三块齐不齐，外加 --resume / --only
两条路径。已进回归测试 P1–P7。

---

## 🚀 执行顺序（fast / full 的差异）

> 主流程四步见 §「跑一期早报」。本节只补 fast 与 full 的**差异**与冻结规则。

### Step 0（每次都跑）— 持仓与模式

```
0a  **先扫本地缓存，判断这是首次还是增量。** 任何取数之前跑：
      python3 snapshot.py      # 打印：快照数 / 最近一份 full / 历史版本清单
    ├ 有快照 → 这是**增量**。只重拉高频格子，低频格子从最近 full 继承（版面标
    │          「沿用 MM/DD 判断」），M2 开头先写「昨日回看」逐条结算上期 prev_focus。
    │          **不要当成首次再全量跑一遍。**
    └ 无快照 → 首次。走 full 建基准；增量格子写「首期无对照」，不留空、不编。

0b  **持仓名单：没有就问，不要替用户猜 —— 但只问这一次。**

    先跑一句判断要不要问：
      python3 onboarding.py --status
    ├ first_run=no  → 已有真实持仓。**不要再问**，只回显一行读到的名单让用户确认没跑偏。
    └ first_run=yes → 没有真实持仓（positions.example.yaml 只是示例，2026-09-17 起
                      不再自动回落，要用得显式 BRIEF_USE_DEMO=1）。问下面三句，
                      **一次问完**，不要一句一轮：

      ① 主要关注哪些板块？
         例：AI 硬件/光模块、存储、AI 电力、电气设备、Neocloud/IDC、中国互联网、消费
      ② 具体盯哪些票？给代码即可
         A股 300308.SZ ｜ 港股 0700.HK ｜ 美股 NVDA ｜ 日股 7011.T ｜ 台股 3008.TW ｜ 韩股 005930.KS
         （含不含 A股/港股决定资金流、龙虎榜、南向那几块渲不渲染，由代码后缀自动判定，不必单问）
      ③ 有组合权重吗？
         有 → 按「代码 权重」给，合计 100%。出组合收益 / 贡献度 / 集中度 / 持仓盈亏
         没有 → 回「关注池」。只做名单跟踪，组合层整块 mask（**不假设等权**）

    拿到回答后**用 onboarding.py 写盘**，不要手拼 YAML（板块落 thesis 字段，M5 deep dive 会复用）：

      cat > /tmp/intake.json <<'JSON'
      {"currency": "USD", "positions": [
        {"ticker": "300308.SZ", "sector": "光模块", "weight": 0.20, "sf_query": "中际旭创 光模块"},
        {"ticker": "NVDA",      "sector": "算力",   "weight": 0.15, "sf_query": "NVIDIA datacenter"}
      ]}
      JSON
      python3 onboarding.py --write /tmp/intake.json

    硬规则（onboarding.py 写盘前会拦，别绕过）：
      · 权重**要么全填要么全不填**；半填被 positions.py 拒，别让用户跑完十几分钟才报错
      · 全填时合计 = 1.0（给百分数自动除 100）
      · 写完用 positions.load_positions() 回读校验，不过就改名 .rejected，**不留半份文件**
      · 落 paths.config_dir()，**不写进 skill 目录**（会被云同步）

    引导只做这一次。之后改名单/权重直接编辑那个 YAML，下一期生效 —— 不重跑引导，也不再问。

0c  模式已经在 0a 定了（无快照→full，有快照→fast），**不要再问用户一遍**。
    只在两种情况下偏离：用户显式说「跑完整」→ full；距上次 full > 5 天或周一 → full。
    开跑前回显一行：「本次 fast（增量），thesis 层沿用 MM/DD 的 full 基准」。
    ⚠️ fast 跑 snapshot.carry_forward() 若返回 need_full=True（无 full 基准）
       → **自动转 full 全量重建**，不要拿更旧的东西凑，也不要让 thesis 层空着
```

### fast 模式（~4 分钟）— 只更新高频

```
只重拉（每日高频，今天会变的）：
    利率曲线 / 中港资金面 / 行情与盘口 / 主力资金流 / 龙虎榜 / 宏观与个股新闻 / 事件流
继承自最近一份 full（周月尺度判断，**今天不重新检索**）：
    核心分歧、一致预期、逐票 thesis、分财年估值阶梯
    —— **版面必须标「沿用 MM/DD 判断」**，不许悄悄当成今天算的
⚠️ 不要"顺手"把 thesis 也刷一遍：那会让 fast 退化成 full，且结论每天无谓抖动。
   thesis 该更新的信号是 full 到期（>5 天）或出现了推翻它的事件，不是"反正都跑了"。

Step 1  exec data_pipeline.py + tape.py + flows.py（市场雷达可 board_top=4 收窄）
Step 2  Tier-1 外媒 2–3 条 query（宏观/地缘），个股新闻每票 1 条轻量
Step 3  snap = snapshot.build(..., mode="fast", focus=[...]); snap = snapshot.carry_forward(snap)
        need_full=True → 转 full
Step 4  delta = snapshot.diff(snap) → **M2 开头先写「昨日回看」逐条结算 prev_focus**
        （每期必跑 diff；名单换血不是豁免理由 —— added/removed 本身就是该结算的变化，
        零重叠时格式为「名单换血：退出/新进」，不是跳过）
Step 5  出报（M1–M6）→ snapshot.save(snap) → snapshot.archive_edition(html_path, date, "fast")
        └ archive_edition 会顺手打一份同名 PDF（交付件两份：HTML + PDF）
```

### full 模式（~12 分钟）— 全量 + 冻结

```
在 fast 全部步骤之上，额外做：
  · pe_engine + deepdive：分财年估值阶梯、高管增减持逐条
  · 每票「核心分歧」重新检索（WebSearch，多方 / 空方 / 未决三面）
  · research_radar + 逐票公告
  · snapshot.build(..., mode="full", debates={...}) —— **这一份成为后续 fast 的继承基准**
```

### 历史版本

```
snapshot.archive_edition(html, date, mode)  每期归档到 <state>/editions/YYYY-MM-DD_<mode>.html
                                            并在**交付件旁边**打一份同名 PDF
snapshot.list_editions()                    列历史版本（最新在前）
python3 snapshot.py                         直接看：快照数 / 最近 full / 历史版本清单
python3 export_pdf.py <早报.html>            单独补一份 PDF（BRIEF_NO_PDF=1 可全局关掉自动导出）
```


## ✍️ 措辞黑名单与叙述纪律（2026-09-17 起，任何一期生效）

这是**单独维护的清单区块**：措辞问题改这里，不进各模块契约。build_morning_brief.py
的门禁已接入本清单：A 类命中 = FAIL（不许交付），B / C 类与破折号 = WARN（逐条人工看）。
**黑名单管「禁什么」；通过禁令之后「怎么写」见 `DESIGN-LANGUAGE.md` §5c
电报体中文写作规范（v4.6，机构主语第三人称 / 量化强制 / 中文句模 6 式 /
术语与数字单位对照 / 评级动作固定说法）—— 两层叠加生效，互不替代。**

### 措辞黑名单（三类）

```
A. 直接操作建议 —— 一律改写为中性事实与风险陈述
   「建议：」「操作：」「操作上」「建议加仓 / 减仓 / 买入 / 卖出 / 不动」
   「可考虑买 / 卖」「止损 / 止盈」「买点 / 卖点」「追涨 / 追反弹 / 抄底 / 逃顶」
   「不加仓」「不加杠杆」
   替代表达：「风险点：…」「验证条件：…」「若 X 出现，则该判断失效」。
   例外：事实性买卖不是建议 —— 高管减持、主力净卖出、南向净买、公司回购是数据，
   照常写；黑名单管的是「让读者怎么做」的句子。

B. 极端定性词 —— 「唯一」「最…」（最大 / 最差 / 最强 / 最贵 / 首次…）
   必须带数据锚与限定范围，否则整句删除。
   写「本期最大」就要给比较对象与数值；给不了就不许写。

C. 强行英译 / 翻译腔 —— 逐字英译的句式一律改写为中文投研语感：
   「作为…的…」「进行了…的…」「是…的存在」、三个「的」以上的长定语链、
   一连串被动（「被定价」「被验证」「被重估」）。
   公司与板块用市场通用中文名，不硬译、不造绰号。
```

### 配套措辞纪律

```
- SNAPSHOT 每点一句话说清两件事：发生了什么 + 对持仓意味着什么。
- 不专业表述一律删：市场黑话与绰号（「压舱石」「易中天」这类）、口语化、情绪化表达。
- 全篇中文投研语感，少用破折号 —— 规范见 DESIGN-LANGUAGE.md §5b。
```

### 叙述纪律（无新闻不编因果）

```
- 凡不能对应到「当日或隔夜具体新闻 / 数据点」的解读性语句，一律删除。
- 无新闻时只陈述可核实事实（价格、成交、公告计数、披露内容），不补叙事。
- 有新闻支撑的解读必须写明对应事件：日期 + 事件名，
  形如「9/16 Fed 加息 25bp → …」，不写无出处的原因链。
```

### 注释纪律（注释性文字不进正文）

```
- 口径注释 / 方法说明（例：「窗口内未上榜 = 未触发披露阈值，不等于无异动」）
  一律进 .fn 编号脚注或页脚备注区；正文只留结论。
- 判断标准：这句话删掉后结论是否仍然完整？是 → 它是注释，挪到脚注。
```

---

## 📋 输出格式强制规则

```
【HTML输出】
- **不要手写 HTML —— 写 `brief.json`，由 builder 渲染**（2026-09-17 起）：
      python3 build_morning_brief.py <run_dir>      # 读 <run_dir>/brief.json
  schema 见该脚本文件头 docstring。理由：每期早报的 CSS / 骨架 / 脚本完全一样，
  手写等于每天重新产出约 100KB 样板，还要先读 85K 模板 + 37K modules.md。
  更要紧的是 `.up/.dn/.bup/.bdn/.flat` 原本逐格手判（一期两百多处）——
  现在传数值，由脚本按本文件的阈值算，**红涨绿跌，利率与股票同一套，无例外**。
  样式**不在脚本里复制**：builder 构建时从 morning_brief_template.html 读
  `<style>` 与 `<script>`，所以「改样式只改模板」依然成立，DEMO 角标也仍由
  模板自带脚本填。
- **builder 的两条内容硬闸（2026-09-18 起，降级路径同样适用）**：
  ① **PE 无财年锚即构建失败** —— 出现 PE 数值的同一句话必须带 `FY20xx`（或「20xx 财年」）；
     表格里**每个 PE 数值**要么自己带锚（写成「23.5x FY2027」），要么整列同锚时由列头带。
     锚直接取 `pe.json:*.fw_eps_fy`（引擎保证 `fw_pe` 有值即有锚，见 fy_anchor.py），
     不自己按财年制推。**表注不再算锚**（2026-09-18 收紧）：那期就是拿一段「美股与 ADR
     多为 FY2026；阿里为 FY2027；三菱重工 7011.T 为 FY2026」的笼统表注顶过了门禁 ——
     按财年制推断的约定不是逐只回传的事实，跨财年制标的横比差一整年盈利。
     pe_engine 不可用、改用其它口径填补时同样适用，不许绕开。
  ② **full 模式月频宏观必须逐项刷新** —— `meta.monthly_macro` 是 full 的必备字段：
     `cpi_ppi`（次月10日重置）、`social_financing_m2`（次月15日）、`cn_pmi`（月末）、
     `us_jobs`（月初首周五）各项带 `as_of`（YYYY-MM），重置日后数据期不得停留在上一期；
     `fomc_minutes` / `earnings_calendar` 至少要有 as_of 或说明。
     数据真未发布/顺延的，在该项 `note` 写明原因放行；**「下一期 full 补齐」不是豁免**。
- 两个模式统一输出 HTML 文件（YYYYMMDD_Morning_Brief.html）
- 版面契约仍以 morning_brief_template.html v4.2（K IC Memo 语法）为准
- ⚠️ **外层 chrome 一个都不能少**：`<body>` 下必须依次是
  `<div class="topband"></div>` 和 `<div class="page"> … </div>`，正文全部包在
  `.page` 里。`.page` 就是版心（max-width 1180 + 左右 44px 内边距）——**丢了它
  正文会直接贴满屏幕、左右零边距**（2026-09-17 那期实测丢过，三期出现三种结构）。
  这条有闸在兜：`archive_edition` / `export_pdf` 都会 `verify_and_repair()`，
  缺了就地补回并写 `<state>/html_repair.log`。**闸是兜底不是许可**，别依赖它。
- **交付件是两份**：HTML（主）+ 同名 PDF（转发/归档用，**流式一页到底**，
  1180px 宽、高度等于整篇 —— 目标是还原 HTML 的滚动阅读体验，不是印在纸上）。
  PDF 由 `snapshot.archive_edition(html_path, ...)` 自动出，不必单独调；
  只补 PDF 时跑 `python3 export_pdf.py <早报.html>`。
  ⚠️ archive_edition 要传**文件路径**而不是 HTML 字符串，PDF 才会打在交付件旁边。
  ⚠️ 流式 PDF 的验收断言是**恰好 1 页**；报「要的是流式一页，实际出了 N 页」
     说明量高没生效或正文超了单页上限，别忽略。真要分页设 `BRIEF_PDF_PAGED=1`。
  PDF 失败只打一行警告，不阻断交付 —— 但那一行必须报给用户，别当没发生。
- Quick模式: <body data-brief-mode="quick">（与归档/执行层所称 fast 为同一模式：版面属性写 `quick`，归档文件名用 `_fast`——两套命名指代相同，校验时勿混用）
- Full模式:  <body data-brief-mode="full">
- DEMO 持仓: <body data-brief-mode="quick" data-demo="1">（页眉自动出 DEMO 角标）
- 只填内容，不改 <style>；要新样式先查 DESIGN-LANGUAGE.md 有没有现成组件
- 禁止输出 markdown 表格作为最终报告格式

【v4.2 = v4.0 + 持仓层与研报层，排版语法不变】
- 内容怎么写、写多少、分几段，与 v4.0 完全一致；长叙述段与图下评论段照写
- .hdr-title / .hdr-sub / .panel / .read 全部是**可选**组件，不是必填字段
- 唯一保留的硬性项：每模块结尾 .src 出处行；口径存疑的数字进 .fn 编号脚注
- 新增硬性项：跑 DEMO 时页眉必须有 DEMO 角标；M5 子块 B 必须写明「来自新闻检索，可能不全」
- **报告正文不写任何工程内部名**：脚本名（*.py）、接口名、字段名、环境变量、文件名一律不进版面。（**页脚状态行豁免**：modules.md 规范要求的 `iv_snapshot.json` / `pe_snapshot.json` 状态标注属规定格式，不在此禁令内）
  出处行只写到**机构 / 数据集**这一层（如「S&P Capital IQ 一致预期」「SEC 公开申报」「券商研报库」），
  不写调用路径。读者是 PM 不是本工具的维护者。
- **对话与进度汇报同规（2026-09-17 起）**：跑报过程中的对话输出同样不外曝数据通道状态——「没有网关/token/UA」「按降级规则走免费层」这类后端配置叙述不进对话；脚本 stdout 的配置警告是给维护者的，不转述。确需用户动作时（缺持仓文件、要配 X 才有 Y）一句带过，不展开。细则见 `data-routing/SKILL.md` §2「数据通道状态不外曝」。

【数字格式】
- 涨跌：+2.3% / −1.8%（带符号，保留1位小数，负号用 U+2212）
- 利率变化：+12bp / −5bp
- 价格：$12.34 或 ¥34.56（对应货币符号）
- PE：12.3x        百分位：34th

【颜色class规则（HTML td）】
- 上涨普通: class="up"   上涨加粗: class="bup"
- 下跌普通: class="dn"   下跌加粗: class="bdn"
- 平盘:     class="flat"   不适用/未取到: class="na"
- 加粗触发: 1D|涨跌|≥3% / 1W~YTD|涨跌|≥5% / vsMA250|偏离|≥5%
- ⚠️ E1 边界：红绿**只能**当"带方向的数值本身"的字色（含 Beat/Miss 幅度、财报后反应）。
  不得作底色/圆点/边框/进度条，不得用于评级、风险等级、定价程度、估值高低
  → 这些一律 Harvey ball（.rlvl / .iv-badge）或 navy 加粗

【全局禁令】
- ❌ emoji（🔴🟡⚪🔥❄️⚡📍✅⚠️…）→ 用 .dot / .iv-badge / .rlvl / kicker 文字
- ❌ 色板外的第三种颜色（橙/琥珀/紫）→ 已无 warn 色
- ❌ 圆角 / 阴影 / 渐变（Harvey ball 的 conic 除外）
- ❌ 行内 style 写颜色字面值 → 只能 var(--x)
```

---

## 📡 数据路由：申万行业PE Band

早报若需加入**行业估值温度模块**（板块PE历史百分位、高低估值板块扫描），必须走申万行业数据接口（本地 `sw-api-router` skill，**未随公开版提供**；未安装则该模块整块留空并写明原因），禁止 web_search 估算。

| 需求 | 模块 |
|------|-------------------|
| 行业PE ±1σ Band + 历史百分位 | M1 |
| 换手率Z-score 情绪信号 | M3 |
| 全L1 PE利差横截面排名（哪个板块便宜） | M5 |

---

## 📌 关键注意事项

```
✅ 已改为自动推导（2026-09-08 起，不再需要按月/按季手改）：
   treasury.gov 的 field_tdr_date_value 与年份 → 由 now_hkt 推导
   Fed Funds 期货前三个合约（ZQ<月码><年>.CBT）→ FF_CONTRACTS 自动生成
   位置：data_pipeline.py 顶部注释里有说明

⚠️ M4 持仓名单 = positions 文件，**一处改全局生效**（2026-09-11 起）
   data_pipeline.WATCH_TICKERS 与 pe_engine.WATCHLIST 都从 positions.py 取，
   不要再在任何 .py 里写死 ticker。已有专属 skill 覆盖的标的只做摘要级汇总，不进 M4。

⚠️ 持仓只数**不设上限**：positions 里有多少只就覆盖多少只——M4 组合层全量、
   M5 逐票 deep dive 全量（full 重建、fast 全量继承）。只数多时压缩单票篇幅，
   不裁掉标的。

⚠️ DEMO 判据：终端打出「DEMO 组合」banner = 读到的是 positions.example.yaml。
   此时报告页眉**必须**挂 DEMO 角标，数字不许被当成真实持仓解读。

⚠️ pe_snapshot.json 缺失 → **估值信号整列是「—」**（2026-09-11 起改为 mask，不再降级顶替）
   pe_pct_1y = None + unavailable_reason；价格分位走独立的 price_pct_1y 字段与独立列。
   绝不要把 price_pct_1y 填进估值信号那一格 —— 那是这次改造要根治的问题本身。
   每季报后手填 `config_dir()/pe_snapshot.json`，见 reference.md

> 取数与口径见 `data-routing/SKILL.md`（取数执行层自备；出不出数、怎么标见它的第 2 节）。
   本 skill 的例外：美股/ADR 走分财年共识阶梯；A股/港股走本地共识源。
   下面这条 09-11 实测是 data-routing 里「锚因股而异」那条判据的原始出处。

⚠️ Fwd PE 口径：**不标财年的 forward EPS 一律不用**。2026-09-11 三只对照 S&P 实测（当时的 yfinance 路径）：
   NVDA 15.57 = FY2028（FY+2，PE 14.0x）而当前财年 FY2027 口径是 **23.5x**，差 40%；
   SNDK 264.72 = FY2028（6.4x）而 FY2027 是 7.9x；AAPL 9.57 = FY2027（FY+1）一致。
   → **美股/ADR 走 deepdive.py 的 S&P 分财年阶梯**（2026-09-17 起已无 yfinance 兜底：
   拿不到就是「—」，不回落到不标财年的源）。A股/港股走 finance-data 一致预期（CNY/HKD 口径）。
   **任何 PE 写进报告都必须带财年标签**，否则读者无法判断它锚在哪一年。

⚠️ 财年锚落盘契约（2026-09-18 起）：`pe.json` 每只票的 `fw_pe` 旁边一定有
   `fw_eps_fy`（"FY2027"）/ `fw_eps_period_end`（真锚，源不给就是 null）/
   `fw_eps_fy_basis`（这个 FY 凭什么判出来的）。判据见 `fy_anchor.py`：
   **选哪一年只认 `period_end_date`**（第一个 ≥ today 的财年末），不认年份标签 ——
   原来 `fy = today.year` 的写法对 1 月结账的 NVDA 会取到**已经结束的** FY2026，
   滚动 PE 坐进「前瞻 PE」那一格。A股/港股两个共识源只给年度数字、没有 period_end，
   basis 记 `eps_year_label` 如实标成色，**不替它们补日期**。
   引擎与 `run_data.py` 两道闸都会把**没有锚的 `fw_pe` 置空** —— 无锚 PE 不进版面。

⚠️ 一致预期**家数 < 3 不出数**（孤证不是共识）。deepdive.py 已按此 mask 整行。

⚠️ 研报检索端点需自配（BRIEF_SF_ENDPOINT），未配置或不可达时 research_radar 取不到数：
   M5 子块 B 缺席、.src 注明「本期未取到研报数据」，**早报照常产出**。

⚠️ 研报检索库**入库有滞后**（2026-09-11 实测 11 天，全库最新停在 08-31）。
   所以窗口固定给宽（Quick 14 / Full 30 天），「今天有什么新的」靠 is_new 增量判定。
   M5 子块 B 顶部固定放 .alert-bar 写「研报原文无 access，内容来自新闻检索，可能不全」——
   否则「0 篇」会被读成「卖方没动静」，实际是「库没更新到」。

⚠️ **北向日度持股已停更**（2024-08-16 起改季度披露）。接口照样返回 1699 行不报错，
   `.tail(1)` 会把两年前的持股当成今日流向。flows.py 已显式 mask，**不要"顺手接回来"**。

⚠️ 东财几个端点**认 TLS 指纹不认请求头**：python（requests/urllib）握手即被拒，curl 正常。
   flows / events 走 curl 子进程，urllib 兜底。调 headers 和加重试都没用，别再试。

⚠️ 美股事件流要 SEC 联系人 UA：`www.sec.gov` 的 ticker→CIK 表强制要求 UA 里带邮箱，
   否则 403（`data.sec.gov` 不要求，两个域策略不同）。没配就整块 mask 并提示设置
   `BRIEF_SEC_UA='YourName/1.0 (you@example.com)'`。**不要把任何邮箱写进 skill 文件。**

⚠️ 港股公告（HKEXnews prefix.do）当前不通，6 种参数组合 + cookie 预热实测全空。
   港股的「0 条公告」是取不到不是没事，版面上必须写明。

⚠️ pysnowball 未安装或无 token 时中概 ADR 自动降级 finance-data（会打印警告，属预期行为）
   token 走 XUEQIU_TOKEN 或 `config_dir()/secrets.json`，**不许写进 skill 目录任何文件**
```
