"""APScheduler 调度：北京时间，工作日触发，内部按交易日历门控节假日。

盘后全流程在多个时间点重试（数据未就绪时），成功则幂等跳过。
单实例 + coalesce 防止重叠；任务异常隔离，不影响调度器存活。
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from ..config import Settings
from ..db import connect, init_db
from ..simulation.account import ensure_account

log = logging.getLogger("nine-quarter.scheduler")
_scheduler: BackgroundScheduler | None = None


def _daily_safe(cfg: Settings) -> None:
    from ..pipeline import DataNotReadyError, run_daily
    conn = connect(cfg.db_path)
    try:
        run_daily(conn, cfg)
    except DataNotReadyError as e:
        log.info("盘后数据未就绪，等待下一重试时段: %s", e)
    except Exception:
        log.exception("盘后任务异常")
    finally:
        conn.close()


def _morning_safe(cfg: Settings) -> None:
    from ..pipeline import run_morning
    conn = connect(cfg.db_path)
    try:
        run_morning(conn, cfg)
    except Exception:
        log.exception("上午任务异常")
    finally:
        conn.close()


def start_scheduler(cfg: Settings) -> BackgroundScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    init_db(cfg.db_path)
    conn = connect(cfg.db_path)
    try:
        ensure_account(conn, cfg.initial_capital)
    finally:
        conn.close()
    sched = BackgroundScheduler(timezone=cfg.timezone)
    mh, mm = cfg.morning_time.split(":")
    sched.add_job(
        _morning_safe, CronTrigger(day_of_week="mon-fri", hour=int(mh), minute=int(mm),
                                   timezone=cfg.timezone),
        args=[cfg], id="morning", coalesce=True, max_instances=1, misfire_grace_time=600)
    for slot in cfg.daily_times.split(","):
        slot = slot.strip()
        if not slot:
            continue
        dh, dm = slot.split(":")
        sched.add_job(
            _daily_safe, CronTrigger(day_of_week="mon-fri", hour=int(dh), minute=int(dm),
                                     timezone=cfg.timezone),
            args=[cfg], id=f"daily-{slot}", coalesce=True, max_instances=1,
            misfire_grace_time=1800)
    sched.start()
    _scheduler = sched
    log.info("调度器已启动：上午 %s，盘后 %s（%s）",
             cfg.morning_time, cfg.daily_times, cfg.timezone)
    return sched


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None