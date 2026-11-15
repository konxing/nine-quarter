"""数据收集与写入：股票池、日历、日线、指数。

设计原则：
- 幂等：同 code+date 重复写入覆盖，不产生重复行（任务中断可重跑）。
- 校验：异常 bar 拒收并计数，绝不写入错误数据。
- 增量：按每股 last_bar_date 断点续传。
- 网络编排与纯写入分离：纯写入函数可单测，网络部分由真实运行验收。
"""
from __future__ import annotations

import logging
import sqlite3

from .validate import bar_errors

log = logging.getLogger("nine-quarter.collector")


def upsert_stocks(conn: sqlite3.Connection, rows: list[dict]) -> int:
    """写入股票池（仅 type=1 股票）。rows 来自 BaoStock stock_basic。"""
    n = 0
    for d in rows:
        if d.get("type") != "1":
            continue
        code = d.get("code", "")
        if not code:
            continue
        code_num = code.split(".")[-1]
        conn.execute(
            "INSERT INTO stocks(code,code_num,name,list_date,out_date,type,status,updated_at) "
            "VALUES (?,?,?,?,?,?,?,datetime('now')) "
            "ON CONFLICT(code) DO UPDATE SET name=excluded.name, "
            "list_date=excluded.list_date, out_date=excluded.out_date, "
            "status=excluded.status, updated_at=excluded.updated_at",
            (code, code_num, d.get("code_name", ""), d.get("ipoDate", ""),
             d.get("outDate", ""), "1", d.get("status", "1")),
        )
        n += 1
    conn.commit()
    return n


def update_industry(conn: sqlite3.Connection, rows: list[dict]) -> int:
    rows_map = {d["code"]: d.get("industry", "") for d in rows if d.get("code")}
    n = 0
    for code, ind in rows_map.items():
        cur = conn.execute("UPDATE stocks SET industry=? WHERE code=?", (ind, code))
        n += cur.rowcount
    conn.commit()
    return n


def upsert_bars(conn: sqlite3.Connection, bars: list[dict]) -> tuple[int, int]:
    """写入日线，返回 (接收数, 拒收数)。异常 bar 拒收。"""
    ins = rej = 0
    for b in bars:
        errs = bar_errors(b)
        if errs:
            rej += 1
            log.warning("拒收异常 bar %s %s: %s", b.get("code"), b.get("date"), errs)
            continue
        conn.execute(
            "INSERT INTO daily_bars(code,date,open,high,low,close,preclose,volume,"
            "amount,turn,trade_status,pct_chg,pe_ttm,pb_mrq,is_st) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(code,date) DO UPDATE SET open=excluded.open, high=excluded.high, "
            "low=excluded.low, close=excluded.close, preclose=excluded.preclose, "
            "volume=excluded.volume, amount=excluded.amount, turn=excluded.turn, "
            "trade_status=excluded.trade_status, pct_chg=excluded.pct_chg, "
            "pe_ttm=excluded.pe_ttm, pb_mrq=excluded.pb_mrq, is_st=excluded.is_st",
            (b.get("code"), b.get("date"), b.get("open"), b.get("high"),
             b.get("low"), b.get("close"), b.get("preclose"), b.get("volume"),
             b.get("amount"), b.get("turn"), b.get("trade_status"),
             b.get("pct_chg"), b.get("pe_ttm"), b.get("pb_mrq"), b.get("is_st", 0)),
        )
        ins += 1
    conn.commit()
    return ins, rej


def upsert_index_bars(conn: sqlite3.Connection, bars: list[dict]) -> int:
    n = 0
    for b in bars:
        conn.execute(
            "INSERT INTO index_bars(code,date,open,high,low,close,preclose,volume,amount,pct_chg) "
            "VALUES (?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(code,date) DO UPDATE SET open=excluded.open, high=excluded.high, "
            "low=excluded.low, close=excluded.close, preclose=excluded.preclose, "
            "volume=excluded.volume, amount=excluded.amount, pct_chg=excluded.pct_chg",
            (b.get("code"), b.get("date"), b.get("open"), b.get("high"),
             b.get("low"), b.get("close"), b.get("preclose"), b.get("volume"),
             b.get("amount"), b.get("pct_chg")),
        )
        n += 1
    conn.commit()
    return n


def upsert_calendar(conn: sqlite3.Connection, days: list[tuple[str, int]]) -> int:
    conn.executemany(
        "INSERT INTO trade_calendar(date,is_trading_day) VALUES (?,?) "
        "ON CONFLICT(date) DO UPDATE SET is_trading_day=excluded.is_trading_day",
        days,
    )
    conn.commit()
    return len(days)


def last_bar_date(conn: sqlite3.Connection, code: str) -> str | None:
    row = conn.execute(
        "SELECT MAX(date) AS d FROM daily_bars WHERE code=?", (code,)
    ).fetchone()
    return row["d"] if row and row["d"] else None


def active_stock_codes(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT code FROM stocks WHERE type='1' AND status='1' ORDER BY code"
    ).fetchall()
    return [r["code"] for r in rows]