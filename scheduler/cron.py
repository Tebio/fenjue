"""FenJue Engine — Task Scheduler

基于 APScheduler 构建的定时任务框架。
支持 daily/weekly cron 表达式，提供每日评分快照、每周复盘等预留接口。
"""

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.executors.pool import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Callable, Optional


class CronScheduler:
    """FenJue 定时任务调度器。

    使用方式:

        scheduler = CronScheduler()
        scheduler.add_daily_job("daily_score", "30 15 * * 1-5", my_func)
        scheduler.add_weekly_job("weekly_review", "0 17 * * 5", my_func)
        scheduler.start()
        # ... app runs ...
        scheduler.stop()

    cron 表达式格式 (5 字段):
        minute hour day month day_of_week
        0    15   *   *     1-5         → 每个交易日 15:00:00
        0    17   *   *     5           → 每周五 17:00:00
    """

    def __init__(self, timezone: str = "Asia/Shanghai"):
        self._timezone = timezone
        self._scheduler = BackgroundScheduler(
            jobstores={"default": MemoryJobStore()},
            executors={"default": ThreadPoolExecutor(max_workers=4)},
            job_defaults={"coalesce": True, "max_instances": 1},
            timezone=self._timezone,
        )
        self._started = False

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
        """注册一个每日执行的定时任务。

        Args:
            name: 任务唯一标识
            cron_expr: 5 字段 cron 表达式 (minute hour day month day_of_week)
            func: 回调函数
            args: 位置参数
            kwargs: 关键字参数
        """
        trigger = self._parse_cron(cron_expr)
        self._scheduler.add_job(
            func=func,
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
        """注册一个每周执行的定时任务。

        与 add_daily_job 相同，语义上用于区分"每周"类任务。
        """
        self.add_daily_job(name, cron_expr, func, args, kwargs)

    def add_job(
        self,
        name: str,
        cron_expr: str,
        func: Callable[..., Any],
        args: Optional[tuple] = None,
        kwargs: Optional[dict] = None,
    ) -> None:
        """通用任务注册（等同于 add_daily_job）。"""
        self.add_daily_job(name, cron_expr, func, args, kwargs)

    def remove_job(self, name: str) -> None:
        """移除指定任务。"""
        self._scheduler.remove_job(name)

    def start(self) -> None:
        """启动调度器（幂等 — 重复调用无副作用）。"""
        if not self._started:
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
    # Reserved interfaces — 每日评分快照 / 每周复盘
    # ------------------------------------------------------------------

    def run_score_snapshot(self) -> None:
        """预留接口：每日评分快照。

        实现后：扫描当前评分池，生成 JSON 快照写入 research/data/scores/。
        """
        pass  # TODO: Phase 2 — 接入 engine.scoring

    def run_weekly_review(self) -> None:
        """预留接口：每周复盘。

        实现后：汇总本周评分变化、生成复盘报告写入 research/journal/。
        """
        pass  # TODO: Phase 2 — 接入 engine.backtest

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_cron(expr: str) -> CronTrigger:
        """将 5 字段 cron 表达式解析为 APScheduler CronTrigger。"""
        parts = expr.strip().split()
        if len(parts) != 5:
            raise ValueError(
                f"无效的 cron 表达式: '{expr}' — 需要 5 字段 (minute hour day month day_of_week)"
            )
        minute, hour, day, month, day_of_week = parts
        return CronTrigger(
            minute=minute,
            hour=hour,
            day=day,
            month=month,
            day_of_week=day_of_week,
        )
