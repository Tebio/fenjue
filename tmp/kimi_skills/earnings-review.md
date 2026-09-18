---
name: earnings-review
description: 财报出单文件交互 HTML 业绩点评，结论先行，不出 Word。触发：业绩点评/财报点评/季报点评/半年报点评/年报点评/earnings review
whenToUse: When the user asks for an earnings recap / quarterly review / 财报点评 / earnings summary HTML / interactive HTML recap, especially from an existing model workbook, local evidence, or uploaded reports.
---

# Earnings Review（业绩点评）

Generate **one concise, self-contained HTML** earnings recap. Keep words to a
minimum: prefer tables, labelled bullets, short takeaway lines and source notes
over long prose — paragraph walls are a defect (see "Prose shape").
The quality bar is a buy-side 业绩点评: verdict first, every table followed by a
short 解读 (what drove it, one-offs, quality flags), and an explicit action view
at the end.

## Deliverable

**不要手写 HTML —— 写 `recap.json`，由 builder 渲染**（2026-09-17 起）：

```bash
python3 scripts/build_earnings_review.py <run_dir>     # 读 <run_dir>/recap.json
```

理由有两条，第二条比第一条重要：

1. 每份 recap 的 CSS、版面骨架、导航脚本、打印样式**完全一样**，手写等于每次
   重新产出约 30KB 不变的样板。实测同样 5 节，`recap.json` 6.5KB vs 手写 HTML
   约 20KB —— 模型输出减少约 67%，且省下的全是样板。
2. style.md 里那些门禁（17px 字号地板、全角标点、token 配色、章节从「一」起编、
   锚点让位高度、宽表 `.scrollx`、verdict 必须是 bullets）手写时**每次都靠自觉，
   实测反复翻车**。builder 把它们变成结构性保证：版面由脚本生成，改不了；
   违规的内容在渲染时被门禁拦下并 exit 1。

所以你的工作是**填数据和写文案**，不是画页面。`recap.json` 的完整 schema、
block 类型与单元格约定见 `scripts/build_earnings_review.py` 的文件头 docstring。
章节号、导航、`#sN` 锚点、正文交叉引用由脚本按 `sections` 顺序统一生成 ——
这正是旧稿「从二起编被当场退回」那类错误的根源，现在不可能再犯。

门禁未过（exit 1）时 HTML 仍会写出供查看，但**不要交付**，先修 `recap.json`。
`{"type":"raw"}` 是逃生口，不过门禁 —— 只在 builder 确实表达不了时用，别拿它绕检查。

- One `.html` file only. 需要转发 / 打印 / 归档时从**同一份 HTML** 出 PDF，两种出口
  （A4 分页 + 连续单页，开关是 URL 上的 `?pdf=long`）：
  `python3 scripts/export_pdf.py recap.html` —— 规则与四个会静默毁掉 PDF 的坑见
  `references/pdf-export.md`。PDF 不是另画一版，是同一份版式的第二个出口。
- Interactive but restrained: sticky nav, table filters, text search, hover details, local links.
- No external CSS, fonts, images, JS libraries, or web assets. An optional
  inline-SVG chart (hand-rolled, no libraries) is allowed when a figure earns
  its place (e.g. price-relative or estimate-revision path) — tables remain the
  default exhibit; one figure max.
- All CSS in `<style>`; only vanilla JavaScript in one inline `<script>` if needed.
- Do **not** generate Word/DOCX with this skill.

## 可选加速路径：有解析器模板的标的

`scripts/parsers/` 下有对应模板的发行人（现有 `nvda_pr.py` / `amd_pr.py` / `baba_pr.py`），可以把
**抠数字**这一步交给脚本，你只写文案：

