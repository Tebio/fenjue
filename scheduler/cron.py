"""FenJue Engine — Task Scheduler

基于 APScheduler 构建的定时任务框架。
支持 daily/weekly cron 表达式，提供每日评分快照、每周复盘。
Job 定义持久化到 SQLite (scheduler_jobs 表)。
"""

from __future__ import annotations

import json
import os
import sqlite3
import textwrap
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.executors.pool import ThreadPoolExecutor

from engine.event_registry import EventRegistry, todays_registry
from engine.macro_industry import MacroIndustryMapper
from engine.feedback import FeedbackEngine

# ---------------------------------------------------------------------------
# SQLite job store
# ---------------------------------------------------------------------------

DDL_SCHEDULER_JOBS = """\
CREATE TABLE IF NOT EXISTS scheduler_jobs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    NOT NULL UNIQUE,
    cron_expr  TEXT    NOT NULL,
    last_run   TEXT,
    status     TEXT    DEFAULT 'pending'
                      CHECK(status IN ('pending','running','success','failed')),
    enabled    INTEGER DEFAULT 1
);
"""


class SQLiteJobStore:
    """Lightweight job persistence backed by SQLite.

    Stores job definitions in the ``scheduler_jobs`` table inside the
    FenJue database so job config survives restarts.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._ensure_table()

    # -- public ----------------------------------------------------------

    def load_jobs(self) -> list[dict[str, Any]]:
        """Return all *enabled* jobs from the table."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT name, cron_expr, last_run, status FROM scheduler_jobs "
                "WHERE enabled = 1 ORDER BY id"
            ).fetchall()
        finally:
            conn.close()
        return [
            {
                "name": r[0],
                "cron_expr": r[1],
                "last_run": r[2],
                "status": r[3],
            }
            for r in rows
        ]

    def save_job(self, name: str, cron_expr: str) -> None:
        """Upsert a job definition (INSERT OR REPLACE)."""
        conn = self._connect()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO scheduler_jobs (name, cron_expr, enabled) "
                "VALUES (?, ?, 1)",
                (name, cron_expr),
            )
            conn.commit()
        finally:
            conn.close()

    def update_status(self, name: str, status: str) -> None:
        """Update last_run and status after a job finishes."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE scheduler_jobs SET last_run = ?, status = ? WHERE name = ?",
                (now, status, name),
            )
            conn.commit()
        finally:
            conn.close()

    # -- internal --------------------------------------------------------

    def _ensure_table(self) -> None:
        db_dir = os.path.dirname(self._db_path)
        if db_dir and not os.path.isdir(db_dir):
            os.makedirs(db_dir, exist_ok=True)
        conn = self._connect()
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute(DDL_SCHEDULER_JOBS)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_scheduler_jobs_name "
                "ON scheduler_jobs(name);"
            )
            conn.commit()
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn


# ---------------------------------------------------------------------------
# CronScheduler
# ---------------------------------------------------------------------------

# Project root (scheduler/ → fenjue/)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


class CronScheduler:
    """FenJue 定时任务调度器。

    使用方式::

        scheduler = CronScheduler()
        scheduler.add_daily_job("daily_score", "30 15 * * 1-5", scheduler.run_score_snapshot)
        scheduler.add_weekly_job("weekly_review", "0 17 * * 5", scheduler.run_weekly_review)
        scheduler.start()
        # ... app runs ...
        scheduler.stop()

    cron 表达式格式 (5 字段):
        minute hour day month day_of_week
        0    15   *   *     1-5         → 每个交易日 15:00:00
        0    17   *   *     5           → 每周五 17:00:00
    """

    # Default paths (relative to project root)
    DEFAULT_DB_PATH = str(_PROJECT_ROOT / "data" / "fenjue.db")
    DEFAULT_CONFIG_PATH = str(_PROJECT_ROOT / "config" / "fenjue.yaml")
    SCORES_DIR = str(_PROJECT_ROOT / "research" / "data" / "scores")
    JOURNAL_DIR = str(_PROJECT_ROOT / "research" / "journal")

    def __init__(
        self,
        timezone: str = "Asia/Shanghai",
        db_path: str | None = None,
        config_path: str | None = None,
    ) -> None:
        self._timezone = timezone
        self._db_path = db_path or self.DEFAULT_DB_PATH
        self._config_path = config_path or self.DEFAULT_CONFIG_PATH
        self._job_store = SQLiteJobStore(self._db_path)
        self._scheduler = BackgroundScheduler(
            jobstores={"default": MemoryJobStore()},
            executors={"default": ThreadPoolExecutor(max_workers=4)},
            job_defaults={"coalesce": True, "max_instances": 1},
            timezone=self._timezone,
        )
        self._started = False
        self._scorer = None  # Lazy-loaded ScoringEngine

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_daily_job(
        self,
        name: str,
        cron_expr: str,
        func: Callable[..., Any],
        args: Optional[tuple] = None,
        kwargs: Optional[dict] = None,
    ) -> None:
        """注册一个每日执行的定时任务。"""
        self._job_store.save_job(name, cron_expr)
        trigger = self._parse_cron(cron_expr)
        self._scheduler.add_job(
            func=self._wrap_job(name, func),
            trigger=trigger,
            args=args or (),
            kwargs=kwargs or {},
            id=name,
            name=name,
            replace_existing=True,
        )

    def add_weekly_job(
        self,
        name: str,
        cron_expr: str,
        func: Callable[..., Any],
        args: Optional[tuple] = None,
        kwargs: Optional[dict] = None,
    ) -> None:
        """注册一个每周执行的定时任务。"""
        self.add_daily_job(name, cron_expr, func, args, kwargs)

    def add_job(
        self,
        name: str,
        cron_expr: str,
        func: Callable[..., Any],
        args: Optional[tuple] = None,
        kwargs: Optional[dict] = None,
    ) -> None:
        """通用任务注册。"""
        self.add_daily_job(name, cron_expr, func, args, kwargs)

    def remove_job(self, name: str) -> None:
        """Remove a job — disables it in DB and removes from APScheduler if present."""
        try:
            self._scheduler.remove_job(name)
        except Exception:
            pass  # may not be registered yet
        conn = self._job_store._connect()
        try:
            conn.execute(
                "UPDATE scheduler_jobs SET enabled = 0 WHERE name = ?", (name,)
            )
            conn.commit()
        finally:
            conn.close()

    def start(self) -> None:
        """启动调度器（幂等）。

        首次启动时从 SQLite 加载已持久化的 job 定义，
        使用默认回调注册到 APScheduler。
        """
        if self._started:
            return

        # 从 DB 恢复已持久化的 jobs
        persisted = self._job_store.load_jobs()
        for job in persisted:
            name = job["name"]
            cron_expr = job["cron_expr"]
            func = self._resolve_func(name)
            if func is not None:
                trigger = self._parse_cron(cron_expr)
                self._scheduler.add_job(
                    func=self._wrap_job(name, func),
                    trigger=trigger,
                    id=name,
                    name=name,
                    replace_existing=True,
                )

        self._scheduler.start()
        self._started = True

    def stop(self) -> None:
        """停止调度器（等待正在执行的任务完成）。"""
        if self._started:
            self._scheduler.shutdown(wait=True)
            self._started = False

    def is_running(self) -> bool:
        return self._started

    def list_jobs(self) -> list[dict]:
        """列出当前注册的所有任务。"""
        return [
            {
                "id": j.id,
                "name": j.name,
                "next_run": str(j.next_run_time) if j.next_run_time else None,
            }
            for j in self._scheduler.get_jobs()
        ]

    # ------------------------------------------------------------------
    # Core job implementations
    # ------------------------------------------------------------------

    def run_score_snapshot(self) -> None:
        """每日评分快照：调用 ScoringEngine 对观察列表评分，保存 JSON。

        接入宏观管线（EventRegistry + MacroIndustryMapper）和反馈引擎
        （FeedbackEngine）。

        输出路径: research/data/scores/{YYYY-MM-DD}.json
        """
        engine = self._get_scorer()
        today = date.today().isoformat()

        # ── 宏观管线 ──────────────────────────────────────────────────
        registry = todays_registry()
        registry.tick()                          # 衰减到期事件
        macro_impact = registry.regime_impact()  # → position_cap_adj, regime_override

        mapper = MacroIndustryMapper()
        mapper.load_events(registry.breakdown())
        industry_weights = mapper.map()
        sector_effect = mapper.sector_multiplier_effect()

        # ── 反馈引擎 ──────────────────────────────────────────────────
        fe = FeedbackEngine(self._config_path)

        # 1. 获取观察列表（watchlist JOIN stocks）
        watchlist = self._get_watchlist()

        # 2. 逐只评分
        results: list[dict[str, Any]] = []
        for item in watchlist:
            code = item["code"]
            name = item["name"]
            quote = self._get_quote_data(code)
            try:
                # Macro context stored in snapshot, NOT multiplied into raw score
                # (position caps belong in ExecutionPlanner)
                score = engine.score_stock(code, quote)
            except Exception as exc:
                score = {"code": code, "error": str(exc)}
            score["name"] = name
            results.append(score)

            # ── money flow axis (separate from Research score) ──────────
            mf_health = score.get("capital_health", "unknown")
            mf_stars = score.get("capital_health_stars", 0)
            print(f"  [{code} {name}] Research={score.get('total',0):.2f}  "
                  f"CapitalHealth={'★'*mf_stars} {mf_health}")

            # 写入反馈日志（无异常时）
            if "error" not in score:
                try:
                    fe.log_prediction(code, score)
                except Exception:
                    pass  # 反馈写入失败不影响主流程

        # 3. 构建快照
        # Aggregate capital health distribution for the snapshot summary
        health_counts: dict[str, int] = {}
        avg_stars = 0.0
        star_total = 0
        star_count = 0
        for r in results:
            if "error" not in r:
                h = r.get("capital_health", "unknown")
                health_counts[h] = health_counts.get(h, 0) + 1
                s = r.get("capital_health_stars", 0)
                if s:
                    star_total += s
                    star_count += 1
        if star_count:
            avg_stars = round(star_total / star_count, 2)

        snapshot = {
            "date": today,
            "generated_at": datetime.now().isoformat(),
            "engine": "ScoringEngine",
            "count": len(results),
            "macro": {
                "active_events": len(registry.events),
                "net_score": macro_impact["net_score"],
                "regime_note": macro_impact["note"],
                "position_cap_adj": macro_impact["position_cap_adj"],
                "sector_multiplier_effect": sector_effect,
                "industry_weights": industry_weights,
            },
            "capital_flow_health": {
                "average_stars": avg_stars,
                "distribution": health_counts,
            },
            "scores": results,
        }

        # 4. 写盘
        os.makedirs(self.SCORES_DIR, exist_ok=True)
        out_path = os.path.join(self.SCORES_DIR, f"{today}.json")
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(snapshot, fh, ensure_ascii=False, indent=2)

        # 5. 同步写入 daily_score 表
        self._persist_scores_to_db(results, today)

    def run_weekly_review(self) -> None:
        """每周复盘：读取本周评分文件，计算 Hit Rate / Alpha，保存周报。

        输出路径: research/journal/week-{n}.md
        """
        today = date.today()
        # 计算本周一 ~ 周日
        monday = today - timedelta(days=today.weekday())
        sunday = monday + timedelta(days=6)

        # 1. 收集本周评分文件
        score_files = self._collect_weekly_scores(monday, sunday)

        # 2. 聚合分析
        ticker_stats: dict[str, dict[str, Any]] = {}
        for sf in score_files:
            try:
                with open(sf, encoding="utf-8") as fh:
                    snap = json.load(fh)
            except Exception:
                continue
            for entry in snap.get("scores", []):
                code = entry.get("code", "")
                if not code:
                    continue
                if code not in ticker_stats:
                    ticker_stats[code] = {
                        "name": entry.get("name", code),
                        "scores": [],
                        "tiers": [],
                    }
                ticker_stats[code]["scores"].append(entry.get("total", 0))
                ticker_stats[code]["tiers"].append(entry.get("tier", "B"))

        if not ticker_stats:
            hit_rate = alpha = 0.0
        else:
            # Hit Rate: S/A tier 占比
            total_scores = sum(len(v["scores"]) for v in ticker_stats.values())
            hit_count = sum(
                1 for v in ticker_stats.values() for t in v["tiers"] if t in ("S", "A")
            )
            hit_rate = round(hit_count / total_scores * 100, 1) if total_scores else 0.0

            # Alpha: mean excess over 5.0 baseline
            all_scores = [s for v in ticker_stats.values() for s in v["scores"]]
            mean_score = sum(all_scores) / len(all_scores) if all_scores else 0.0
            alpha = round(mean_score - 5.0, 2)

        # 3. 确定周数
        week_num = monday.isocalendar()[1]
        week_label = f"week-{week_num}"

        # 4. 生成周报
        os.makedirs(self.JOURNAL_DIR, exist_ok=True)
        out_path = os.path.join(self.JOURNAL_DIR, f"{week_label}.md")
        content = textwrap.dedent(f"""\
            # Week {week_num} 复盘 — {monday.isoformat()} ~ {sunday.isoformat()}

            ## 统计摘要

            | 指标 | 值 |
            |:---|---:|
            | Hit Rate (S+A 占比) | {hit_rate}% |
            | Alpha (超额基准)    | {alpha} |
            | 覆盖标的数           | {len(ticker_stats)} |
            | 评分文件数           | {len(score_files)} |

            ## 各标的本周评分一览

            | 代码 | 名称 | 均分 | 最高 | 最低 | 最优 Tier |
            |:---|---:|---:|---:|---:|:--:|
        """)

        for code, stats in sorted(ticker_stats.items()):
            sc = stats["scores"]
            tiers = stats["tiers"]
            best_tier = "S" if "S" in tiers else ("A" if "A" in tiers else "B")
            content += (
                f"| {code} | {stats['name']} | {sum(sc)/len(sc):.2f} "
                f"| {max(sc):.1f} | {min(sc):.1f} | {best_tier} |\n"
            )

        content += textwrap.dedent(f"""

            ## 体系审视

            - [ ] 否（90%的情况下选这个）
            - [ ] 产业映射修正：
            - [ ] 权重微调：
            - [ ] 新增失效条件：

            ## 下周关注

            -
        """)

        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(content)

    def verify_30d_predictions(self) -> None:
        """每日验证 30 天前的预测：调用 FeedbackEngine.verify() 逐条对照当天价格验证。

        遍历 ``30`` 天前的反馈记录，对每条未验证的预测获取当前价格，
        调用 ``FeedbackEngine.verify()`` 计算实际收益并标记命中/未命中，
        最后统计并打印整体命中率。
        """
        from engine.feedback import FeedbackEngine

        feedback = self._get_feedback()
        today = date.today()
        date_30d_ago = (today - timedelta(days=30)).isoformat()

        # Load records from exactly 30 days ago
        records = feedback._load_records(date_30d_ago)
        unverified = [
            r for r in records
            if r.hit is None and r.predicted_tier in ("S", "A")
        ]

        if not unverified:
            print(f"[verify_30d] {date_30d_ago}: 无待验证预测 (共 {len(records)} 条记录)")
            return

        verified_count = 0
        hit_count = 0
        for rec in unverified:
            quote = self._get_quote_data(rec.code)
            price = quote.get("price")
            if price is None or price <= 0:
                continue

            try:
                result = feedback.verify(
                    rec.code,
                    current_price=float(price),
                    date_30d_ago=date_30d_ago,
                )
                if result and result.hit is not None:
                    verified_count += 1
                    if result.hit:
                        hit_count += 1
            except Exception as exc:
                print(f"[verify_30d] 验证 {rec.code} 失败: {exc}")

        hit_rate = round(hit_count / verified_count * 100, 1) if verified_count else 0.0
        print(
            f"[verify_30d] {date_30d_ago}: "
            f"验证 {verified_count}/{len(unverified)} 条, "
            f"命中 {hit_count}, 命中率 {hit_rate}%"
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_scorer(self):
        """Lazy-load the ScoringEngine singleton."""
        if self._scorer is None:
            from engine.scoring.scorer import ScoringEngine

            self._scorer = ScoringEngine(self._config_path)
        return self._scorer

    def _get_feedback(self):
        """Lazy-load the FeedbackEngine singleton."""
        from engine.feedback import FeedbackEngine

        return FeedbackEngine(self._config_path)

    def _get_watchlist(self) -> list[dict[str, str]]:
        """Return all stocks in the watchlist (code + name)."""
        try:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT s.code, s.name FROM stocks s "
                "INNER JOIN watchlist w ON w.stock_id = s.id"
            ).fetchall()
            conn.close()
            return [{"code": r["code"], "name": r["name"]} for r in rows]
        except Exception:
            # Fallback — pull codes from the YAML industry tree
            return self._get_watchlist_from_config()

    def _get_watchlist_from_config(self) -> list[dict[str, str]]:
        """Fallback: extract watchlist codes from fenjue.yaml industry_tree."""
        import yaml

        try:
            with open(self._config_path, encoding="utf-8") as fh:
                cfg = yaml.safe_load(fh) or {}
        except Exception:
            return []

        codes: list[dict[str, str]] = []
        seen: set[str] = set()
        for sector in (cfg.get("industry_tree") or {}).values():
            for chain in (sector.get("chains") or {}).values():
                for tickers in chain.values():
                    for c in tickers:
                        if c not in seen:
                            seen.add(c)
                            codes.append({"code": c, "name": c})
        return codes

    @staticmethod
    def _get_quote_data(code: str) -> dict[str, Any]:
        """Fetch quote data for a stock.

        Returns a minimal dict with defaults when live data is unavailable.
        In production, integrate with aquote / ahistory / market data provider.
        """
        # Try daily_score table for most recent entry
        # (stub — always returns neutral defaults for now)
        _ = code
        return {
            "turnover": 6.0,       # neutral — no live data
            "pct_20d": 0.0,        # neutral
        }

    def _persist_scores_to_db(
        self, results: list[dict[str, Any]], today: str
    ) -> None:
        """Write scores into the daily_score table."""
        try:
            conn = sqlite3.connect(self._db_path)
            conn.execute("PRAGMA foreign_keys=ON;")

            for r in results:
                code = r.get("code", "")
                if "error" in r:
                    continue

                # Resolve stock_id
                row = conn.execute(
                    "SELECT id FROM stocks WHERE code = ?", (code,)
                ).fetchone()
                if row is None:
                    continue
                stock_id = row[0]

                conn.execute(
                    """INSERT OR REPLACE INTO daily_score
                       (stock_id, date, total_score, industry_score, flow_score,
                        inst_score, margin_score, quant_score, expect_score,
                        confidence, tier)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        stock_id,
                        today,
                        r.get("total"),
                        r.get("industry"),
                        r.get("flow"),
                        r.get("inst"),
                        r.get("margin"),
                        r.get("quant"),
                        r.get("expect"),
                        r.get("confidence"),
                        r.get("tier"),
                    ),
                )
            conn.commit()
            conn.close()
        except Exception:
            pass  # non-fatal — scores JSON is the primary artifact

    def _collect_weekly_scores(self, monday: date, sunday: date) -> list[str]:
        """Return paths to score JSON files within [monday, sunday]."""
        if not os.path.isdir(self.SCORES_DIR):
            return []
        files: list[str] = []
        d = monday
        while d <= sunday:
            path = os.path.join(self.SCORES_DIR, f"{d.isoformat()}.json")
            if os.path.isfile(path):
                files.append(path)
            d += timedelta(days=1)
        return files

    def _wrap_job(self, name: str, func: Callable[..., Any]) -> Callable[..., Any]:
        """Wrap a job function so status is tracked in SQLite."""

        def _wrapper(*args: Any, **kwargs: Any) -> None:
            self._job_store.update_status(name, "running")
            try:
                func(*args, **kwargs)
                self._job_store.update_status(name, "success")
            except Exception:
                self._job_store.update_status(name, "failed")
                raise

        return _wrapper

    def _resolve_func(self, name: str) -> Callable[..., Any] | None:
        """Map a persisted job name back to its callback.

        Extend this mapping when new scheduled jobs are added.
        """
        mapping: dict[str, Callable[..., Any]] = {
            "daily_score": self.run_score_snapshot,
            "weekly_review": self.run_weekly_review,
            "verify_30d_predictions": self.verify_30d_predictions,
        }
        return mapping.get(name)

    @staticmethod
    def _parse_cron(expr: str) -> CronTrigger:
        """将 5 字段 cron 表达式解析为 APScheduler CronTrigger。"""
        parts = expr.strip().split()
        if len(parts) != 5:
            raise ValueError(
                f"无效的 cron 表达式: '{expr}' — 需要 5 字段 "
                f"(minute hour day month day_of_week)"
            )
        minute, hour, day, month, day_of_week = parts
        return CronTrigger(
            minute=minute,
            hour=hour,
            day=day,
            month=month,
            day_of_week=day_of_week,
        )
