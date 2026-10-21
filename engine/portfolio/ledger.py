#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""engine/portfolio/ledger.py — PORT-01 统一组合账本（AGENTS #359）。

只记账，零业务规则（CONSTRAINTS C6.3）：不排序、不止损、不选股、不分配资金。

- 价格口径：一律用成交价，账本不做复权；同批 Fill 不许混用复权口径，
  复权一致性是调用方责任（spec 反例三）。
- 费用真源（D-07/C4.2/C6.1）：只来自 engine/costs.py（TAX-01 实际落地形态；
  spec/backlog/D-07 里的 `taxfee/` 是旧计划名，见 AGENTS #359）。Fill.fee/tax
  是输出字段——apply() 经 costs.py 计算回填；外部传非零 fee/tax 即
  FeeInjectionError，结构上杜绝第二套费用口径。
- 现金守恒（#249：买入漏扣现金 → 8 年净值 8377%）：买入扣 cash+fee、
  卖出加 cash-fee-tax、分红加 cash-tax；assert_conservation() 从入账 Fill
  重放重算，误差 >= 0.01 元即 ConservationError。
- 硬校验（I1 + spec 反例）：透支→OverdraftError；重复 (line,code,day,side)
  →DuplicateFillError；shares 必须 100 整数倍；cash==price*shares（容差 0.01）。
- 分红 v1（spec 风险条「如实记账」）：除权日记账，红利税按最早入场日→除权日
  的持有期调 costs.dividend_tax 即扣；到账时滞不建模（列 CASH-01）。
- combine(lines, cash0, slot_yuan, fills=None)：slot_yuan 仅作贡献 pct 分母，
  不强制执行——资金分配是 PORT-02 allocator 的事。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, replace

try:  # 包用法：from engine.portfolio.ledger import ...
    from ..costs import buy_fee, sell_fee, dividend_tax
except ImportError:  # 直跑/sys.path 指向 engine/ 的用法（仓库既有惯例）
    from costs import buy_fee, sell_fee, dividend_tax

CENT = 0.01  # 金额容差（元），I0：金额 2 位小数


class LedgerError(Exception):
    """账本错误基类。"""


class OverdraftError(LedgerError):
    """买入 cash+fee 超过可用现金——不许静默透支（spec 反例一）。"""


class DuplicateFillError(LedgerError):
    """重复 (line, code, day, side)——重复入账是历史 bug 源（spec 反例二）。"""


class FeeInjectionError(LedgerError):
    """外部传入非零 fee/tax——费用只能由账本经 costs.py 计算（D-07）。"""


class ConservationError(LedgerError):
    """现金守恒断言失败（#249 防线）。"""


@dataclass
class Fill:
    """一笔成交（字段契约见 INTERFACES I1）。

    fee/tax 为输出字段：构造时留 0，账本 apply 时经 costs.py 计算回填。
    side ∈ {buy, sell, div}；div 的 price=每股股息、shares=持仓股数、cash=股息总额。
    """
    line: str
    code: str
    side: str          # buy / sell / div
    day: str           # YYYY-MM-DD（BJT 交易日）
    price: float       # 成交价（账本不复权）
    shares: int        # A股 100 股整数倍
    cash: float        # 成交金额 = price*shares（div=股息总额）
    fee: float = 0.0   # 输出字段，账本回填
    tax: float = 0.0   # 输出字段，账本回填
    note: str = ""
    sig_day: str = ""  # 触发该笔的信号日（I1，归因用）


@dataclass
class _Position:
    shares: int
    cost: float        # 含买入费用的成本基（随卖出按比例结转，贡献归因用）
    px_cost: float     # 纯价格口径成本基（Σprice*shares，停牌估值兜底用）
    entry_day: str     # 最早入场日（红利税持有期口径）
    line: str