```bash
# 抓 5 期：当期 + 上一季（环比）+ 去年同期（同比）。周转天数的分母是**当季**收入，
# 只能在各期自己的公告里拿，所以对照期要各抓一份。实测 10 份附件并行约 3s。
scripts/fetch_sec_exhibits.sh <CIK> 5 run/raw
python3 scripts/parsers/<issuer>_pr.py run/raw/<当期>/q*pr.htm --cfo run/raw/<当期>/q*cfocommentary.htm \
        --out run/facts.json                          # 逐字搬运 + 9 项会计恒等式自检
python3 scripts/parsers/nvda_pr.py run/raw/<上一季>/q*pr.htm --out run/prior.json
python3 scripts/parsers/nvda_pr.py run/raw/<去年同期>/q*pr.htm --out run/yago.json
python3 scripts/verify_facts.py run/facts.json run/raw/<当期>/q*.htm   # 独立复核：原文逐字命中
# 卖方一致预期：走 finance-data 的 us.consensus 路由拿 S&P CapIQ 真值（财年按**发行人自己**的
# 口径，NVDA 2026-07 那季属 FY2027）。返回的行逐字落成 consensus_snapshot.csv 当信源，
# 每个值带三块进 _consensus_registry.json。拿不到就不出，**不用邻期顶替**。
python3 scripts/consensus_to_facts.py --ticker NVDA --fiscal-year 2027 \
        --facts run/facts.json --out run/consensus_facts.json
python3 scripts/verify_registry.py run/_consensus_registry.json run/consensus_snapshot.csv
python3 scripts/facts_to_scaffold.py run/facts.json --consensus run/consensus_facts.json \
        --prior run/prior.json --year-ago run/yago.json \
        --out run/recap.scaffold.json                 # 表格填满，只剩 {{FILL:槽位}}
#   ↑ 解析那一步已经把每个数字的坐标当场记进 run/_data_registry.json
python3 scripts/verify_registry.py run/_data_registry.json run/raw/<当期>/*.htm
#     ↑ 脚本按坐标回原文逐字重读（验收不经 LLM）
#   ↓ 你只产出一个 {"s1.stance": "…", …} 的平铺映射，几 KB
python3 scripts/fill_recap.py run/recap.scaffold.json run/fills.json --out run/recap.json
python3 scripts/build_earnings_review.py run
# 交付闸用的 registry：当场记的坐标 + 一致预期那批（tier B）+ 派生值，合成一份
python3 scripts/build_registry.py run/facts.json run/raw/<当期>/*.htm \
        --scaffold run/recap.scaffold.json --consensus run/_consensus_registry.json \
        --out run/_registry_full.json
python3 scripts/validate_recap.py run/recap.json --facts run/facts.json \
        --scaffold run/recap.scaffold.json --registry run/_registry_full.json \
        --html run/*.html          # 槽位/**每个数字必须已注册**/版式/HTML 一条命令
```

**为什么值得**（2026-09-17 同模型同材料各跑 3 次实测）：单次总 token 30.1k → 15.8k，
耗时 281s → 139s；更要紧的是**编造的数字 8 个 → 0 个** —— 手抠那三次每次都凭空造出
公告里没有的「上季」对比基数（上季存货、上季 DSO、上季承诺余额），因为季度公告根本
不披露上季资产负债表，而模板又问了。数字由脚本填，这条路就不存在。

**边界，别越过**：

- **没有模板的标的照旧走常规流程**，不要硬套。解析器认不出发行人会当场报错退出、
  不落半成品 —— 那是设计意图。新增模板见 `scripts/parsers/README.md`。
- **一次性项目的金额在调节表里**（GAAP→non-GAAP），`facts.json` 已带上；
  §2 的业绩质量拆解直接引它，不要回原文再捞一遍。
- **运营指标（DSO / 存货周转 / DPO / 现金循环 / 净现金）由 scaffold 算好**，按 91 天
  财季口径，实际用的公式写在表的「口径 / 来源」列里（净现金的科目组随公告形态变：
  FY26 及更早只有合并的「现金、等价物及有价证券」一行，公式跟着变）。
  **环比与同比是各期用各期的公告重算的**，不是拿本期分母套上期余额 —— 给了
  `--prior` / `--year-ago` 才有，没给就诚实落 `**信息缺口**`，**不要就地估一个**。
  值得强调：手写那三次编出来的「上季存货 25,800」「上季 DSO 45 天」，跟真值
  （25,797 / 45.4 天）几乎一模一样 —— 凭记忆填空**恰好填对**比填错更危险，
  因为合理性检查根本发现不了。判据只能是"这个数在不在给定材料里"。
