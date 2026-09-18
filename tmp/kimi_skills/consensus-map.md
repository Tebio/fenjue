---
name: consensus-map
description: 各家券商独立预测按自有驱动因子粒度铺开对比，出 Excel + 交互 HTML。触发：一致预期地图/共识地图/券商预期对比/卖方预测分布/预期差/consensus map
whenToUse: When the user asks for a consensus map / broker estimate comparison / sell-side estimates vs own drivers / 券商预期对比 / 一致预期梳理 for one or more tickers, standalone or embedded into a model_basics/driver_setter workbook.
---

# Consensus Map（一致预期地图）

A consensus map is NOT a topline table. Its clusters mirror the user's own driver
model (segment revenue YoY, segment margins, cost ratios, capex…) — each KPI block
shows every broker's independent estimate so the user can see where their own
assumptions sit vs the street. House style and driver philosophy are owned by
`driver_setter` + `model_basics` (both under `../institutional-financial-modeling/`); this skill adds
retrieval, canonicalization, layout, and QC rules specific to consensus work.
It ships as a standalone top-level skill — mount it on its own; mounting the
institutional-financial-modeling group is only required for INTEGRATED runs.

## Visual companion (HTML charts)

`python3 scripts/build_consensus_charts.py <run_dir>` emits a single-file,
zero-dependency interactive HTML dashboard (hand-rolled inline SVG + tables —
no libraries, works offline, ~100-250 KB) from the same run-folder inputs. The
design is consulting IC-memo style: brand-navy/accent palette only (navy =
fact/actuals, accent = estimates, grey = third-party; no rainbow, shadows,
gradients, rounded corners, or traffic lights), Georgia for the page title +
big numerals, Arial elsewhere, body 17px / page max-width 1560px / SVG axis
12.5px (2026-09-15 enlargement — do not shrink back), and every section is a
full memo "page" — breadcrumb, action title (a sentence with a NUMBER +
JUDGEMENT computed from the run data), one-line mechanism subtitle, black
hairline, exhibits, numbered footnotes with sources and a page number. Charts
carry NO per-mark value labels: the only on-chart numbers are the mean per
cluster/series ("均值 1,886"), axis ticks, and the TP chart's bar-end target
prices; every bar, table cell, TP bar, and heat-table cell is clickable and
drives a sticky report-detail card (bank/title/date/rating/TP/KPI/period/
value/page cite/derived/source) from an embedded `window.DETAIL` JSON blob via
one delegated vanilla-JS listener. Section order: 怎么读这份 (methodology
with the reports table) → 共识与分歧 → 共识数值 → 数字分歧 → 轨迹 →
评级与目标价 → 热力表 → 修订轨迹.

- **Per-report source labels**: the reports table and the detail card render
  each bank's `source` JSON field via `SRC_LABELS` (uploaded / free_pdf /
  free_pdf / vendor / public_fallback) — never hardcode "uploaded".
  The cover source line is configurable as `SOURCE_LINE_CHARTS` in the run
  config.