class Ledger:
    """统一组合账本：Fill 进、逐笔记账、mark-to-market 出净值。"""

    def __init__(self, cash0: float, lines: list[str]) -> None:
        if cash0 <= 0:
            raise ValueError(f"cash0 必须为正, got {cash0!r}")
        if not lines:
            raise ValueError("lines 不能为空")
        self.cash0 = float(cash0)
        self.lines = list(lines)
        self._cash = float(cash0)
        self._fills: list[Fill] = []
        self._seen: set[tuple] = set()          # (line, code, day, side)
        self._pos: dict[tuple, _Position] = {}  # (line, code) -> Position
        self._last_px: dict[str, float] = {}    # code -> 最近 mark 价
        self._budgets: dict[str, float] = {}    # line -> slot_yuan（combine 登记）
        self._nav: list[dict] = []

    # ── 记账 ──────────────────────────────────────────────────────────

    def apply(self, f: Fill) -> Fill:
        """记一笔：校验 → 经 costs.py 计费 → 落账 → 更新现金与持仓。返回入账副本。"""
        if f.fee != 0.0 or f.tax != 0.0:
            raise FeeInjectionError(
                f"fee/tax 由账本经 costs.py 计算，外部不许传入: fee={f.fee} tax={f.tax}")
        if f.line not in self.lines:
            raise ValueError(f"未登记的线 {f.line!r}（Ledger(lines={self.lines})）")
        if f.side not in ("buy", "sell", "div"):
            raise ValueError(f"side 必须是 buy/sell/div, got {f.side!r}")
        if not isinstance(f.shares, int) or f.shares <= 0 or f.shares % 100 != 0:
            raise ValueError(f"shares 必须是 100 的正整数倍, got {f.shares!r}")
        if f.side == "div":
            if f.cash <= 0:
                raise ValueError(f"div 的 cash(股息总额) 必须为正, got {f.cash!r}")
        else:
            if f.price <= 0:
                raise ValueError(f"price 必须为正, got {f.price!r}")
            if abs(f.cash - f.price * f.shares) > CENT:
                raise ValueError(
                    f"cash 必须等于 price*shares: {f.cash} != {f.price}*{f.shares}")

        key = (f.line, f.code, f.day, f.side)
        if key in self._seen:
            raise DuplicateFillError(f"重复入账 (line,code,day,side)={key}")

        if f.side == "buy":
            booked = self._apply_buy(f)
        elif f.side == "sell":
            booked = self._apply_sell(f)
        else:
            booked = self._apply_div(f)
        self._seen.add(key)  # 入账成功才占用键位（失败的 apply 不许留痕迹）
        self._fills.append(booked)
        return booked

    def _apply_buy(self, f: Fill) -> Fill:
        # fee 保持 costs.py 原始精度（对拍契约=逐分相等）；2 位小数舍入发生在
        # JSON 落盘边界（I0），账本内部不预先舍入。
        fee = buy_fee(f.cash)
        if f.cash + fee > self._cash + CENT:
            raise OverdraftError(
                f"透支: 买入需 {f.cash + fee:.2f}（成交 {f.cash} + 费 {fee}），"
                f"可用现金 {self._cash:.2f}")
        self._cash = self._cash - f.cash - fee
        pk = (f.line, f.code)
        pos = self._pos.get(pk)
        if pos is None:
            self._pos[pk] = _Position(f.shares, f.cash + fee, f.cash, f.day, f.line)
        else:
            pos.shares += f.shares
            pos.cost = pos.cost + f.cash + fee
            pos.px_cost = pos.px_cost + f.cash
        return replace(f, fee=fee, tax=0.0)

    def _apply_sell(self, f: Fill) -> Fill:
        pk = (f.line, f.code)
        pos = self._pos.get(pk)
        if pos is None or f.shares > pos.shares:
            have = pos.shares if pos else 0
            raise ValueError(f"卖出超过持仓: {f.line}/{f.code} 卖 {f.shares} > 持 {have}")
        fee = sell_fee(f.cash)
        tax = 0.0  # A股无资本利得税；红利税已在 div 入账时即扣（v1 口径）
        self._cash = self._cash + f.cash - fee - tax
        # 成本按卖出比例结转
        ratio = f.shares / pos.shares
        pos.shares -= f.shares
        pos.cost = pos.cost - pos.cost * ratio
        pos.px_cost = pos.px_cost - pos.px_cost * ratio
        if pos.shares == 0:
            del self._pos[pk]
        return replace(f, fee=fee, tax=tax)

    def _apply_div(self, f: Fill) -> Fill:
        pk = (f.line, f.code)
        pos = self._pos.get(pk)
        if pos is None or pos.shares <= 0:
            raise ValueError(f"分红入账时无持仓: {f.line}/{f.code} on {f.day}")
        # v1：除权日即扣红利税，持有期=最早入场日→除权日（costs.py 日历月口径）
        tax = dividend_tax(pos.entry_day, f.day, f.cash)
        self._cash = self._cash + f.cash - tax
        return replace(f, fee=0.0, tax=tax)

    # ── 查询 ──────────────────────────────────────────────────────────

    def cash(self) -> float:
        return self._cash

    def fills(self) -> list[Fill]:
        """已入账的 Fill（fee/tax 已回填）。"""
        return list(self._fills)

    def positions(self) -> dict[str, dict]:
        """code -> {shares, cost, line(s)}。多线持同码时合并，line 字段为排序后的线名列表。"""
        out: dict[str, dict] = {}
        for (line, code), p in self._pos.items():
            if p.shares <= 0:
                continue
            d = out.setdefault(code, {"shares": 0, "cost": 0.0, "lines": []})
            d["shares"] += p.shares
            d["cost"] = round(d["cost"] + p.cost, 2)
            d["lines"].append(line)
        for d in out.values():
            d["lines"].sort()
            d["line"] = d["lines"][0] if len(d["lines"]) == 1 else "+".join(d["lines"])
        return out

    # ── 守恒断言 ──────────────────────────────────────────────────────

    def assert_conservation(self) -> None:
        """现金守恒：从入账 Fill 重放重算，与运行余额误差 >= 0.01 元即 raise。

        守恒式：cash == cash0 - Σ买入(cash+fee) + Σ卖出(cash-fee-tax) + Σ分红(cash-tax)
        """
        c = self.cash0
        for f in self._fills:
            if f.side == "buy":
                c -= f.cash + f.fee
            elif f.side == "sell":
                c += f.cash - f.fee - f.tax
            else:  # div
                c += f.cash - f.tax
        if abs(c - self._cash) >= CENT:
            raise ConservationError(
                f"现金守恒失败: 重放重算 {c:.2f} != 运行余额 {self._cash:.2f} "
                f"（差 {c - self._cash:+.4f} 元，{len(self._fills)} 笔）")

    # ── mark-to-market ────────────────────────────────────────────────

    def _px(self, code: str, pos: _Position) -> float:
        """估值价：最近 mark 价 → 无则入场均价兜底（= pead_pool_sim 的
        `close_of or entry` 口径；纯价格不含费）。"""
        px = self._last_px.get(code)
        if px is not None:
            return px
        return pos.px_cost / pos.shares

    def _mkt_by_line(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for (line, code), p in self._pos.items():
            if p.shares > 0:
                out[line] = out.get(line, 0.0) + p.shares * self._px(code, p)
        return out

    def mark(self, day: str, prices: dict[str, float]) -> None:
        """收盘 mark-to-market：更新持仓市值并记一行净值（I2 五键 + by_line）。"""
        self._last_px.update(prices)
        mkt_bl = self._mkt_by_line()
        mkt = sum(mkt_bl.values())
        nav = self._cash + mkt
        by_line = {}
        for line in self.lines:
            mv = mkt_bl.get(line, 0.0)
            eq = self._budgets.get(line, self.cash0) + self._line_pnl(line, mv)
            prev = self._nav[-1]["by_line"][line]["equity"] if self._nav else None
            ret = (eq / prev - 1) if prev else 0.0
            by_line[line] = {"mkt_value": mv, "ret": ret, "equity": eq}
        self._nav.append({
            "date": day, "nav": nav, "cash": self._cash, "mkt_value": mkt,
            "exposure": (mkt / nav) if nav else 0.0, "by_line": by_line,
        })

    def nav_series(self) -> list[dict]:
        """[{date, nav, cash, mkt_value, exposure, by_line}]（I2 契约）。"""
        return list(self._nav)

    # ── 贡献归因 ──────────────────────────────────────────────────────

    def _line_pnl(self, line: str, mkt_value: float | None = None) -> float:
        """线级盈亏（元）= -Σ买(cash+fee) + Σ卖(cash-fee-tax) + Σ分红(cash-tax) + 持仓市值。
        与守恒式同源：全线合计 = nav - cash0（全部持仓已 mark 时精确成立）。"""
        if mkt_value is None:
            mkt_value = self._mkt_by_line().get(line, 0.0)
        pnl = mkt_value
        for f in self._fills:
            if f.line != line:
                continue
            if f.side == "buy":
                pnl -= f.cash + f.fee
            elif f.side == "sell":
                pnl += f.cash - f.fee - f.tax
            else:
                pnl += f.cash - f.tax
        return pnl

    def contributions(self) -> dict[str, dict]:
        """线 -> {yuan, pct}。pct 分母 = combine 登记的 slot_yuan，未登记用 cash0。"""
        mkt_bl = self._mkt_by_line()
        out = {}
        for line in self.lines:
            yuan = self._line_pnl(line, mkt_bl.get(line, 0.0))
            denom = self._budgets.get(line, self.cash0)
            out[line] = {"yuan": yuan, "pct": yuan / denom if denom else 0.0}
        return out


# ── 跨线喂入与合并 ─────────────────────────────────────────────────────

def load_line_fills(path: str | None, line: str, *,
                    pead_trades: list[dict] | None = None,
                    price_book: dict | None = None,
                    slot_yuan: float | None = None) -> list[Fill]:
    """读一条线的成交记录为 Fill 列表（路径由调用方给，账本不硬编码——SEC-01 后
    输入可能来自 data/private/）。

    两种来源：
    1. path=jsonl（I1 契约，一行一笔）：fee/tax 字段**载入即丢弃**——费用真源是
       costs.py，由账本 apply 重算（D-07；防止旧文件里的异口径费用混进账本）。
    2. pead_trades=pead_pool_sim 的 trades 列表（{code, entry_d, exit_d, ret,
       why, days}，**无价格**）：必须配 price_book={code: {day: {open, close}}}
       与 slot_yuan，重建 buy@entry_d 开盘 / sell@exit_d 收盘两笔；
       股数 = floor(slot_yuan/开盘价/100)*100（A股整手，I1 不变量）。
    """
    if pead_trades is not None:
        if price_book is None or slot_yuan is None:
            raise ValueError("pead_trades 适配必须给 price_book 与 slot_yuan（不许猜价）")
        fills = []
        for t in pead_trades:
            code, ent, ext = t["code"], t["entry_d"], t["exit_d"]
            o = price_book[code][ent]["open"]
            c = price_book[code][ext]["close"]
            shares = int(slot_yuan / o) // 100 * 100
            if shares <= 0:
                raise ValueError(f"slot {slot_yuan} 买不起一手 {code}@{o}")
            fills.append(Fill(line=line, code=code, side="buy", day=ent,
                              price=o, shares=shares, cash=o * shares,
                              note=f"pead_pool {t.get('why', '')} 入场"))
            fills.append(Fill(line=line, code=code, side="sell", day=ext,
                              price=c, shares=shares, cash=c * shares,
                              note=f"pead_pool {t.get('why', '')} 出场"))
        return fills

    if path is None:
        raise ValueError("path 与 pead_trades 必须给其一")
    fills = []
    with open(path, encoding="utf-8-sig") as fh:  # I0：读旧文件允许 utf-8-sig
        for ln, row in enumerate(fh, 1):
            row = row.strip()
            if not row:
                continue
            d = json.loads(row)
            try:
                fills.append(Fill(
                    line=d.get("line", line), code=d["code"], side=d["side"],
                    day=d["day"], price=float(d.get("price", 0.0)),
                    shares=int(d["shares"]), cash=float(d["cash"]),
                    fee=0.0, tax=0.0,  # 丢弃文件里的 fee/tax，账本经 costs.py 重算
                    note=d.get("note", ""), sig_day=d.get("sig_day", "")))
            except KeyError as e:
                raise ValueError(f"{path}:{ln} 缺字段 {e}") from None
    return fills


def combine(lines, cash0: float, slot_yuan: float,
            fills: list[Fill] | None = None) -> Ledger:
    """多线合并：各线登记起始资金 slot_yuan（仅作贡献 pct 分母与归因，不强制执行——
    资金分配规则是 PORT-02 allocator 的事，账本不塞业务规则）。

    lines: list[str] 仅登记线名；或 dict[str, str] {线名: jsonl 路径} 顺便载入。
    fills: 额外 Fill 列表（按给定顺序入账，排序是调用方责任）。
    """
    if isinstance(lines, dict):
        names, paths = list(lines), dict(lines)
    else:
        names, paths = list(lines), {}
    led = Ledger(cash0=cash0, lines=names)
    for name in names:
        led._budgets[name] = float(slot_yuan)
    for name, p in paths.items():
        for f in load_line_fills(p, name):
            led.apply(f)
    for f in fills or []:
        led.apply(f)
    return led
