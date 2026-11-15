"""模拟订单撮合：次日按真实可得开盘价成交，严格遵守 A 股规则。

无未来价格守卫：撮合日必须严格晚于决策日（收盘后决策只能次日执行）。
无法确认成交（停牌/涨跌停/一字板/缺数据/T+1 不足）保留未成交，超期作废。
现金不足时缩减至可买整手；绝不虚构成交。
"""
from __future__ import annotations

import logging
import sqlite3

from .account import eligible_shares, get_account, record_buy, record_sell
from .rules import (
    _code_num,
    fill_check_buy,
    fill_check_sell,
    round_buy_shares,
    trade_costs,
)

log = logging.getLogger("nine-quarter.broker")


def create_order(conn: sqlite3.Connection, decision_date: str, code: str,
                 name: str, side: str, target_weight: float,
                 planned_shares: int, ref_price: float, reason: str) -> int:
    # 幂等：同一决策日、同一股票、同一方向只允许一张订单，
    # 避免每日流程中断重跑时重复建单/重复成交。
    existing = conn.execute(
        "SELECT id FROM orders WHERE decision_date=? AND code=? AND side=? "
        "ORDER BY id LIMIT 1", (decision_date, code, side)).fetchone()
    if existing is not None:
        return existing["id"]
    # 前一日的同方向订单仍未成交时也不再叠加新单，避免同一股票重复买入
    # 导致实际仓位超过单只上限（卖出同理，避免重复计划卖出）。
    pending = conn.execute(
        "SELECT id FROM orders WHERE code=? AND side=? AND status='pending' "
        "ORDER BY id LIMIT 1", (code, side)).fetchone()
    if pending is not None:
        return pending["id"]
    cur = conn.execute(
        "INSERT INTO orders(decision_date,code,name,side,status,target_weight,"
        "planned_shares,ref_price,reason,created_at,updated_at) "
        "VALUES (?,?,?,?, 'pending',?,?,?,?,datetime('now'),datetime('now'))",
        (decision_date, code, name, side, target_weight, planned_shares,
         ref_price, reason))
    conn.commit()
    return cur.lastrowid


def _wait_or_expire(conn, order, expire_days: int, trade_date: str,
                    reason: str) -> str:
    """Count failed execution attempts by distinct trading date, not scheduler retry.

    Existing databases are supported: use the legacy wait_days counter as the
    baseline and store all future attempts in order_attempts.
    """
    with conn:
        attempt = conn.execute(
            "INSERT OR IGNORE INTO order_attempts(order_id, attempt_date, reason) "
            "VALUES (?,?,?)", (order["id"], trade_date, reason))
        if not attempt.rowcount:
            current = conn.execute(
                "SELECT status FROM orders WHERE id=?", (order["id"],)).fetchone()
            return current["status"] if current else "pending"
        wait = order["wait_days"] + 1
        status = "expired" if wait >= expire_days else "pending"
        conn.execute(
            "UPDATE orders SET status=?, wait_days=?, updated_at=datetime('now') "
            "WHERE id=?", (status, wait, order["id"]))
    return status


def _record_trade(conn, order_id, code, side, trade_date, price, shares,
                  costs, price_source="daily_open") -> None:
    conn.execute(
        "INSERT INTO trades(order_id,code,side,trade_date,price,shares,amount,"
        "commission,stamp_tax,transfer_fee,price_source,created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,datetime('now'))",
        (order_id, code, side, trade_date, price, shares, shares * price,
         costs["commission"], costs["stamp_tax"], costs["transfer_fee"], price_source))


def _affordable_buy_shares(conn, code, price, planned, cost_kwargs) -> int:
    cash = get_account(conn)["cash"]
    est = round_buy_shares(code, int(cash / (price * 1.001))) if price > 0 else 0
    shares = min(planned, est)
    step = 1 if _code_num(code).startswith(("688", "689")) else 100
    while shares > 0:
        costs = trade_costs(shares * price, "buy", **cost_kwargs)
        if shares * price + costs["total"] <= cash + 1e-6:
            return shares
        shares = round_buy_shares(code, shares - step)
    return 0


