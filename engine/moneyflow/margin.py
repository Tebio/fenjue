"""
MarginTracker — 融资融券数据获取、本地缓存与评分。

数据源: 东方财富 datacenter API (RPTA_WEB_RZRQ_GGMX)
- 融资余额 (RZYE)    — 当日融资余额
- 融资买入 (RZMRE)   — 当日融资买入额
- 融资偿还 (RZCHE)   — 当日融资偿还额
- 净买入  (RZJME)    — 融资净买入额

缓存策略:
    - 每日拉取后写入 data/margin/YYYY-MM-DD.json
    - 内存中保留最近 30 天历史用于趋势评分

评分维度 (1-10):
    连续 3 天融资余额下降 >5% → 2-3 (融资强平)
    融资余额稳定/上升 + 股价微跌 → 8   (融资锁仓)
    融资余额上升 + 股价上涨       → 9   (顺势)
    余额平稳                     → 6-7 (中性)
    无数据                       → 5   (默认)

Usage:
    from engine.moneyflow import MarginTracker
    mt = MarginTracker()
    score, raw = mt.update_and_score("002428", {"change_pct": -2.5})
    # → (8, {"date":"2026-07-09","rzye":5007043965,...})
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


# ── Eastmoney API ──────────────────────────────────────────────────────────

_EM_API = (
    "https://datacenter.eastmoney.com/securities/api/data/v1/get"
    "?reportName=RPTA_WEB_RZRQ_GGMX"
    "&columns=ALL"
    "&filter=(SCODE=%22{code}%22)"
    "&pageSize={page_size}"
    "&sortTypes=-1"
    "&sortColumns=DATE"
)

# 融资余额增长率字段名 (FIN_BALANCE_GR 是东财预计算的变化率，但某些日期可能为 null，
# 因此我们优先用自己的日间变化计算)


def _curl(url: str) -> str:
    """subprocess curl — 与 MarketData 一致，绕过 Python 代理问题。"""
    r = subprocess.run(
        ["curl", "-s", "--max-time", "15",
         "-H", "User-Agent: Mozilla/5.0",
         "-H", "Referer: https://data.eastmoney.com/",
         url],
        capture_output=True, timeout=20,
    )
    try:
        return r.stdout.decode("utf-8")
    except UnicodeDecodeError:
        return r.stdout.decode("gbk", errors="replace")


class MarginTracker:
    """融资融券数据获取器 — 东财 API + 本地 JSON 缓存 + 趋势评分。"""

    def __init__(self, cache_dir: str = "data/margin/") -> None:
        """初始化缓存目录并加载最近 30 天历史数据。

        Args:
            cache_dir: 相对于项目根目录的缓存路径。
        """
        # 自动解析到 fenjue 项目根目录
        _project_root = Path(__file__).resolve().parent.parent.parent
        self._cache_dir = _project_root / cache_dir
        self._cache_dir.mkdir(parents=True, exist_ok=True)

        # 内存缓存: code → [{date, rzye, rzmre, rzche, rzjme, ...}, ...]
        self._history: dict[str, list[dict[str, Any]]] = {}

        self._load_recent_history(days=30)

    # ── public API ────────────────────────────────────────────────────────

    def fetch_today(self, code: str) -> dict[str, Any] | None:
        """从东财 API 获取该股最新的融资融券数据。

        Args:
            code: 6 位股票代码，如 "002428"。

        Returns:
            dict 或 None:
                date              — 交易日期 (YYYY-MM-DD)
                rzye              — 融资余额 (元)
                rzmre             — 融资买入额 (元)
                rzche             — 融资偿还额 (元)
                rzjme             — 融资净买入 (元)
                balance_change    — 融资余额较前一日变化 (元)
                balance_change_pct— 融资余额变化百分比
                spj               — 收盘价
                zdf               — 涨跌幅 (%)
        """
        url = _EM_API.format(code=code, page_size=1)
        try:
            raw = _curl(url)
            data = json.loads(raw)
        except (json.JSONDecodeError, Exception):
            return None

        if not data.get("success") or not data.get("result"):
            return None

        rows = data["result"].get("data")
        if not rows:
            return None

        row = rows[0]
        today_date = _parse_date(row.get("DATE", ""))
        if not today_date:
            return None

        rzye = _safe_float(row.get("RZYE"))
        rzmre = _safe_float(row.get("RZMRE"))
        rzche = _safe_float(row.get("RZCHE"))
        rzjme = _safe_float(row.get("RZJME"))

        # 计算与前一日的历史变化
        prev_day = self._get_prev_day(code, today_date)
        balance_change: float | None = None
        balance_change_pct: float | None = None
        if prev_day and rzye is not None:
            prev_balance = prev_day.get("rzye")
            if prev_balance and prev_balance > 0:
                balance_change = rzye - prev_balance
                balance_change_pct = round(balance_change / prev_balance * 100, 4)

        return {
            "date": today_date,
            "rzye": rzye,
            "rzmre": rzmre,
            "rzche": rzche,
            "rzjme": rzjme,
            "balance_change": balance_change,
            "balance_change_pct": balance_change_pct,
            "spj": _safe_float(row.get("SPJ")),
            "zdf": _safe_float(row.get("ZDF")),
            "code": code,
        }

    def score(self, code: str, quote_data: dict[str, Any] | None = None) -> int:
        """基于融资融券历史趋势评分 (1-10)。

        评分规则:
            连续 3 天融资余额累计下降 >5% → 2-3 (融资强平/撤离)
            融资余额上升 + 股价微跌        → 8   (融资锁仓)
            融资余额上升 + 股价上涨        → 9   (顺势加仓)
            余额平稳 (波动 <2%)            → 7   (中性偏稳)
            有数据但无明显趋势              → 6   (中性)
            无数据                         → 5   (默认)

        Args:
            code:       6 位股票代码。
            quote_data: 可选行情数据，含 change_pct (当日涨跌幅)。

        Returns:
            int: 1-10 评分。
        """
        history = self._history.get(code, [])
        if not history:
            return 5  # 无数据 → 默认中性

        change_pct = 0.0
        if quote_data:
            change_pct = float(quote_data.get("change_pct", 0) or 0)

        recent = history[:3]  # 最近 3 个交易日 (已按日期降序排列)

        if len(recent) < 2:
            # 只有 1 天数据，无法判断趋势
            return 6

        # ── 计算 3 日融资余额变化 ──
        balances = [d.get("rzye") for d in recent if d.get("rzye") is not None]
        if len(balances) < 2:
            return 6

        # 3 日累计变化 (最早 vs 最新)
        newest_balance = balances[0]
        oldest_balance = balances[-1]

        if oldest_balance and oldest_balance > 0:
            pct_3d = (newest_balance - oldest_balance) / oldest_balance * 100
        else:
            pct_3d = 0.0

        # ── 单日变化方向 ──
        day1_change = 0.0
        if len(balances) >= 2 and balances[1] and balances[1] > 0:
            day1_change = (balances[0] - balances[1]) / balances[1] * 100

        # ── 逐日方向计数 ──
        down_days = sum(
            1 for i in range(len(balances) - 1)
            if balances[i] is not None and balances[i + 1] is not None
            and (balances[i] or 0) < (balances[i + 1] or 0) * 0.995  # 下降 >0.5%
        )

        # ── 逐日融资余额的下降幅度 (从旧到新) ──
        cumulative_daily_pct = 0.0
        valid_balances = [b for b in balances if b is not None]
        if len(valid_balances) >= 2:
            # 计算 daily cumulative (逐日乘积)
            prod = 1.0
            for i in range(1, len(valid_balances)):
                # 从旧到新: valid_balances[-1] → valid_balances[0]
                idx_from_end = len(valid_balances) - 1 - i
                if valid_balances[idx_from_end + 1] > 0:
                    prod *= valid_balances[idx_from_end] / valid_balances[idx_from_end + 1]
            cumulative_daily_pct = (prod - 1) * 100

        # ── 评分逻辑 ──

        # 连续 3 天融资余额下降且累计 >5% → 融资强平
        if down_days >= 2 and pct_3d < -5:
            return 2
        if down_days >= 2 and pct_3d < -3:
            return 3

        # 融资余额大幅下降 (单日 >3%)
        if day1_change < -3:
            return 3

        # 融资余额上升 + 股价上涨 → 顺势
        if pct_3d > 2 and change_pct > 0:
            return 9
        if pct_3d > 0 and change_pct > 2:
            return 9

        # 融资余额上升/稳定 + 股价微跌 → 融资锁仓
        if pct_3d > -2 and change_pct < 0 and change_pct > -5:
            return 8

        # 融资余额上升中
        if pct_3d > 2:
            return 8

        # 余额平稳 (波动 <2%)
        if abs(pct_3d) < 2:
            return 7

        # 余额小幅下降
        if pct_3d < -2:
            return 4

        # 默认有数据但无明显信号
        return 6

    def update_and_score(
        self, code: str, quote_data: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any] | None]:
        """拉取今日融资数据 → 保存缓存 → 返回 (score, raw_data)。

        Args:
            code:       6 位股票代码。
            quote_data: 可选行情数据，传入后可结合融资趋势打分。

        Returns:
            tuple[int, dict|None]: (评分 1-10, 原始数据 dict 或 None)。
        """
        raw = self.fetch_today(code)
        if raw:
            self._save_to_cache(code, raw)
        return self.score(code, quote_data), raw

    # ── internal: cache ───────────────────────────────────────────────────

    def _load_recent_history(self, days: int = 30) -> None:
        """从 data/margin/ 缓存文件中加载最近 N 天的数据到内存。"""
        cutoff = date.today() - timedelta(days=days)
        cache_files = sorted(
            self._cache_dir.glob("*.json"),
            reverse=True,
        )
        loaded: set[str] = set()
        for fp in cache_files:
            try:
                day_str = fp.stem  # "2026-07-09"
                day_date = datetime.strptime(day_str, "%Y-%m-%d").date()
                if day_date < cutoff:
                    continue
                day_data = json.loads(fp.read_text(encoding="utf-8"))
                stocks = day_data.get("stocks", [])
                for s in stocks:
                    code = s.get("code")
                    if not code or code in loaded:
                        continue
                    entry = {
                        "date": s.get("date", day_str),
                        "rzye": _safe_float(s.get("rzye")),
                        "rzmre": _safe_float(s.get("rzmre")),
                        "rzche": _safe_float(s.get("rzche")),
                        "rzjme": _safe_float(s.get("rzjme")),
                        "spj": _safe_float(s.get("spj")),
                        "zdf": _safe_float(s.get("zdf")),
                    }
                    if s.get("balance_change") is not None:
                        entry["balance_change"] = _safe_float(s["balance_change"])
                    if s.get("balance_change_pct") is not None:
                        entry["balance_change_pct"] = _safe_float(s["balance_change_pct"])
                    self._history.setdefault(code, []).append(entry)
                    loaded.add(code)
            except (json.JSONDecodeError, ValueError, KeyError):
                continue

        # 按日期降序排列每个 code 的历史
        for code in self._history:
            self._history[code].sort(
                key=lambda x: str(x.get("date", "")),
                reverse=True,
            )

    def _save_to_cache(self, code: str, data: dict[str, Any]) -> None:
        """将单只股票的融资数据追加到当日 JSON 缓存文件中。"""
        day = data.get("date", date.today().isoformat())
        cache_file = self._cache_dir / f"{day}.json"

        # 读取已有数据
        existing: dict[str, Any] = {"date": day, "stocks": []}
        if cache_file.exists():
            try:
                existing = json.loads(cache_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, ValueError):
                pass

        # 更新或追加该股数据
        stock_entry = {
            "code": code,
            "date": day,
            "rzye": data.get("rzye"),
            "rzmre": data.get("rzmre"),
            "rzche": data.get("rzche"),
            "rzjme": data.get("rzjme"),
            "balance_change": data.get("balance_change"),
            "balance_change_pct": data.get("balance_change_pct"),
            "spj": data.get("spj"),
            "zdf": data.get("zdf"),
        }
        stocks = existing.get("stocks", [])
        replaced = False
        for i, s in enumerate(stocks):
            if s.get("code") == code:
                stocks[i] = stock_entry
                replaced = True
                break
        if not replaced:
            stocks.append(stock_entry)
        existing["stocks"] = stocks

        cache_file.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # 更新内存缓存
        entry = {
            "date": day,
            "rzye": data.get("rzye"),
            "rzmre": data.get("rzmre"),
            "rzche": data.get("rzche"),
            "rzjme": data.get("rzjme"),
            "balance_change": data.get("balance_change"),
            "balance_change_pct": data.get("balance_change_pct"),
            "spj": data.get("spj"),
            "zdf": data.get("zdf"),
        }
        hist = self._history.setdefault(code, [])
        # 替换已存在的同日记录
        for i, h in enumerate(hist):
            if h.get("date") == day:
                hist[i] = entry
                break
        else:
            hist.append(entry)
        hist.sort(key=lambda x: str(x.get("date", "")), reverse=True)

    def _get_prev_day(
        self, code: str, current_date: str,
    ) -> dict[str, Any] | None:
        """获取该股在 current_date 之前最近的一个交易日数据 (从内存缓存)。"""
        hist = self._history.get(code, [])
        for entry in hist:
            if str(entry.get("date", "")) < current_date:
                return entry
        return None

    # ── convenience ───────────────────────────────────────────────────────

    def get_history(self, code: str, days: int = 10) -> list[dict[str, Any]]:
        """返回该股最近 N 天的融资历史数据 (内存缓存)。"""
        return self._history.get(code, [])[:days]

    def invalidate(self) -> None:
        """清空内存缓存 (文件缓存保留)。"""
        self._history.clear()


# ── helpers ────────────────────────────────────────────────────────────────

def _parse_date(raw: str) -> str | None:
    """解析东财 API 返回的日期字段 (格式: '2026-07-08 00:00:00')。"""
    if not raw:
        return None
    try:
        return raw.strip()[:10]
    except Exception:
        return None


def _safe_float(val: Any) -> float | None:
    """安全转换为 float，异常或空值返回 None。"""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None
