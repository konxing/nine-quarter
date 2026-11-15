"""订单撮合测试：禁止未来价格、次日开盘成交、涨跌停/停牌、到期、T+1 卖出。

对应验收要求 6/7：模拟成交遵守规则，且不能用未来价格模拟历史交易。
"""
import sqlite3

import pytest

from backend.db import SCHEMA
from backend.simulation.account import ensure_account, get_account, record_buy
from backend.simulation.broker import create_order, process_pending_orders
from backend.simulation.rules import trade_costs


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    ensure_account(c, 100000)
    yield c
    c.close()


def _bar(open=10.0, high=10.5, low=9.8, close=10.2, preclose=10.0,
         volume=1_000_000, status=1):
    return dict(open=open, high=high, low=low, close=close, preclose=preclose,
                volume=volume, trade_status=status)


def _order(conn, decision="2026-11-09", code="sh.600000", side="buy",
           shares=1000, weight=0.1, price=10.0):
    return create_order(conn, decision, code, "测试股", side, weight, shares,
                        price, "测试理由")


def _status(conn, oid):
    return conn.execute("SELECT status FROM orders WHERE id=?", (oid,)).fetchone()["status"]


class TestNoLookahead:
    def test_create_order_is_idempotent_per_day(self, conn):
        """任务中断后重跑每日流程时，同一决策日/股票/方向的订单不应重复创建。"""
        a = _order(conn)
        b = _order(conn, shares=500)
        assert a == b
        assert conn.execute("SELECT COUNT(*) n FROM orders").fetchone()["n"] == 1

    def test_no_second_order_while_same_pending_exists(self, conn):
        """前一日买单仍待成交时，次日再次推荐不应叠加第二张单（避免超仓位）。"""
        a = _order(conn, decision="2026-11-09")
        b = _order(conn, decision="2026-11-10")
        assert b == a
        assert conn.execute("SELECT COUNT(*) n FROM orders").fetchone()["n"] == 1

    def test_new_order_allowed_after_previous_filled(self, conn):
        a = _order(conn, decision="2026-11-09")
        conn.execute("UPDATE orders SET status='filled' WHERE id=?", (a,))
        conn.commit()
        b = _order(conn, decision="2026-11-10")
        assert b != a
        assert conn.execute("SELECT COUNT(*) n FROM orders").fetchone()["n"] == 2

    def test_cannot_fill_on_decision_day(self, conn):
        oid = _order(conn, decision="2026-11-09")
        events = process_pending_orders(conn, "2026-11-09", {"sh.600000": _bar()})
        assert _status(conn, oid) == "pending"
        assert conn.execute("SELECT COUNT(*) n FROM trades").fetchone()["n"] == 0
        assert events == []

    def test_cannot_fill_before_decision(self, conn):
        oid = _order(conn, decision="2026-11-09")
        process_pending_orders(conn, "2026-11-06", {"sh.600000": _bar()})
        assert _status(conn, oid) == "pending"


class TestBuyFill:
    def test_next_day_fills_at_open(self, conn):
        oid = _order(conn)
        events = process_pending_orders(conn, "2026-11-10", {"sh.600000": _bar(open=10.0)})
        assert _status(conn, oid) == "filled"
        t = conn.execute("SELECT * FROM trades").fetchone()
        assert t["price"] == 10.0
        assert t["trade_date"] == "2026-11-10"
        assert t["price_source"] == "daily_open"
        assert t["shares"] == 1000
        assert len(events) == 1

    def test_limit_up_open_stays_pending(self, conn):
        oid = _order(conn)
        bar = _bar(open=11.0, high=11.0, low=10.6, preclose=10.0)
        process_pending_orders(conn, "2026-11-10", {"sh.600000": bar})
        assert _status(conn, oid) == "pending"
        assert conn.execute("SELECT COUNT(*) n FROM trades").fetchone()["n"] == 0

    def test_suspended_stays_pending(self, conn):
        oid = _order(conn)
        process_pending_orders(conn, "2026-11-10",
                             {"sh.600000": _bar(status=0, volume=0)})
        assert _status(conn, oid) == "pending"

    def test_missing_bar_stays_pending(self, conn):
        oid = _order(conn)
        process_pending_orders(conn, "2026-11-10", {})
        assert _status(conn, oid) == "pending"
        w = conn.execute("SELECT wait_days FROM orders WHERE id=?", (oid,)).fetchone()["wait_days"]
        assert w == 1

    def test_expire_after_limit_days(self, conn):
        oid = _order(conn)
        bar = _bar(open=11.0, high=11.0, low=11.0, preclose=10.0)  # 一字涨停
        process_pending_orders(conn, "2026-11-10", {"sh.600000": bar}, expire_days=1)
        assert _status(conn, oid) == "expired"

    def test_insufficient_cash_reduces_shares(self, conn):
        # 现金仅 10000，计划 2000 股×10=20000 -> 缩减到可买整手
        conn.execute("UPDATE account SET cash=10000 WHERE id=1")
        oid = _order(conn, shares=2000)
        process_pending_orders(conn, "2026-11-10", {"sh.600000": _bar(open=10.0)})
        assert _status(conn, oid) == "filled"
        t = conn.execute("SELECT shares FROM trades").fetchone()
        assert 0 < t["shares"] <= 1000
        assert t["shares"] % 100 == 0
        assert get_account(conn)["cash"] >= 0


