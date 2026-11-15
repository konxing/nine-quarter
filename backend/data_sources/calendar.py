"""交易日历查询（数据来自 BaoStock query_trade_dates，存于 trade_calendar 表）。

所有日期均为 YYYY-MM-DD 字符串。未知日期（日历未覆盖）抛 ValueError，
迫使调用方先更新日历，而不是猜测。
"""
from __future__ import annotations

import sqlite3


def is_trading_day(conn: sqlite3.Connection, date: str) -> bool:
    row = conn.execute(
        "SELECT is_trading_day FROM trade_calendar WHERE date=?", (date,)
    ).fetchone()
    if row is None:
        raise ValueError(f"交易日历未覆盖 {date}，请先更新日历")
    return bool(row["is_trading_day"])


def next_trading_day(conn: sqlite3.Connection, date: str, n: int = 1) -> str | None:
    """date 之后第 n 个交易日（不含 date 当日）。超出日历范围返回 None。"""
    rows = conn.execute(
        "SELECT date FROM trade_calendar WHERE date>? AND is_trading_day=1 "
        "ORDER BY date LIMIT ?",
        (date, n),
    ).fetchall()
    if len(rows) < n:
        return None
    return rows[-1]["date"]


def prev_trading_day(conn: sqlite3.Connection, date: str, n: int = 1) -> str | None:
    """date 之前第 n 个交易日（不含 date 当日）。"""
    rows = conn.execute(
        "SELECT date FROM trade_calendar WHERE date<? AND is_trading_day=1 "
        "ORDER BY date DESC LIMIT ?",
        (date, n),
    ).fetchall()
    if len(rows) < n:
        return None
    return rows[-1]["date"]


def trading_days_between(conn: sqlite3.Connection, start: str, end: str) -> list[str]:
    """[start, end] 闭区间内的交易日列表。"""
    rows = conn.execute(
        "SELECT date FROM trade_calendar WHERE date>=? AND date<=? "
        "AND is_trading_day=1 ORDER BY date",
        (start, end),
    ).fetchall()
    return [r["date"] for r in rows]