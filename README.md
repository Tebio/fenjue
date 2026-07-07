# 焚诀 — Investment Research Lab

> 决策引擎，不是炒股工具。
>
> 做一个属于自己的 Bloomberg（个人版）。

---

## 架构

```
fenjue/
├── engine/              # ⭐ 核心 — 决策引擎
│   ├── scoring/         #   六维评分
│   ├── mapping/         #   产业映射树
│   ├── regime/          #   市场状态
│   ├── execution/       #   建仓模型
│   └── backtest/        #   回测验证
│
├── api/                 # FastAPI 统一接口 (Phase 3)
│   ├── app.py
│   ├── routes/
│   └── schemas/
│
├── console/             # 轻量控制台 (Phase 4)
│   ├── dashboard/
│   └── settings/
│
├── research/            # 研究资产 (不可丢)
│   ├── docs/            #   方法论冻结版
│   ├── journal/         #   交易日志
│   ├── data/            #   每日评分快照
│   └── Changelog/       #   版本记录
│
└── skills/              # Hermes 技能
```

---

## 四层决策

```
Level 0: 市场状态 → 仓位上限
Level 1: 产业雷达 → 钱去哪
Level 2: 公司映射 → 认知差 × 供应链
Level 3: 交易执行 → 如何建仓 / 何时删除
```

---

## 当前阶段

**Phase 1: 验证期** — JSON + Git，每天自动评分。

- [x] 方法论 V2.3 封版
- [x] 仓库私有化
- [ ] 每日自动评分 (cron)
- [ ] 每周自动复盘 (cron)
- [ ] 3 个月后评估 Hit Rate / Alpha

---

## 原则

> 先研究产业，再寻找认知差；
> 先判断逻辑，再设计交易；
> 先定义失效条件，再决定是否持有。

> 90% 时候不改公式。每份评分永久留痕，Git 不撒谎。
