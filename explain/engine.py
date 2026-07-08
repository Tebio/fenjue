"""
ExplainEngine V2 — 动态溯源评分解释。
每个维度的 source 由真实数据生成，可追溯，可审计。
Scorer 传入 industry_context + quote_data，Explain 产出人类可读解释。
"""
from __future__ import annotations
from typing import Any


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

        # ── evidence: data sources used for each dimension ───────────
        evidence_sources: list[str] = []
        if ind_ctx.get("name") and ind_ctx["name"] != "未匹配产业":
            evidence_sources.append("产业链: fenjue.yaml industry_tree")
        if "turnover" in quote:
            evidence_sources.append("换手率: 东方财富实时数据")
        if "pct_20d" in quote:
            evidence_sources.append("20日涨幅: 东方财富实时数据")
        evidence: dict[str, Any] = {"sources": evidence_sources}

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