- **02 共识与分歧**: `key_debates.md` is embedded in full (small built-in
  markdown renderer: headers, tables, lists, bold, blockquotes). House
  structure: one `## 共识` section (brief bullets — ratings, print verdict,
  tight bands) then `## 分歧一/二/…` sections, each framed as two opposing
  theses plus a 裁决指标 (the observable that settles it). The action title
  auto-names the debates from heading short forms ("核心分歧 N 个：甲、乙、
  丙") — heading count works at any markdown level (`##` or `###`). Numbers
  differing is not itself a debate; only opposing theses earn a section.
- **02 经营假设对比 (operating stats)**: when the map carries `Operating`-cluster
  KPIs (销量/产量/价格/分部 — e.g. CATL 电池销量 GWh, BYD 汽车销量 万辆; unit
  `units` = GWh, `wn` = 万辆), the debates section appends a "关键经营假设对比"
  block (same banks × periods table renderer, cap 12) quantifying the debate at
  the driver layer. These KPIs are excluded from the 05 轨迹 tables to avoid
  duplication.
- **03 共识数值**: one table — per KPI × period: bold sample mean with
  `min–max · n` beneath (n = houses disclosing that period, blank = none).
  Level-KPI rows are followed by their YoY row derived from the MEAN levels
  (ᵈ, never a re-average of per-bank YoYs); cells whose |YoY| > 100% are
  suppressed as basis breaks (share-count changes — the BYD 2025 送转 case)
  and counted in the footnote. The action title names the focus-period
  归母净利润 consensus (mean + range in 亿 + n) and the widest level-KPI gap
  ((max−min)/min).
- **04 数字分歧**: clustered per-KPI bar panels (x = periods, one thin bar per
  bank per cluster in canonical bank order — navy bars = actual periods,
  accent = forecasts; zero baseline for level units, 0–1 domain for pct; navy
  mean tick + Georgia mean label per cluster; n=1 cluster → single bar + note,
  no stats). Panel 760×280, bar width ≤ 12.
- **05 轨迹**: plain tables, NOT charts — one compact table per KPI (banks ×
  periods, printed values, `ᵈ` flag on derived, mean row in the footer,
  blank cell = not disclosed). The shape is already carried by the section-03
  bars; this section gives exact numbers only. The section action title keeps
  the revenue CAGR band ("年均复合增速带 22.9%–30.6%——斜率之争被复利放大");
  panel mini-titles deduplicate against it, and degenerate bands (min == max)
  collapse to a single value.
- **06 评级与目标价**: horizontal TP bars sorted descending, bar-end values,
  navy median line + label (W 1120, row height 40).
- **07 热力表**: bank × KPI at the focus period, accent/navy fill = signed
  deviation from the mean, introduced by a two-swatch legend (■ 高于均值 /
  ■ 低于均值 · 越深=幅度越大 · 空白=未披露) — no long mechanism prose.
- own-vs-street dumbbells only when own-model values exist (red #C00000
  reserved for that single house "own" semantic).
- **08 修订轨迹 (revisions)**: for every house with ≥2 vintages on different
  dates, one row — prev→latest date, rating action, TP action, and Δ of the key
  level KPIs (营业收入/归母净利润, FY2026E first) computed from the same
  house's own prints. Same-day A/H twins and identical-value re-ingestions do
  not count; single-vintage houses are stated as unobservable. Superseded
  vintages stay in the raw JSON (tagged 备查) and never enter statistics.

When the run's config declares `FONT = "华文楷体"`, the page switches to a
"STKaiti","华文楷体","KaiTi" stack and Chinese-first engine strings. Verify
visually with headless Chrome before handoff:
`--headless --screenshot=out.png --window-size=1600,9600 file:///…`
(append `#detail=N` to the URL to screenshot the detail card open on mark N).

**PDF export (print stylesheet contract, 2026-09-15)**: the same HTML carries
a `@media print` block that produces a single continuous A4-width page —
no pagination. Contract: `@page{size:210mm <PDF_PAGE_H_MM>mm;margin:8mm}` — page height comes
from the run config's `PDF_PAGE_H_MM` (default 2520, the CATL reference
run at 2478mm content). Sizing protocol per run: print at the default,
measure content fill via pdftoppm + PIL, then set `PDF_PAGE_H_MM` =
content mm × 1.02 in `consensus_config.py` and rebuild (BYD regression
run: 2194mm content → 2240mm → fill 98%), `body{zoom:0.85}`, `.wrap{max-width:820px}`, `.grid2` forced to one
column, `table.mdt` at 13px with `word-break:keep-all`, `#detailCard` hidden,
`svg{max-width:100%}`. Export:
`chrome --headless --print-to-pdf=out.pdf --no-pdf-header-footer file:///…`.
Verify: `pypdf` page count == 1 and content fill ≥ 95% before handoff. A
paged A4-portrait variant (`.page{page-break-before:always}` + panel
`page-break-inside:avoid` + cover `page-break-after:always`) is the fallback
when a paginated document is explicitly requested.

**Excel-native charts**: possible via openpyxl (`BarChart`/`LineChart`/`ScatterChart`)
for simple in-workbook bars (e.g. TP ladder), but static and stylistically limited —
the HTML companion is the default rich medium (same genre as the team's sell-side
decks); add Excel charts only if the user explicitly wants them inside the workbook.
Both read the same canonical JSON — never a separate hand-copied dataset.

## Two modes — decide first

**STANDALONE** (called by itself): full workbook —
`Cover → <one map tab per company> → Raw_Data → Data_Sources`. Cover follows the
Cover(2) layout idiom (navy identity band + GEO/SECTOR-style rows, section bands)
**in Arial at every size** (driver_setter rule 15 addendum: Arial Narrow is never
house style; Cover(2) adoption is layout-only). No reference/scratch tabs
(Cover (2), Assumptions (2)…) ever survive into the output.