- **交付物里每个数字都必须是 registry 里的已注册条目**（原值带坐标，或派生值带算法）。
  坐标是**取数当场记**的，不是事后拿值回原文搜的 —— 后者记下的"出处"只是"某个也含
  这个值的单元格"，且没法做往返验证。
  registry 没有的写 `**信息缺口**`，**不许凭记忆填**。三块字段（信源 / 时间 / 口径）
  与四种状态见 `references/data-registry.md` —— 那里也记了三条实测教训：
  坐标核验**只证明"存在于原文"、不证明"是对的那一列"**（所以本期是第几列改由脚本
  从表头独立推，不听提取器的）；展示层做了记法归一的值，registry 必须把归一后的
  形态也记上，否则成品里的数回溯不到出处。
- scaffold 出来的表**不要手改数字**。要改先改 `facts.json` 或解析器，否则
  `validate_recap.py` 的"数字可回溯"会把它标成查无出处 —— 那正是它该做的事。

## Default output shape

Use this verdict-first structure unless the user asks otherwise. Numbered
section headers carry the thesis ("三、分部收入：主品牌企稳，电商拖累收窄"),
not bare labels. **Header 是封面，不占章节号 —— 正文从「一、核心结论」起编**
（2026-09-16 house directive；旧稿从「二」起，被当场退回）。中文页的章节标题
**只写中文**，不写 `核心结论 Verdict：` 这类中英对照，也不写 emoji（含 `⚠️`）。 Every table gets a takeaway beneath it — ≤2 lines, or 2–4
bullets when it needs more.

- **Header**（不编号） — meta chips: ticker, company, 报告期, 数据截止日, 视角 (buy-side
   / own model), 口径 (currency & basis).
1. **核心结论 (Verdict)** — stance line (e.g. 持有/观望, 增持) + the full thesis
   as **3–6 labelled bullets**, not paragraphs: 业绩质量 / 量利背离 / 盈利结构 /
   核心分歧 / 指引与回报 / 估值锚与催化 (PE/PB with the close used, cash cushion,
   named catalysts with dates), each ≤2 lines; close with the one-line 一句话 in
   the navy callout bar.
2. **业绩概览 (Performance snapshot)** — KPI table (KPI, Actual, YoY, Sell-side
   consensus, Δ, `% beat / miss`, Own model, Notes) **plus the earnings-quality
   decomposition**: 2–4 lines reconciling the headline beat/miss into gross
   margin vs opex vs tax/one-offs, with one-off items explicitly flagged
   (e.g. tax-rate normalization, impairment base effects, "若剔除…则经常性口径…").
3. **收入结构 (Segments / category / channel)** — revenue by segment/category
   and by channel where the business discloses it: value, YoY, 占比, and a
   qualitative-trend column. Add the sequential cadence (Q1→Q2 节奏) when
   quarterly data exists. Skip with a stated reason only when the company has
   no meaningful split.
4. **盈利能力 (Margin bridge)** — GM% bridge (mix, discount/price, input costs)
   vs opex-ratio table (销售/管理/研发 or SBC lines + driver column) vs tax, to
   OP% and NI%: each margin with YoY Δ in pct and the driver named.
5. **运营与资产负债 (Operating quality, BS & CF)** — the 2–5 ratios that matter
   for this business (库销比/存货增速, DSO/DPO, 周转天数), CF summary (OCF, capex,
   FCF), cash reserve and net cash, plus safety math when relevant
   (e.g. 现金占市值≈x%). Mark any unavailable block "**信息缺口**" inline and
   move on — never pad.
6. **指引 (Guidance)** — what changed vs maintained, plus open targets /
   implied requirements: translate soft guidance into the implied numeric
   range ("低单位数增长 → 收入 300–306亿, 净利 18–27亿 vs 上年 29.4亿").
