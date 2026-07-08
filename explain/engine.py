"""
ExplainEngine V2 — 动态溯源评分解释。
每个维度的 source 由真实数据生成，可追溯，可审计。
Scorer 传入 industry_context + quote_data，Explain 产出人类可读解释。
"""
from __future__ import annotations
from typing import Any


def _industry_ev_src(ind: dict) -> str:
    """Build evidence source string for industry dimension."""
    name = ind.get("name", "")
    stars = ind.get("heat_stars", "")
    stage = ind.get("stage", "")
    if name and name != "未匹配产业":
        parts = [f"fenjue.yaml industry_tree → {name}"]
        if stars:
            parts.append(stars)
        if stage:
            parts.append(stage)
        return " ".join(parts)
    return "fenjue.yaml industry_tree → 未匹配产业"


class ExplainEngine:
    """生成六维评分的可追溯解释。"""

    _WEIGHT_KEY: dict[str, str] = {
        "industry": "industry_trend",
        "flow":     "capital_flow",
        "inst":     "institutional",
        "margin":   "margin",
        "quant":    "quantitative",
        "expect":   "expectation",
    }

    _LABELS: dict[str, str] = {
        "industry": "产业趋势",
        "flow":     "资金流向",
        "inst":     "机构持仓",
        "margin":   "融资情绪",
        "quant":    "量化信号",
        "expect":   "预期兑现",
        "macro":    "宏观事件",
    }

    def explain(self, code: str, score_dict: dict[str, Any]) -> dict[str, Any]:
        """生成评分拆解，每维含动态 source。

        score_dict 需包含:
            industry/flow/inst/margin/quant/expect → 原始分
            total / tier / verdict / confidence
            weights → {yaml_key: float}
            industry_context (可选) → {name, heat_stars, stage}
            quote_data        (可选) → {turnover, pct_20d}
            macro_context     (可选) → {net_score, events: [label, ...], impact_summary}
        """
        weights = score_dict.get("weights", {})
        quote   = score_dict.get("quote_data") or {}
        ind_ctx = score_dict.get("industry_context") or {}
        macro   = score_dict.get("macro_context") or {}
        total   = float(score_dict.get("total", 0))

        breakdown: list[dict[str, Any]] = []
        for dim_key, label in self._LABELS.items():
            if dim_key == "macro":
                if not macro:
                    continue
                # Macro is a modifier, not a scored dimension
                net = macro.get("net_score", 0)
                contrib = round(net * 0.1, 4)  # macro 占总分 ~10%
                events = macro.get("events", [])
                summary = macro.get("impact_summary", "")
                src = self._src_macro(net, events, summary)
                breakdown.append({
                    "dimension":    "macro",
                    "label":        label,
                    "score":        round(abs(net), 1),
                    "weight":       0.1,
                    "contribution": contrib,
                    "source":       src,
                })
            else:
                raw = float(score_dict.get(dim_key, 0))
                wk  = self._WEIGHT_KEY.get(dim_key, dim_key)
                w   = float(weights.get(wk, 0))
                c   = round(raw * w, 4)
                src = self._source(dim_key, raw, w, c, ind_ctx, quote)
                breakdown.append({
                    "dimension":    dim_key,
                    "label":        label,
                    "score":        raw,
                    "weight":       w,
                    "contribution": c,
                    "source":       src,
                })

        # ── delta: score change vs previous run ──────────────────────
        delta: dict[str, Any] | None = None
        prev_total = score_dict.get("prev_total")
        if prev_total is not None:
            prev = float(prev_total)
            diff = round(total - prev, 4)
            direction = "up" if diff > 0 else "down" if diff < 0 else "flat"
            delta = {"direction": direction, "amount": abs(diff)}

        # ── evidence: structured per-dimension data source with confidence ─
        evidence: dict[str, Any] = {
            "industry": {
                "source": _industry_ev_src(ind_ctx),
                "confidence": "high" if ind_ctx.get("name") and ind_ctx["name"] != "未匹配产业" else "low",
            },
            "flow": {
                "source": "腾讯API qt.gtimg.cn" if "turnover" in quote else "换手率数据缺失",
                "confidence": "high" if "turnover" in quote else "low",
            },
            "inst": {
                "source": "默认占位(待接东方财富机构)",
                "confidence": "low",
            },
            "margin": {
                "source": "默认占位(待接融资融券)",
                "confidence": "low",
            },
            "quant": {
                "source": "默认占位(待接龙虎榜)",
                "confidence": "low",
            },
            "expect": {
                "source": "20日涨幅计算" if "pct_20d" in quote or ("price" in quote and "close_20d_ago" in quote) else "20日涨幅数据缺失",
                "confidence": "high" if "pct_20d" in quote else "medium",
            },
        }
        if macro:
            macro_src = macro.get("impact_summary", "") or ", ".join(macro.get("events", [])[:3])
            evidence["macro"] = {
                "source": f"宏观事件: {macro_src}" if macro_src else "宏观事件数据缺失",
                "confidence": "medium" if macro.get("events") else "low",
            }

        return {
            "total":      total,
            "tier":       score_dict.get("tier", "B"),
            "verdict":    score_dict.get("verdict", ""),
            "confidence": score_dict.get("confidence", 50),
            "breakdown":  breakdown,
            "delta":      delta,
            "evidence":   evidence,
            "_verified":  abs(sum(d["contribution"] for d in breakdown) - total) < 0.001,
        }

    # ── V3: 5-layer vertical explain ───────────────────────────

    # ── regime contribution mapping ────────────────────────────
    _REGIME_CONTRIB: dict[str, float] = {
        "risk_on":      0.50,
        "risk_neutral": 0.00,
        "risk_off":    -0.40,
        "crisis":      -0.80,
    }

    def explain_full(self, code: str, score_dict: dict[str, Any]) -> dict[str, Any]:
        """Vertical explain through all 5 layers — each answers 'why'.

        Layers:
            1. 宏观 — macro_context events + net_score → external tailwinds/headwinds
            2. 市场 — regime + max_position → market environment adjustment
            3. 产业 — industry_context name/stars/stage + chain mapping
            4. 公司 — all 6 scoring dimensions with traces
            5. 执行 — execution_plan: 3-step position building

        Args:
            code:       6-digit stock code.
            score_dict: dict from ScoringEngine.score_stock() enriched with:
                industry_context → {name, heat_stars, stage}
                macro_context    → {net_score, events: [label,…], impact_summary}
                execution_plan   → [{step, action, position_pct, trigger, price_range}, …]
                regime           → {regime, max_position, sector_multiplier, …}
                quote_data       → {turnover, pct_20d}

        Returns:
            dict with code, total, tier, layers (5 items), _verified.
            Each layer: {layer, label, contribution, reason_text, details}.
        """
        total        = float(score_dict.get("total", 0))
        weights      = score_dict.get("weights", {})
        ind_ctx      = score_dict.get("industry_context") or {}
        macro        = score_dict.get("macro_context") or {}
        execution    = score_dict.get("execution_plan") or []
        regime       = score_dict.get("regime") or {}
        quote        = score_dict.get("quote_data") or {}
        tier         = score_dict.get("tier", "B")

        # ── Layer 1: 宏观 ───────────────────────────────────────
        macro_contrib: float = 0.0
        macro_reason: str = ""
        macro_details: dict[str, Any] = {}
        if macro:
            net = float(macro.get("net_score", 0))
            macro_contrib = round(net * 0.1, 4)
            events = macro.get("events", [])
            summary = macro.get("impact_summary", "")
            macro_reason = self._macro_layer_reason(net, events, summary)
            macro_details = {
                "net_score":    net,
                "direction":    "利空" if net < -0.3 else "利好" if net > 0.3 else "中性",
                "events":       events,
                "event_count":  len(events),
                "impact_summary": summary,
            }

        layer_macro = {
            "layer":        "macro",
            "label":        "宏观",
            "contribution": macro_contrib,
            "reason_text":  macro_reason,
            "details":      macro_details,
        }

        # ── Layer 2: 市场 ───────────────────────────────────────
        regime_name = regime.get("regime", "risk_neutral")
        max_pos     = float(regime.get("max_position", 0.6))
        market_contrib = self._REGIME_CONTRIB.get(regime_name, 0.0)

        regime_display = {
            "risk_on": "Risk On", "risk_neutral": "Risk Neutral",
            "risk_off": "Risk Off", "crisis": "Crisis",
        }.get(regime_name, regime_name)

        market_reason = f"{regime_display}, 仓位{int(max_pos * 100)}%"
        if market_contrib > 0:
            market_reason += f" (尾部风利好)"
        elif market_contrib < 0:
            market_reason += f" (尾部风偏紧)"

        layer_market = {
            "layer":        "market",
            "label":        "市场",
            "contribution": market_contrib,
            "reason_text":  market_reason,
            "details": {
                "regime":             regime_name,
                "regime_display":     regime_display,
                "max_position":       max_pos,
                "sector_multiplier":  regime.get("sector_multiplier", 1.0),
                "capital_style":      regime.get("capital_style", "balanced"),
            },
        }

        # ── Layer 3: 产业 ───────────────────────────────────────
        industry_raw      = float(score_dict.get("industry", 0))
        industry_wk       = self._WEIGHT_KEY.get("industry", "industry_trend")
        industry_w        = float(weights.get(industry_wk, 0.35))
        industry_contrib  = round(industry_raw * industry_w, 4)

        ind_name  = ind_ctx.get("name", "未匹配产业")
        ind_stars = ind_ctx.get("heat_stars", "")
        ind_stage = ind_ctx.get("stage", "")
        ind_chain = ind_ctx.get("chain") or self._infer_chain(ind_name)

        ind_reason_parts = [ind_name]
        if ind_stars:
            ind_reason_parts.append(ind_stars)
        if ind_stage:
            ind_reason_parts.append(ind_stage)
        if ind_chain:
            ind_reason_parts.append(f"{ind_chain}链景气")
        industry_reason = ", ".join(ind_reason_parts) if ind_reason_parts else "产业未匹配"

        layer_industry = {
            "layer":        "industry",
            "label":        "产业",
            "contribution": industry_contrib,
            "reason_text":  industry_reason,
            "details": {
                "name":       ind_name,
                "heat_stars": ind_stars,
                "stage":      ind_stage,
                "chain":      ind_chain,
                "raw_score":  industry_raw,
                "weight":     industry_w,
                "source":     self._src_industry(industry_raw, industry_w, industry_contrib, ind_ctx),
            },
        }

        # ── Layer 4: 公司 ───────────────────────────────────────
        company_contrib = 0.0
        company_dims: list[dict[str, Any]] = []
        company_reason_parts: list[str] = []

        for dim_key in ("flow", "inst", "margin", "quant", "expect"):
            raw = float(score_dict.get(dim_key, 0))
            wk  = self._WEIGHT_KEY.get(dim_key, dim_key)
            w   = float(weights.get(wk, 0))
            c   = round(raw * w, 4)
            company_contrib += c
            src = self._source(dim_key, raw, w, c, ind_ctx, quote)
            company_dims.append({
                "dimension":    dim_key,
                "label":        self._LABELS[dim_key],
                "raw":          raw,
                "weight":       w,
                "contribution": c,
                "source":       src,
            })

        company_contrib = round(company_contrib, 4)

        # Synthesize company-layer reason from dimensions
        dim_map = {d["dimension"]: d for d in company_dims}
        flow_raw   = dim_map.get("flow", {}).get("raw", 0)
        expect_raw = dim_map.get("expect", {}).get("raw", 0)
        if flow_raw >= 8:
            company_reason_parts.append("资金活跃")
        elif flow_raw >= 5:
            company_reason_parts.append("资金正常")
        else:
            company_reason_parts.append("资金偏冷")
        if expect_raw >= 8:
            company_reason_parts.append("预期未兑现")
        elif expect_raw <= 4:
            company_reason_parts.append("预期兑现充分")
        company_reason = ", ".join(company_reason_parts) if company_reason_parts else "六维评分"

        layer_company = {
            "layer":        "company",
            "label":        "公司",
            "contribution": company_contrib,
            "reason_text":  company_reason,
            "details": {
                "dimensions": company_dims,
                "dimension_count": len(company_dims),
            },
        }

        # ── Layer 5: 执行 ───────────────────────────────────────
        total_position = round(sum(
            float(s.get("position_pct", 0)) for s in execution
        ), 4)
        exec_reason = self._execution_layer_reason(execution)

        # Map triggers to readable labels
        _trigger_labels: dict[str, str] = {
            "entry_signal": "等MA5确认",
            "confirmation": "第二笔等放量突破",
            "breakout":     "新高收盘确认",
        }

        exec_steps: list[dict[str, Any]] = []
        for s in execution:
            trigger_raw = s.get("trigger", "")
            trigger_label = _trigger_labels.get(trigger_raw, trigger_raw)
            exec_steps.append({
                "step":         s.get("step"),
                "action":       s.get("action"),
                "position_pct": s.get("position_pct"),
                "trigger":      trigger_raw,
                "trigger_label": trigger_label,
                "price_range":  s.get("price_range"),
            })

        layer_execution = {
            "layer":        "execution",
            "label":        "执行",
            "contribution": 0.0,  # execution is a plan, not a score contribution
            "reason_text":  exec_reason,
            "details": {
                "total_position": total_position,
                "total_position_pct": f"{int(total_position * 100)}%",
                "step_count":   len(exec_steps),
                "steps":        exec_steps,
            },
        }

        layers = [
            layer_macro,
            layer_market,
            layer_industry,
            layer_company,
            layer_execution,
        ]

        # ── verification ────────────────────────────────────────
        # Macro and market are external overlays — only industry + company
        # contributions must sum to the 6-dimension composite total.
        core_sum = industry_contrib + company_contrib
        verified = abs(core_sum - total) < 0.02

        return {
            "code":       code,
            "total":      total,
            "tier":       tier,
            "verdict":    score_dict.get("verdict", ""),
            "confidence": score_dict.get("confidence", 50),
            "layers":     layers,
            "_verified":  verified,
        }

    # ── 5-layer helper methods ─────────────────────────────────

    @staticmethod
    def _macro_layer_reason(net: float, events: list[str], summary: str) -> str:
        """Build human-readable macro reason text."""
        direction = "利空" if net < -0.3 else "利好" if net > 0.3 else "中性"
        if events:
            top = events[:3]
            evt_str = "、".join(top)
            return f"宏观{abs(net):.1f}分({direction}): {evt_str}"
        if summary:
            return f"宏观{abs(net):.1f}分({direction}): {summary}"
        return f"宏观{abs(net):.1f}分({direction})"

    @staticmethod
    def _infer_chain(ind_name: str) -> str:
        """Infer industry chain name from industry name."""
        _CHAIN_MAP: dict[str, str] = {
            "AI材料":    "磷化铟",
            "半导体":    "半导体",
            "机器人":    "机器人",
            "军工电子":   "军工",
            "新能源":    "新能源",
        }
        return _CHAIN_MAP.get(ind_name, "")

    @staticmethod
    def _execution_layer_reason(plan: list[dict[str, Any]]) -> str:
        """Build human-readable execution plan reason."""
        if not plan:
            return "暂无执行计划"
        first = plan[0]
        first_pct = int(float(first.get("position_pct", 0)) * 100)
        first_trigger = first.get("trigger", "entry_signal")
        trigger_map = {
            "entry_signal": "等MA5确认",
        }
        label = trigger_map.get(first_trigger, first_trigger)

        parts = [f"首笔{first_pct}%"]
        if label:
            parts.append(label)
        if len(plan) > 1:
            second = plan[1]
            s_trigger = second.get("trigger", "")
            s_label = {"confirmation": "第二笔等放量突破"}.get(s_trigger, s_trigger)
            if s_label:
                parts.append(s_label)
        return ", ".join(parts)

    # ── per-dimension source builders ─────────────────────────

    def _source(self, dim: str, raw: float, w: float, c: float,
                ind: dict, quote: dict) -> str:
        if dim == "industry":
            return self._src_industry(raw, w, c, ind)
        if dim == "flow":
            return self._src_flow(raw, w, c, quote)
        if dim == "expect":
            return self._src_expect(raw, w, c, quote)
        if dim in ("inst", "margin", "quant"):
            return self._src_placeholder(dim, raw, w, c)
        return f"raw={raw:.1f} × {w} = {c:.2f}"

    def _src_industry(self, raw: float, w: float, c: float, ind: dict) -> str:
        name  = ind.get("name", "未匹配产业")
        stars = ind.get("heat_stars", "★★☆☆☆")
        stage = ind.get("stage", "未知阶段")
        if name == "未匹配产业":
            return f"未匹配产业映射 → raw={raw:.1f} × {w} = {c:.2f}"
        return f"{name} {stars} {stage} → raw={raw:.1f} × {w} = {c:.2f}"

    def _src_flow(self, raw: float, w: float, c: float, quote: dict) -> str:
        t = quote.get("turnover")
        if t is None:
            return f"换手率缺失 → raw={raw:.1f} × {w} = {c:.2f}"
        bucket = (
            "过热(>20%)" if t > 20 else
            "活跃(10-20%)" if t >= 10 else
            "正常(3-10%)" if t >= 3 else
            "冷清(1-3%)" if t >= 1 else
            "极冷(<1%)"
        )
        return f"换手率 {t:.1f}% → {bucket} → raw={raw:.1f} × {w} = {c:.2f}"

    def _src_expect(self, raw: float, w: float, c: float, quote: dict) -> str:
        pct = quote.get("pct_20d")
        if pct is None:
            return f"20日涨幅缺失 → raw={raw:.1f} × {w} = {c:.2f}"
        zone = (
            "涨幅>30%(兑现充分)" if pct > 30 else
            "区间15-30%"           if pct >= 15 else
            "区间5-15%"            if pct >= 5 else
            "涨幅<5%(预期未兑现)"
        )
        return f"近20日涨幅 {pct:.1f}% → {zone} → raw={raw:.1f} × {w} = {c:.2f}"

    def _src_placeholder(self, dim: str, raw: float, w: float, c: float) -> str:
        return f"{self._LABELS.get(dim,dim)}: 暂用默认值(数据源待接入) → raw={raw:.1f} × {w} = {c:.2f}"

    def _src_macro(self, net: float, events: list[str], summary: str) -> str:
        direction = "利空" if net < -0.3 else "利好" if net > 0.3 else "中性"
        top_events = events[:3] if events else []
        evt_str = "、".join(top_events) if top_events else summary
        return f"宏观{abs(net):.1f}分({direction}): {evt_str}"