def process_pending_orders(conn: sqlite3.Connection, trade_date: str,
                           bars: dict[str, dict], expire_days: int = 3,
                           cost_kwargs: dict | None = None,
                           price_source: str = "daily_open") -> list[dict]:
    """处理所有 pending 订单。bars 为撮合日真实日线（含 open/preclose/trade_status）。

    price_source：daily_open（盘后按当日开盘价）或 realtime_snapshot（上午实时价）。
    """
    cost_kwargs = cost_kwargs or {}
    orders = conn.execute(
        "SELECT * FROM orders WHERE status='pending' ORDER BY id").fetchall()
    events: list[dict] = []
    for o in orders:
        # 无未来价格守卫：撮合日必须严格晚于决策日
        if trade_date <= o["decision_date"]:
            continue
        code = o["code"]
        bar = bars.get(code)
        if bar is None:
            status = _wait_or_expire(conn, o, expire_days, trade_date, "无当日行情")
            events.append(dict(order_id=o["id"], code=code, action=status,
                               reason="无当日行情"))
            continue
        is_st = bool(bar.get("is_st", 0))
        if o["side"] == "buy":
            ok, price, reason = fill_check_buy(code, bar, is_st)
            if not ok:
                status = _wait_or_expire(conn, o, expire_days, trade_date, reason)
                events.append(dict(order_id=o["id"], code=code, action=status, reason=reason))
                continue
            shares = _affordable_buy_shares(conn, code, price, o["planned_shares"], cost_kwargs)
            if shares <= 0:
                status = _wait_or_expire(conn, o, expire_days, trade_date, "现金不足")
                events.append(dict(order_id=o["id"], code=code, action=status, reason="现金不足"))
                continue
            costs = trade_costs(shares * price, "buy", **cost_kwargs)
            # Account movement, trade ledger, and order status must commit atomically.
            with conn:
                record_buy(conn, code, trade_date, shares, price, costs, commit=False)
                _record_trade(conn, o["id"], code, "buy", trade_date, price, shares, costs, price_source)
                conn.execute(
                    "UPDATE orders SET status='filled', filled_date=?, filled_price=?, "
                    "filled_shares=?, fees=?, updated_at=datetime('now') WHERE id=?",
                    (trade_date, price, shares, costs["total"], o["id"]))
            events.append(dict(order_id=o["id"], code=code, action="filled",
                               side="buy", price=price, shares=shares))
        else:  # sell
            elig = eligible_shares(conn, code, trade_date)
            if elig <= 0:
                status = _wait_or_expire(conn, o, expire_days, trade_date, "T+1 可卖不足")
                events.append(dict(order_id=o["id"], code=code, action=status,
                                   reason="T+1 可卖不足"))
                continue
            ok, price, reason = fill_check_sell(code, bar, is_st)
            if not ok:
                status = _wait_or_expire(conn, o, expire_days, trade_date, reason)
                events.append(dict(order_id=o["id"], code=code, action=status, reason=reason))
                continue
            shares = min(o["planned_shares"], elig)
            costs = trade_costs(shares * price, "sell", **cost_kwargs)
            with conn:
                record_sell(conn, code, trade_date, shares, price, costs, commit=False)
                _record_trade(conn, o["id"], code, "sell", trade_date, price, shares, costs, price_source)
                conn.execute(
                    "UPDATE orders SET status='filled', filled_date=?, filled_price=?, "
                    "filled_shares=?, fees=?, updated_at=datetime('now') WHERE id=?",
                    (trade_date, price, shares, costs["total"], o["id"]))
            events.append(dict(order_id=o["id"], code=code, action="filled",
                               side="sell", price=price, shares=shares))
    return events