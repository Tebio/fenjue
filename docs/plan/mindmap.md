# 焚诀思维导图（Mermaid，GitHub 直接渲染）

> 三张图：① 部门模型 ② 系统与数据流 ③ 目标模块依赖。
> 判断"某件事属于谁"时看①；判断"数据从哪来到哪去"看②；判断"代码该放哪、谁能 import 谁"看③。

---

## ① 部门模型（他的一人公司）

```mermaid
mindmap
  root((焚诀<br/>一人公司))
    研究部 A-
      事件研究
      推测纪律 HAC/DSR/防前视
      待补: 试验登记/功效/bootstrap/真OOS
    数据部 C+
      行情与缓存(kcache/m60)
      公告/两融/分红/HiThink
      待补: DQ断言/源冗余/快照/灾备演练
    组合部 F(空)
      统一账本
      成本与税费唯一真源
      资金调度/跨线冲突/现金收益
    风控部 F(空)
      相关性/协方差
      波动率目标/回撤预算
      压力测试/VaR
    中台 F(空)
      成交/持仓/费用对账
      P&L归因
      净值与会计口径
    执行部 D
      手工9:25挂单
      待补: 滑点实测/TCA/偏离记录
    技术部 B-
      494脚本/63cron/66k行
      待补: 统一库/版本锚/CI/监控分级
    治理部 D+
      台账AGENTS.md/REGISTRY
      待补: 状态机/退役判据/结论外部审查
    安全与资产 D
      公开仓库暴露持仓
      待补: 私仓剥离/备份演练
```

---

## ② 系统与数据流（现状 + 目标态缺口标红点）

```mermaid
graph TD
  subgraph 数据源["外部数据源（单点风险）"]
    BS[baostock 日K]:::single
    TX[腾讯行情]:::single
    HT[HiThink relay 涨停/龙虎榜]:::single
    EM[东财 公告/预增/两融]:::single
    AK[akshare 分红/成分]
  end

  subgraph 数据层["数据层（缺断言/快照）"]
    KC[(big_kcache 前复权)]
    KCu[(big_kcache_unadj 不复权)]
    M60[(m60 分钟线)]
    DB[(margin_stock.db / ann_stream / hithink)]
    CAL[(index_sh000001 交易日历)]
  end

  subgraph 研究层["研究层（最强）"]
    LP[law_pipeline REGISTRY 111条<br/>HAC / 日历时间组合 / DSR]
    ST[事件研究 / 回测 / 锦标赛]
    SH[影子账本 shadow]
  end

  subgraph 生产层["生产层"]
    SIG[信号生成 lines/*]
    ORD[委托单 ops_briefing]
    GATE[regime/X规则闸门]
  end

  subgraph 缺1["❌ 组合层（空）"]
    LDG[统一账本/资金占用]
    TAX[费率税费唯一真源<br/>红利税按持有期]
  end

  subgraph 缺2["❌ 风控层（空）"]
    COR[相关性/协方差]
    VT[波动率目标/回撤预算]
  end

  subgraph 缺3["❌ 中台（空）"]
    REC[券商成交/持仓对账]
    ATTR[P&L 归因]
  end

  UIU[面板 docs/index.html<br/>+ QQ 推送]

  数据源 --> 数据层 --> 研究层 --> 生产层
  生产层 --> ORD --> 手工执行
  手工执行 -.缺.-> REC
  SIG --> SH --> 缺1
  缺1 --> 缺2
  缺1 --> 缺3
  缺1 --> UIU
  缺2 --> UIU
  缺3 --> UIU
  classDef single fill:#ffe0e0,stroke:#c00
```

---

## ③ 目标模块依赖（单向，只许向下）

```mermaid
graph TD
  L[lines/* 各条生产线的信号生成] --> P[portfolio/ 账本·资金·成本·归因]
  L --> R[risk/ 相关性·波动目标·回撤预算]
  P --> X[taxfee/ 费率与税费唯一真源]
  P --> C[core/ 日期·日历·序列·统计]
  R --> C
  X --> C
  L --> D[data/ 读取与新鲜度断言]
  D --> C
  G[registry/ 状态机·闸门·体检] --> C
  M[monitor/ DQ断言·告警] --> D
  RP[repro/ 版本·参数哈希·快照] --> C
  RES[research/ HAC·日历时间·DSR·bootstrap·功效] --> C
  REC[recon/ 券商成交导入与对账] --> P
  REC --> X

  C -.禁止.-> P
  C -.禁止.-> R
  L -.禁止互相import.-> L
```

规则：`lines/` 之间**不得互相 import**（跨线共享必须下沉到 `core/` 或 `portfolio/`）；
`core/` 只依赖标准库与 numpy/pandas；**所有费用与税费只能来自 `taxfee/`**。