**INTEGRATED**: model_basics owns shared identity, manifest, evidence, Raw_Data,
Data_Sources and the final gate; driver_setter owns forecasts. Consensus, comps
and guidance perform domain-local work/checks, not duplicate full builds.
Reuse the host identity and layout: Consensus tab when declared, otherwise
blocks under Assumptions; no duplicate Cover or source layers. Standalone tasks
retain their complete workflow. See
`../institutional-financial-modeling/model_basics/references/token-efficiency.md`.
Use the host period scheme. Per KPI:
- bank rows (blue = cited), Mean/Median (black, n≥2 only), then the **own-model row
  in red as same-sheet formula references back to the Assumptions driver cells
  above** (`=P8`, never re-typed values — boundary #5 cite-don't-recompute), then
  a Delta (own − mean) row.
- The map's Mean/Median rows are the **anchor source for the host's Assumptions**
  under the consensus-anchoring doctrine (driver_setter workflow step 6): driver
  inputs link to the map's Mean cells for the same operating metric — keep Mean
  cell addresses stable and declared in the manifest (one run's r5, 2026-09-08).
- Extracted raw rows **merge into the host's Raw_Data table** (append, tagged
  `consensus-map` in the source column); report citations **merge into the host's
  Data_Sources table**. Never create parallel side tables.
- Integration mutates the host file: work on a copy, check for externalLinks
  first (openpyxl round-trip mangles them — 2026-09-07 incident), and re-run the
  host's QC gates after.

## Workflow

`scope → retrieve → canonicalize → build → QC gate → handoff`

1. **Scope**: FIRST the identity lock (search-first, per model_basics SKILL.md
   §Step 0 — a FRESH web search, never from memory): confirm each company's
   current listing status, exact ticker(s) (unambiguous), listing venue (if
   US-listed: ADR/GDR + ratio vs ordinary/primary shares) and fiscal calendar
   (watch non-Dec FYE: BABA Mar, GIS May; FY-vs-CY labeling), stating the as-of
   date of the check. Then: which banks, periods (next few quarters if own model
   is quarterly + FY horizon), own driver file path (optional; if none on file,
   say so on the tab).
2. **Retrieve** per `references/retrieval.md`:
   - **ASK FOR UPLOADS FIRST — actively, before any route work.** Prompt the
     user to upload their own sell-side / in-house reports (PDF). Say plainly
     what the tradeoff is: with uploads the map is bank-by-bank from full
     reports; without them the data set degrades to sparse free PDFs
     (A-shares) or vendor aggregates (Wind / CapIQ-style — fewer houses, less
     driver granularity, no page citations). If the user uploads, those
     documents are the number source and no route is needed for the covered
     banks.
   - **No uploads → Eastmoney free whole PDFs (A-shares, sparse) is the only
     other skill route.** Anything further (datasource vendor aggregates,
     public web) is the base model's own routing — do not actively invoke it;
     if such a value lands in the data, label it `vendor` / `public_fallback`
     and state the limitation. Numbers are read from full PDFs, page-cited,
     bank-by-bank — group aggregates never substitute for bank rows.
   - **内部研报检索与全文镜像通道一律停用**——包括目录元数据在内的任何用途
     都不走；**外资研报付费源不使用**——外资行保持登记缺口，除非用户自行上传。
   → per-bank KPI JSON per company (`raw/<ticker>_consensus.json`).
3. **Canonicalize**: define the canonical KPI list by reading the user's own
   Assumptions/driver rows. Separate bases (GAAP vs non-GAAP vs bank-adjusted) into
   distinct rows; flag perimeter changes (e.g. BABA FY27 resegmentation); compute
   derived YoY/ratios only from the same bank's own printed levels (`derived` flag).
   Audit: every extracted estimate maps to a canonical row or is consciously dropped
   — print the audit, never silently drop.
4. **Build**: `python3 scripts/build_consensus_map.py <run_dir>` (engine +
   `<run_dir>/consensus_config.py`; see header of that script). Layout contract:
   `references/layout-and-style.md`.
5. **QC gate** (all must pass before handoff):
   - LibreOffice recalc round-trip: file opens, every formula resolves, cover links
     and deltas compute; Excel must NOT show a recovery prompt (no externalLinks,
     no defined-name debris — inspect the zip if unsure).
   - No stat formula in an empty period column; no Mean/Median on n=1 blocks.
   - Unmapped-estimates audit printed and reviewed.
   - Column widths verified at the xlsx `<col>` XML level (rule 16c — LibreOffice
     round-trips write ranged col entries that naive openpyxl readbacks misreport).
   - Fonts Arial-only (all sheets incl. Cover); percent cells display one decimal.
6. **Handoff**: workbook path, as-of date, coverage table (bank × report date used),
   gaps (unindexed/uncovered/catalog-only), basis caveats, refresh triggers.
   Append telemetry to `telemetry.jsonl` (date, tickers, banks, gates, rework).

## Layout essence (details in references/layout-and-style.md)

- Dates as columns, banks as rows; clusters ordered revenue → margins → profit →
  capex/other; KPI blocks inside cluster bands (blank row only *before* a cluster
  band — never between driver rows).
- n=1 KPI blocks collapse to a single cited row (KPI + bank + values + full
  citation); n≥2 blocks carry live `AVERAGE`/`MEDIAN` formulas, only in period
  columns that actually carry bank values.
- Own-model row sits **below Median**, red; Delta row `own − mean` below it.
- Colors: blue `0000CC` = cited from broker reports, red `C00000` = own-model
  input, black bold = calculated, grey `7F7F7F` = notes. Navy `1F3864` period
  bands, `EDEDED` section bands. Arial everywhere. Percent one decimal.
- Units live in the identity line (`RMB bn unless noted`); exceptions flagged in
  the cluster header — never repeated per KPI row.

## Assets

- `scripts/consensus_map_lib.py` — engine (styles, sheet/cover/raw/sources builders,
  `integrate_into_host`).
- `scripts/build_consensus_map.py` — CLI for standalone builds (`<run_dir>` holds
  `consensus_config.py` + `raw/*.json`).
- `references/retrieval.md` — uploads-first field guide; the only other skill
  route is Eastmoney free PDFs (A-shares); 内部研报通道已停用、外资付费源不使用
  (living file — update from bad cases).
- `references/layout-and-style.md` — full layout & house-style contract.
- `telemetry.jsonl` — run log.