class TestSellFill:
    def test_sell_next_day_after_buy(self, conn):
        record_buy(conn, "sh.600000", "2026-11-06", 1000, 10.0, trade_costs(10000, "buy"))
        oid = _order(conn, side="sell", shares=1000)
        process_pending_orders(conn, "2026-11-10", {"sh.600000": _bar(open=10.5)})
        assert _status(conn, oid) == "filled"
        t = conn.execute("SELECT * FROM trades WHERE side='sell'").fetchone()
        assert t["price"] == 10.5
        assert t["shares"] == 1000

    def test_limit_down_open_cannot_sell(self, conn):
        record_buy(conn, "sh.600000", "2026-11-06", 1000, 10.0, trade_costs(10000, "buy"))
        oid = _order(conn, side="sell", shares=1000)
        bar = _bar(open=9.0, high=9.4, low=9.0, preclose=10.0)
        process_pending_orders(conn, "2026-11-10", {"sh.600000": bar})
        assert _status(conn, oid) == "pending"

    def test_sell_t1_not_eligible_stays_pending(self, conn):
        # 当日买入，次日才决策卖出 -> 撮合日买入批次仍不可卖的情况由 eligible 控制
        record_buy(conn, "sh.600000", "2026-11-10", 1000, 10.0, trade_costs(10000, "buy"))
        oid = _order(conn, decision="2026-11-09", side="sell", shares=1000)
        # 撮合日 2026-11-10 == 买入日 -> 不可卖
        process_pending_orders(conn, "2026-11-10", {"sh.600000": _bar()})
        assert _status(conn, oid) == "pending"

class TestRetryIntegrity:
    def test_failed_attempt_only_once_per_trading_date(self, conn):
        oid = _order(conn)
        for _ in range(4):
            process_pending_orders(conn, "2026-11-10", {}, expire_days=3)
        row = conn.execute(
            "SELECT status,wait_days FROM orders WHERE id=?", (oid,)).fetchone()
        assert (row["status"], row["wait_days"]) == ("pending", 1)
        process_pending_orders(conn, "2026-11-11", {}, expire_days=3)
        process_pending_orders(conn, "2026-11-12", {}, expire_days=3)
        assert _status(conn, oid) == "expired"
        assert conn.execute(
            "SELECT COUNT(*) n FROM order_attempts WHERE order_id=?", (oid,)
        ).fetchone()["n"] == 3

    def test_failed_trade_write_rolls_back_account_and_order(self, conn):
        oid = _order(conn)
        starting_cash = get_account(conn)["cash"]
        conn.execute("""
            CREATE TRIGGER reject_trade BEFORE INSERT ON trades
            BEGIN SELECT RAISE(ABORT, 'forced ledger failure'); END;
        """)
        with pytest.raises(sqlite3.DatabaseError, match="forced ledger failure"):
            process_pending_orders(conn, "2026-11-10", {"sh.600000": _bar()})
        assert get_account(conn)["cash"] == starting_cash
        assert conn.execute("SELECT COUNT(*) n FROM position_lots").fetchone()["n"] == 0
        assert _status(conn, oid) == "pending"
