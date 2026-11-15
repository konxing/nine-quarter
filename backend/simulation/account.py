"""模拟账户与持仓：现金、批次成本（FIFO）、T+1 可卖、每日估值与回撤。

Python 负责全部数值计算。持仓按买入批次记录以精确执行 T+1 与成本核算。
所有变更在调用方事务内进行；这里每个函数自行 commit 以便独立使用与测试。
"""
from __future__ import annotations

import sqlite3


def ensure_account(conn: sqlite3.Connection, initial_capital: float) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO account(id,initial_capital,cash,realized_pnl,updated_at) "
        "VALUES (1,?,?,0,datetime('now'))", (initial_capital, initial_capital))
    conn.commit()


def get_account(conn: sqlite3.Connection) -> dict:
    r = conn.execute("SELECT * FROM account WHERE id=1").fetchone()
    if r is None:
        raise ValueError("账户未初始化")
    return dict(r)


def get_positions(conn: sqlite3.Connection) -> dict[str, dict]:
    rows = conn.execute(
        "SELECT code, SUM(shares) shares, SUM(cost_amount) cost_amount "
        "FROM position_lots GROUP BY code HAVING SUM(shares) > 0")
    out = {}
    for r in rows:
        shares = r["shares"]
        cost = r["cost_amount"]
        out[r["code"]] = {
            "shares": shares, "cost_amount": cost,
            "avg_cost": cost / shares if shares else 0.0,
        }
    return out


def eligible_shares(conn: sqlite3.Connection, code: str, date: str) -> int:
    """T+1：仅买入日早于 date 的批次可卖。"""
    r = conn.execute(
        "SELECT COALESCE(SUM(shares),0) s FROM position_lots "
        "WHERE code=? AND buy_date<?", (code, date)).fetchone()
    return int(r["s"])


def record_buy(conn: sqlite3.Connection, code: str, date: str, shares: int,
               price: float, costs: dict, *, commit: bool = True) -> None:
    if shares <= 0:
        raise ValueError("买入股数必须为正")
    amount = shares * price
    total_cost = amount + costs["total"]
    acc = get_account(conn)
    if acc["cash"] < total_cost - 1e-6:
        raise ValueError(f"现金不足：需 {total_cost:.2f}，可用 {acc['cash']:.2f}")
    conn.execute("UPDATE account SET cash=cash-?, updated_at=datetime('now') WHERE id=1",
                 (total_cost,))
    conn.execute(
        "INSERT INTO position_lots(code,buy_date,shares,cost_amount) VALUES (?,?,?,?)",
        (code, date, shares, total_cost))
    if commit:
        conn.commit()


def record_sell(conn: sqlite3.Connection, code: str, date: str, shares: int,
                price: float, costs: dict, *, commit: bool = True) -> float:
    """FIFO 卖出（仅 T+1 可卖批次）。返回已实现盈亏。"""
    if shares <= 0:
        raise ValueError("卖出股数必须为正")
    if eligible_shares(conn, code, date) < shares:
        raise ValueError(f"可卖股数不足（T+1 或持仓不足）：{code} {shares}")
    lots = conn.execute(
        "SELECT id,shares,cost_amount FROM position_lots "
        "WHERE code=? AND buy_date<? AND shares>0 ORDER BY buy_date,id",
        (code, date)).fetchall()
    remaining = shares
    cost_basis = 0.0
    for lot in lots:
        if remaining <= 0:
            break
        take = min(remaining, lot["shares"])
        unit_cost = lot["cost_amount"] / lot["shares"]
        cost_basis += take * unit_cost
        new_shares = lot["shares"] - take
        new_cost = lot["cost_amount"] - take * unit_cost
        conn.execute("UPDATE position_lots SET shares=?, cost_amount=? WHERE id=?",
                     (new_shares, new_cost, lot["id"]))
        remaining -= take
    amount = shares * price
    net = amount - costs["total"]
    realized = net - cost_basis
    conn.execute(
        "UPDATE account SET cash=cash+?, realized_pnl=realized_pnl+?, "
        "updated_at=datetime('now') WHERE id=1", (net, realized))
    conn.execute("DELETE FROM position_lots WHERE shares<=0")
    if commit:
        conn.commit()
    return realized


def mark_to_market(conn: sqlite3.Connection, date: str,
                   prices: dict[str, float]) -> dict:
    """按最新可得价格估值，写每日快照（幂等）。缺价以成本保守计。"""
    acc = get_account(conn)
    positions = get_positions(conn)
    mv = 0.0
    total_cost = 0.0
    for code, p in positions.items():
        px = prices.get(code)
        if px is None:
            px = p["avg_cost"]
        mv += p["shares"] * px
        total_cost += p["cost_amount"]
    total_assets = acc["cash"] + mv
    initial = acc["initial_capital"]
    cum_return = total_assets / initial - 1 if initial else 0.0
    prev = conn.execute(
        "SELECT peak_assets,max_drawdown FROM account_daily WHERE date<? "
        "ORDER BY date DESC LIMIT 1", (date,)).fetchone()
    prev_peak = prev["peak_assets"] if prev else initial
    prev_mdd = prev["max_drawdown"] if prev else 0.0
    peak = max(prev_peak, total_assets)
    dd = (peak - total_assets) / peak if peak else 0.0
    mdd = max(prev_mdd, dd)
    snap = dict(date=date, cash=acc["cash"], market_value=round(mv, 2),
                total_assets=round(total_assets, 2),
                unrealized_pnl=round(mv - total_cost, 2),
                realized_pnl=round(acc["realized_pnl"], 2),
                cum_return=round(cum_return, 6), peak_assets=round(peak, 2),
                max_drawdown=round(mdd, 6))
    conn.execute(
        "INSERT INTO account_daily(date,cash,market_value,total_assets,unrealized_pnl,"
        "realized_pnl,cum_return,peak_assets,max_drawdown) "
        "VALUES (:date,:cash,:market_value,:total_assets,:unrealized_pnl,"
        ":realized_pnl,:cum_return,:peak_assets,:max_drawdown) "
        "ON CONFLICT(date) DO UPDATE SET cash=excluded.cash, "
        "market_value=excluded.market_value, total_assets=excluded.total_assets, "
        "unrealized_pnl=excluded.unrealized_pnl, realized_pnl=excluded.realized_pnl, "
        "cum_return=excluded.cum_return, peak_assets=excluded.peak_assets, "
        "max_drawdown=excluded.max_drawdown", snap)
    conn.commit()
    return snap