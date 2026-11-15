"""数据更新编排：日历、股票池、日线增量/回填、指数。

断点续传：每股按 last_bar_date 续接；已达标股票跳过 -> 任务中断可重跑。
容错：单股失败记录并继续；失败比例过高（>20%）抛 DataSourceError，
调用方停止，不得用残缺数据冒充完整行情。
"""
from __future__ import annotations

import datetime as dt
import logging
import sqlite3

from .baostock_source import BaoStockSource, DataSourceError
from .collector import (
    active_stock_codes,
    last_bar_date,
    upsert_bars,
    upsert_calendar,
    upsert_index_bars,
    upsert_stocks,
)

log = logging.getLogger("nine-quarter.update")


def latest_available_date(bs: BaoStockSource, today: str | None = None) -> str:
    """以沪指最近一根日线确定数据源已发布到的最新日期。"""
    today = today or dt.date.today().isoformat()
    start = (dt.date.fromisoformat(today) - dt.timedelta(days=15)).isoformat()
    rows = bs.index_daily("sh.000001", start, today)
    dates = [r["date"] for r in rows if r.get("date")]
    if not dates:
        raise DataSourceError("无法确定最新可用行情日期（指数无数据）")
    return max(dates)


def ensure_calendar(conn: sqlite3.Connection, bs: BaoStockSource,
                    start: str, end: str) -> int:
    days = bs.trade_dates(start, end)
    return upsert_calendar(conn, days)


def refresh_stock_pool(conn: sqlite3.Connection, bs: BaoStockSource) -> int:
    return upsert_stocks(conn, bs.stock_basic())


def update_bars(conn: sqlite3.Connection, bs: BaoStockSource,
                start: str, end: str, progress_every: int = 200) -> dict:
    """增量/回填日线到 [start, end]。返回统计。"""
    codes = active_stock_codes(conn)
    total = len(codes)
    if total == 0:
        raise DataSourceError("股票池为空，请先 refresh_stock_pool")
    done = skipped = failed = inserted = rejected = 0
    fail_codes: list[str] = []
    for i, code in enumerate(codes, 1):
        last = last_bar_date(conn, code)
        if last and last >= end:
            skipped += 1
        else:
            s = start
            if last and last >= start:
                s = (dt.date.fromisoformat(last) + dt.timedelta(days=1)).isoformat()
            try:
                bars = bs.daily(code, s, end)
                ins, rej = upsert_bars(conn, bars)
                inserted += ins
                rejected += rej
                done += 1
            except Exception as e:
                failed += 1
                fail_codes.append(code)
                log.warning("更新失败 %s: %s", code, e)
        if i % progress_every == 0 or i == total:
            log.info("日线进度 %d/%d（更新%d 跳过%d 失败%d 写入%d 拒收%d）",
                     i, total, done, skipped, failed, inserted, rejected)
    if total and failed / total > 0.20:
        raise DataSourceError(
            f"日线更新失败比例过高 {failed}/{total}，停止（示例 {fail_codes[:5]}）")
    return dict(total=total, updated=done, skipped=skipped, failed=failed,
                inserted=inserted, rejected=rejected, fail_codes=fail_codes)


def update_indices(conn: sqlite3.Connection, bs: BaoStockSource,
                   start: str, end: str, codes: tuple) -> int:
    n = 0
    for code in codes:
        try:
            n += upsert_index_bars(conn, bs.index_daily(code, start, end))
        except Exception as e:
            log.warning("指数更新失败 %s: %s", code, e)
    return n


def run_initial(conn: sqlite3.Connection, cfg, today: str | None = None) -> dict:
    """首次初始化：日历 + 股票池 + 回填 + 指数。"""
    today = today or dt.date.today().isoformat()
    start = (dt.date.fromisoformat(today)
             - dt.timedelta(days=cfg.backfill_calendar_days)).isoformat()
    future = (dt.date.fromisoformat(today) + dt.timedelta(days=30)).isoformat()
    stats: dict = {}
    with BaoStockSource() as bs:
        stats["calendar"] = ensure_calendar(conn, bs, start, future)
        stats["stocks"] = refresh_stock_pool(conn, bs)
        end = latest_available_date(bs, today)
        stats["data_end"] = end
        stats["bars"] = update_bars(conn, bs, start, end)
        stats["indices"] = update_indices(conn, bs, start, end, cfg.index_codes)
    return stats