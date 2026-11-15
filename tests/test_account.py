"""模拟账户与持仓测试：买卖、T+1、FIFO 成本、收益、回撤。

对应验收要求 6：模拟买入/卖出/持仓/收益。
"""
import sqlite3

import pytest

from backend.db import SCHEMA
from backend.simulation.account import (
    eligible_shares,
    ensure_account,
    get_account,
    get_positions,
    mark_to_market,
    record_buy,
    record_sell,
)
from backend.simulation.rules import trade_costs


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    ensure_account(c, 100000)
    yield c
    c.close()


class TestAccount:
    def test_initial(self, conn):
        a = get_account(conn)
        assert a["cash"] == 100000
        assert a["initial_capital"] == 100000

    def test_ensure_idempotent(self, conn):
        ensure_account(conn, 100000)
        assert get_account(conn)["cash"] == 100000


class TestBuy:
    def test_buy_reduces_cash_and_adds_lot(self, conn):
        costs = trade_costs(10000, "buy")  # 1000股×10元
        record_buy(conn, "sh.600000", "2026-11-09", 1000, 10.0, costs)
        a = get_account(conn)
        assert a["cash"] == pytest.approx(100000 - 10000 - costs["total"])
        pos = get_positions(conn)
        assert pos["sh.600000"]["shares"] == 1000
        assert pos["sh.600000"]["cost_amount"] == pytest.approx(10000 + costs["total"])

    def test_buy_insufficient_cash_raises(self, conn):
        costs = trade_costs(200000, "buy")
        with pytest.raises(ValueError):
            record_buy(conn, "sh.600000", "2026-11-09", 20000, 10.0, costs)


class TestSellT1:
    def test_same_day_cannot_sell(self, conn):
        record_buy(conn, "sh.600000", "2026-11-09", 1000, 10.0, trade_costs(10000, "buy"))
        assert eligible_shares(conn, "sh.600000", "2026-11-09") == 0
        with pytest.raises(ValueError):
            record_sell(conn, "sh.600000", "2026-11-09", 1000, 10.5, trade_costs(10500, "sell"))

    def test_next_day_can_sell(self, conn):
        record_buy(conn, "sh.600000", "2026-11-09", 1000, 10.0, trade_costs(10000, "buy"))
        assert eligible_shares(conn, "sh.600000", "2026-11-10") == 1000

    def test_sell_realized_pnl_fifo(self, conn):
        record_buy(conn, "sh.600000", "2026-11-06", 1000, 10.0, trade_costs(10000, "buy"))
        record_buy(conn, "sh.600000", "2026-11-09", 1000, 12.0, trade_costs(12000, "buy"))
        # 卖 1000，FIFO 用第一笔成本10元；卖价11元
        costs = trade_costs(11000, "sell")
        record_sell(conn, "sh.600000", "2026-11-10", 1000, 11.0, costs)
        pos = get_positions(conn)
        assert pos["sh.600000"]["shares"] == 1000  # 剩第二笔
        a = get_account(conn)
        # 实现盈亏 = 11000 - 费用 - 成本(10000+第一笔费)
        first_cost = 10000 + trade_costs(10000, "buy")["total"]
        expected_realized = 11000 - costs["total"] - first_cost
        assert a["realized_pnl"] == pytest.approx(expected_realized, abs=0.01)

    def test_sell_more_than_held_raises(self, conn):
        record_buy(conn, "sh.600000", "2026-11-06", 1000, 10.0, trade_costs(10000, "buy"))
        with pytest.raises(ValueError):
            record_sell(conn, "sh.600000", "2026-11-10", 2000, 11.0, trade_costs(22000, "sell"))


class TestMarkToMarket:
    def test_total_assets_and_return(self, conn):
        record_buy(conn, "sh.600000", "2026-11-06", 1000, 10.0, trade_costs(10000, "buy"))
        snap = mark_to_market(conn, "2026-11-09", {"sh.600000": 12.0})
        a = get_account(conn)
        assert snap["market_value"] == 12000
        assert snap["total_assets"] == pytest.approx(a["cash"] + 12000)
        assert snap["cum_return"] == pytest.approx(snap["total_assets"] / 100000 - 1)
        assert snap["max_drawdown"] == 0.0

    def test_drawdown_after_drop(self, conn):
        mark_to_market(conn, "2026-11-06", {})  # 空仓 peak=100000
        record_buy(conn, "sh.600000", "2026-11-06", 5000, 10.0, trade_costs(50000, "buy"))
        mark_to_market(conn, "2026-11-09", {"sh.600000": 12.0})  # 总资产上升
        snap = mark_to_market(conn, "2026-11-10", {"sh.600000": 8.0})  # 大跌
        assert snap["max_drawdown"] > 0
        # 峰值约为 现金+60000，谷值 现金+40000
        assert snap["peak_assets"] >= snap["total_assets"]

    def test_idempotent_same_date(self, conn):
        mark_to_market(conn, "2026-11-09", {})
        mark_to_market(conn, "2026-11-09", {})
        n = conn.execute("SELECT COUNT(*) n FROM account_daily").fetchone()["n"]
        assert n == 1