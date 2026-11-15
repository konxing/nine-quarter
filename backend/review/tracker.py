"""决策追踪：推荐股第 1/3/5 交易日表现，相对行业与基准（沪深300）。

收益以推荐时参考价（当日收盘）为基准到评估日收盘；行业收益为同行业
在市成员同窗口收益均值。缺数据则跳过，绝不估算。幂等：已记录不重复。
"""
from __future__ import annotations

import sqlite3

CHECKPOINTS = (1, 3, 5)


def trading_day_count(conn: sqlite3.Connection, start: str, end: str) -> int:
    """(start, end] 区间内的交易日数。"""
    r = conn.execute(
        "SELECT COUNT(*) n FROM trade_calendar "
        "WHERE date>? AND date<=? AND is_trading_day=1", (start, end)).fetchone()
    return int(r["n"])


def checkpoint_date(conn: sqlite3.Connection, start: str, n: int) -> str | None:
    """start 之后第 n 个交易日的日期（交易日历缺失则 None）。"""
    if n <= 0:
        return None
    r = conn.execute(
        "SELECT date FROM trade_calendar WHERE date>? AND is_trading_day=1 "
        "ORDER BY date LIMIT 1 OFFSET ?", (start, n - 1)).fetchone()
    return r["date"] if r else None


def _close(conn: sqlite3.Connection, code: str, date: str) -> float | None:
    r = conn.execute("SELECT close FROM daily_bars WHERE code=? AND date=?",
                     (code, date)).fetchone()
    if r and r["close"] is not None:
        return float(r["close"])
    r = conn.execute("SELECT close FROM index_bars WHERE code=? AND date=?",
                     (code, date)).fetchone()
    return float(r["close"]) if r and r["close"] is not None else None


def _industry_return(conn: sqlite3.Connection, industry: str,
                     start: str, end: str) -> float | None:
    if not industry:
        return None
    rows = conn.execute(
        "SELECT b1.close c0, b2.close c1 FROM stocks s "
        "JOIN daily_bars b1 ON b1.code=s.code AND b1.date=? "
        "JOIN daily_bars b2 ON b2.code=s.code AND b2.date=? "
        "WHERE s.industry=? AND s.type='1' AND s.status='1'",
        (start, end, industry)).fetchall()
    rets = [(r["c1"] / r["c0"] - 1) * 100 for r in rows
            if r["c0"] and r["c1"] and r["c0"] > 0]
    return sum(rets) / len(rets) if rets else None


def update_outcomes(conn: sqlite3.Connection, eval_date: str,
                    index_code: str = "sh.000300") -> int:
    picks = conn.execute("SELECT * FROM picks").fetchall()
    inserted = 0
    for p in picks:
        for cp in CHECKPOINTS:
            exists = conn.execute(
                "SELECT 1 FROM pick_outcomes WHERE pick_id=? AND checkpoint=?",
                (p["id"], cp)).fetchone()
            if exists:
                continue
            cp_date = checkpoint_date(conn, p["run_date"], cp)
            # 复盘可能漏跑某一天：用该检查点的真实交易日补记，不能用之后的日期冒充
            if not cp_date or cp_date > eval_date:
                continue
            eval_close = _close(conn, p["code"], cp_date)
            if eval_close is None:
                continue
            ref = p["ref_price"] or _close(conn, p["code"], p["run_date"])
            if not ref:
                continue
            ret_pct = (eval_close / ref - 1) * 100
            idx0 = _close(conn, index_code, p["run_date"])
            idx1 = _close(conn, index_code, cp_date)
            index_ret = (idx1 / idx0 - 1) * 100 if idx0 and idx1 else None
            industry = conn.execute("SELECT industry FROM stocks WHERE code=?",
                                    (p["code"],)).fetchone()
            ind_ret = _industry_return(
                conn, industry["industry"] if industry else "", p["run_date"], cp_date)
            excess = ret_pct - index_ret if index_ret is not None else None
            conn.execute(
                "INSERT INTO pick_outcomes(pick_id,checkpoint,eval_date,ret_pct,"
                "industry_ret_pct,index_ret_pct,excess_vs_index) VALUES (?,?,?,?,?,?,?)",
                (p["id"], cp, cp_date, round(ret_pct, 4),
                 round(ind_ret, 4) if ind_ret is not None else None,
                 round(index_ret, 4) if index_ret is not None else None,
                 round(excess, 4) if excess is not None else None))
            inserted += 1
    conn.commit()
    return inserted


def update_position_outcomes(conn: sqlite3.Connection, eval_date: str,
                             index_code: str = "sh.000300") -> int:
    """追踪 AI 持仓判断（持有/减仓/卖出）在第 1/3/5 交易日的价格表现。

    判断对错由复盘解读：如卖出后下跌为正确、持有后上涨为正确。
    漏跑检查点时按该检查点的真实交易日补记，不用后续价格冒充。
    """
    decisions = conn.execute("SELECT * FROM position_decisions").fetchall()
    inserted = 0
    for d in decisions:
        for cp in CHECKPOINTS:
            exists = conn.execute(
                "SELECT 1 FROM position_decision_outcomes WHERE decision_id=? AND checkpoint=?",
                (d["id"], cp)).fetchone()
            if exists:
                continue
            cp_date = checkpoint_date(conn, d["decision_date"], cp)
            if not cp_date or cp_date > eval_date:
                continue
            eval_close = _close(conn, d["code"], cp_date)
            if eval_close is None:
                continue
            ref = d["ref_price"] or _close(conn, d["code"], d["decision_date"])
            if not ref:
                continue
            ret_pct = (eval_close / ref - 1) * 100
            idx0 = _close(conn, index_code, d["decision_date"])
            idx1 = _close(conn, index_code, cp_date)
            index_ret = (idx1 / idx0 - 1) * 100 if idx0 and idx1 else None
            conn.execute(
                "INSERT INTO position_decision_outcomes(decision_id,checkpoint,eval_date,"
                "ret_pct,index_ret_pct) VALUES (?,?,?,?,?)",
                (d["id"], cp, cp_date, round(ret_pct, 4),
                 round(index_ret, 4) if index_ret is not None else None))
            inserted += 1
    conn.commit()
    return inserted