7. **指引历史 (Guidance history)** — ledger/matrix of historical targets with
   guide / actual / Δ / outcome.
8. **卖方预测网格 (Street grid + revisions)** — broker × FY1/FY2/FY3 estimates
   (净利 or EPS, plus PE/评级/目标价 where published), with **old-vs-new as
   adjacent labeled rows** (修订前/修订后) for houses that revised, and a
   dispersion line (区间, 离散度%, 中值). Below it the pre/post rating-PT
   vintages with explicit dates.
9. **估值与同行 (Valuation & peers)** — compact snapshot: close price (date),
    PE/PB/PS on FY1/FY2, 52-week context if available; peer table (3–5 names ×
    growth / margin / valuation / guidance stance). Flag 口径 mismatches inline
    **in words**（`口径不可比` / `KRW · K-IFRS` / `非 GAAP`），不用 emoji。
10. **风险与催化 (Risks & catalysts)** — numbered risks, each tied to a specific
    number from the body (not boilerplate); catalysts with expected timing.
11. **综合判断 (Scorecard & action view)** — small scorecard table
    (维度 × 评估 × 信号) using the monochrome signal glyph set (see style
    rules), then the conditional action plan ("若 2 个以上信号验证 → 加仓;
    若 X 发生 → 下调").
12. **来源与数据说明 (Sources & caveats)** — retrieval route, model source, basis, data-quality
    notes, per-section source filenames.

Do **not** include these by default:

- Earnings call notes section
- Call-anatomy section
- Earnings-date reaction windows such as `D−7 / D−1 / D+1 / D+7`
- Full consensus-map section (the street grid in §8 is the compact version)
- Target-price tape as a headline section
- Full transcript

If the user explicitly asks for any of those, create a separate companion
artifact or a clearly separate optional section.

## Data collection route

### User-uploaded materials (PRIMARY — actively invited at the start)

Actively invite uploads at the start — the recap is markedly better with the
user's own sell-side / in-house documents than with vendor aggregates alone
(without uploads, report-sourced numbers degrade to Wind / CapIQ-style
aggregates: fewer houses, less granularity — say so plainly when that is the
case). Allow the user to upload or point to any of the following and synthesize
them into the recap:

- their own model workbook
- sell-side reports
- consensus exports
- guidance ledgers
- earnings call transcripts
- price/market data files
- local evidence packs

### Report retrieval when uploads don't cover it

- **Eastmoney research center** (free whole PDFs, A-shares only, sparse):
  `akshare ak.stock_research_report_em(symbol=...)` → direct PDF links; numbers
  page-cited from the full PDF.
- Anything beyond uploads and Eastmoney (datasource vendor aggregates,
  public web) is the base model's own routing — do not actively invoke it;
  label it `vendor` / `public_fallback` if it lands in the data.
- **Internal report-retrieval / full-text mirror channels are NOT AVAILABLE in the
  public edition** — do not reach for them for anything, including catalog metadata.
  Foreign-broker houses stay documented gaps unless the user uploads their reports.

Use SEC / company filings for identity and statement-basis facts; use market-data sources for prices; use public web only as fallback for facts that are not otherwise available.

### 估值 / 共识 / 行情 / 分部：取数与口径见 `data-routing/SKILL.md`

那是本发行版的唯一取数指针（取数执行层自备；出不出数、怎么标见它的第 2 节）。
**不要在这里复述规则** —— 副本只会漂开。本 skill 的例外只有一条：**研报原文**仍按上面
「上传优先 + 东财研报中心免费整份 PDF（A股，逐页引用）」取 —— recap 要的是可页级引用的
原文，不是检索切片。数值口径没有例外。

### 素材优先级 / Source precedence

这五条管的是「同一个数字有多个来源时听谁的、以及怎么并存」，属于 recap 的编辑规则，
不是取数口径 —— 取数口径统一在 `data-routing/SKILL.md`。

1. **User model first** — the user’s workbook is the canonical own-model source unless the user says otherwise.
2. **Uploaded sell-side material is evidence, not a plug** — extract estimates, vintages, PT/rating and rationale; do not overwrite the own model silently.
3. **Synthesize across sources** — reconcile actuals, consensus, own-model estimates, guidance history, and market reaction into one consistent page.
4. **Preserve basis** — GAAP vs non-GAAP, reported vs estimated, pre-earnings vs post-earnings, bank-level vs aggregate statistics must stay separate **on the page** —— 别把两种口径混进同一列。
5. **Do not fabricate coverage** — missing consensus or revisions stay `n/c`; no synthetic 30-day window.

## Required content rules

### Performance snapshot

- Include sell-side consensus when available.
- Always show both absolute delta and `% beat / miss` where comparable.
- `% beat / miss = actual ÷ consensus − 1`.
- EPS on a negative base uses absolute delta instead of a misleading percentage.
- No consensus → grey `n/c`, never zero.

### Earnings quality and margins

- Every profit beat/miss gets a driver decomposition; one-offs are named and
  quantified, never blended into "recurring" silently.
- Margin moves use `pct` for rate deltas, `%` for growth deltas; negative-base
  awareness everywhere.

### Guidance and guidance history

- Separate current-quarter guidance changes from historical target tracking.
- Guidance history should be a matrix/ledger, not a narrative wall.
- Remove empty rows; use `—` for blank cells.
- Open targets and implied requirements belong in a compact separate table,
  with the implied-range math shown.

### Street grid and pre vs post

- Bank-by-bank, never aggregates only; show old/new vintages as adjacent rows.
- Dispersion stats (range, dispersion %, median) on every multi-bank grid.
- Keep explicit dates and flags.
- Do not turn sparse evidence into a fake complete window.

### Conventions throughout

- Per-row 来源/source attribution where sources differ within a table.
- 口径 mismatch 与缺数就地标注，不只写进结尾 caveats：口径用**文字**标
  （`口径各异` / `毛利口径` / `模型值，非实际` / `derived`），缺数用 `**信息缺口**`。
  **不要用 `⚠️` 或任何 emoji**（2026-09-16 house directive；builder 门禁会拦，
  正文与 bullet 标签都拦）。
- Change notation: `+0.9pct` / `+2.8%` / `—` for blanks.
- Punctuation: 中文正文全角标点（`，` `；` `：` `（` `）`），半角只留在数字/英文 token
  内部（千分位、小数点、ticker、英文句）。规则到此为止，**不必再去翻 style.md** ——
  那边的 badcase 长文是给改 builder 的人看的。

## Visual design rules

**配色、字号、版面骨架、导航、锚点、打印 CSS 全部由 builder 生成，你改不到，
也不用管。** 以前这里（和 `references/style.md` 291 行）要求「读完再写页面、
逐字复制 token 块」，那是手写 HTML 时代的规矩；builder 落地后再读一遍是白花
约 5.7k token。`references/style.md` 现在是**改 builder 时才读**的设计台账。

`recap.json` 里真正由你决定、builder 兜不住的只有四条：

- **宽表要自己开 `min_width`**。builder 只在数值列 > 6 时自动套 `.scrollx`；
  宽度得你给，且**备注列要留 ≥300px**（7 家 × FY1–FY3 的网格实测 `min_width:1760`）。
  挤窄备注列的症状很好认：每行胀到 100–250px 高，整页读起来是一条条空白带。
- **信号字形只用 `▲` / `–` / `▼`**（正 / 中性 / 负），且**只在综合判断的评分卡里用**，
  navy 或灰，不用红绿。
- **要加粗写 `**文字**`，不要写 HTML 标签。** 文案字段一律转义，`<b>…</b>` 会原样
  显示成标签本身，门禁直接拦下（实测某组 prompt 下 3/3 次中招、每次 40+ 处）。
  `**…**` 是**唯一**的标记通道，缺数标记 `**信息缺口**` 正是走它渲染成粗体。
  公告原文里的尾随脚注星号（`Tax expense from OBBBA**`）配不成对，原样保留。
- **全程禁 emoji**（含 `⚠️`）。口径与风险提示写字：`口径各异` / `毛利口径` /
  `模型值，非实际` / `**信息缺口**` / `derived`。
- **中文正文全角标点**，半角只留在数字/英文 token 内部（千分位、小数点、ticker、
  英文整句）。

其余（白底、token 配色、17px 字号地板、页眉页脚、表格线、无阴影无圆角无渐变）
由 builder 结构性保证；退役色 `#16324f` / `#2f6fbf` / `#f4f6f8` 由门禁拦。
真要出格只能走 `{"type":"raw"}` —— 它不过门禁，别拿它绕检查。

## Prose shape — bullets, not walls

Long paragraphs are a defect in this deliverable (house red-pen on a real
A-share interim run: the recap shipped a ~900-character verdict block and
250–400-character takeaways).

- A `<p>` never exceeds 2 rendered lines (≈120–140 全角字符 at the house width);
  anything longer becomes a bulleted list.
- Every bullet leads with a bold label (`<b>量（主驱动，+）：</b>…`), carries one
  idea, and stays ≤2 rendered lines. No nested bullets.
- **§1 Verdict is structurally bulleted**: stance line + 3–6 labelled bullets
  (业绩质量 / 量利背离 / 盈利结构 / 核心分歧 / 指引与回报 / 估值锚与催化) + the
  one-line 一句话 in the navy callout bar. Never 2–3 dense paragraphs.
- Takeaways under tables: ≤2 lines, or 2–4 bullets.
- Risks, catalysts, implied-guidance requirements, sources and caveats are
  always lists — catalysts lead with the date in bold.
- Bullets render at body size (17px), never in a smaller type class.
- When a list becomes parallel items sharing the same 3 fields, make it a table.

## Validation before handoff

这份清单过去是一整条"交付前都看一眼"，实测记不住。现在按**谁来查**分三档 ——
只有第三档要你花时间。

### 一、builder 门禁已硬拦（exit 1，不必人工看）

外部资源引用 ｜ 锚点无对应元素 ｜ 重复 id ｜ `<p>` 超 2 行 ｜ 第一节没有 bullets ｜
退役配色 `#16324f` / `#2f6fbf` / `#f4f6f8` ｜ 文案里写了 HTML 标签（会被转义成
页面上的字面量）｜ 正文与 **bullet 标签**里的 emoji。

门禁没过 HTML 仍会写出供查看，但**不要交付**，先改 `recap.json`。

### 二、builder 结构性保证（改不到，也不用查）

单文件、可解析 ｜ 字号体系（body 17px、表 16px、注 14px、地板 12.5px）｜ token 配色 ｜
章节号从「一」起且导航/`<span class=no>`/`#sN` 四处同步 ｜ 单表头 + 表格线 ｜
数值列 > 6 自动进 `.scrollx`。

唯一例外是 `{"type":"raw"}`：它不过门禁也不受保证，用了就得自己查。

### 三、仍要人工过（门禁查不了的）

- **必备章节在、默认不出的章节没混进来**（call notes / call anatomy /
  D−7…D+7 反应窗 / 完整共识地图 / 目标价 tape / 全文转写）
- **`% beat / miss` 复算对**：`actual ÷ consensus − 1`；负基数 EPS 用绝对差不用百分比；
  没有一致预期写 `n/c`，不写 0
- **上传材料按文件名/路径出现在来源里**，没上传就照实说"降级到 vendor 聚合口径"
- **没有凭据、私有签名 URL、内网 PDF 正文被嵌进页面**
- **口径没混列**：GAAP 与 non-GAAP、实际与预测、事前与事后分开摆
- **全角标点**（门禁只给 WARN 不拦，得自己看一眼）
- **浏览器里真看一眼**：逐个点导航、表格搜索框能过滤高亮、宽表没有整行胀成空白带；
  做不到就明说"未做浏览器目视验证"，不要默认它通过
