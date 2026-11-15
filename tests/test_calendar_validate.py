"""交易日历与数据校验测试。

对应验收要求 2（数据异常时停止使用错误数据）与
测试要求（非交易日、数据重复、无行情数据）。
"""
import sqlite3

import pytest

from backend.data_sources.calendar import (
    is_trading_day,
    next_trading_day,
    prev_trading_day,
    trading_days_between,
)
from backend.data_sources.validate import bar_errors, check_coverage
from backend.db import SCHEMA


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    # 2026-11-06 周五交易日，07/08 周末，09 周一交易日
    days = [
        ("2026-11-05", 1), ("2026-11-06", 1),
        ("2026-11-07", 0), ("2026-11-08", 0),
        ("2026-11-09", 1), ("2026-11-10", 1),
        ("2026-11-11", 1),
    ]
    c.executemany("INSERT INTO trade_calendar(date,is_trading_day) VALUES (?,?)", days)
    c.commit()
    yield c
    c.close()


class TestCalendar:
    def test_weekday_is_trading(self, conn):
        assert is_trading_day(conn, "2026-11-09") is True

    def test_weekend_not_trading(self, conn):
        assert is_trading_day(conn, "2026-11-08") is False

    def test_unknown_date_raises(self, conn):
        with pytest.raises(ValueError):
            is_trading_day(conn, "2027-01-01")

    def test_next_trading_day_skips_weekend(self, conn):
        assert next_trading_day(conn, "2026-11-06") == "2026-11-09"

    def test_next_trading_day_n2(self, conn):
        assert next_trading_day(conn, "2026-11-06", 2) == "2026-11-10"

    def test_prev_trading_day(self, conn):
        assert prev_trading_day(conn, "2026-11-09") == "2026-11-06"

    def test_next_beyond_calendar_returns_none(self, conn):
        assert next_trading_day(conn, "2026-11-11") is None

    def test_trading_days_between(self, conn):
        assert trading_days_between(conn, "2026-11-06", "2026-11-10") == [
            "2026-11-06", "2026-11-09", "2026-11-10"]


class TestBarValidation:
    def test_valid_bar_no_errors(self):
        row = dict(open=10.0, high=10.5, low=9.8, close=10.2,
                   preclose=10.0, volume=1000, amount=10000, trade_status=1)
        assert bar_errors(row) == []

    def test_high_below_low_rejected(self):
        row = dict(open=10.0, high=9.0, low=9.8, close=10.2,
                   preclose=10.0, volume=1000, amount=10000, trade_status=1)
        assert any("high" in e for e in bar_errors(row))

    def test_close_outside_range_rejected(self):
        row = dict(open=10.0, high=10.5, low=9.8, close=11.0,
                   preclose=10.0, volume=1000, amount=10000, trade_status=1)
        assert any("close" in e for e in bar_errors(row))

    def test_negative_volume_rejected(self):
        row = dict(open=10.0, high=10.5, low=9.8, close=10.2,
                   preclose=10.0, volume=-1, amount=10000, trade_status=1)
        assert any("volume" in e for e in bar_errors(row))

    def test_zero_price_trading_bar_rejected(self):
        row = dict(open=0, high=0, low=0, close=0,
                   preclose=10.0, volume=1000, amount=10000, trade_status=1)
        assert bar_errors(row) != []

    def test_suspended_empty_prices_allowed(self):
        row = dict(open=None, high=None, low=None, close=None,
                   preclose=None, volume=0, amount=0, trade_status=0)
        assert bar_errors(row) == []

    def test_suspended_empty_string_volume_allowed(self):
        # 真实 BaoStock 停牌日：volume/价格均为空字符串，tradestatus=0
        row = dict(open="", high="", low="", close="", preclose="",
                   volume="", amount="", trade_status="0")
        assert bar_errors(row) == []

    def test_missing_fields_rejected(self):
        assert bar_errors({}) != []


class TestCoverage:
    def _seed_bars(self, conn, codes, date):
        conn.executemany(
            "INSERT OR REPLACE INTO daily_bars(code,date,close,trade_status) VALUES (?,?,10.0,1)",
            [(c, date) for c in codes])
        conn.commit()

    def test_full_coverage_ok(self, conn):
        conn.executemany(
            "INSERT INTO stocks(code,code_num,name,type,status,updated_at) VALUES (?,?,?,?, '1','now')",
            [("sh.600000", "600000", "浦发银行", "1"), ("sz.000001", "000001", "平安银行", "1")])
        self._seed_bars(conn, ["sh.600000", "sz.000001"], "2026-11-09")
        ok, cov, _ = check_coverage(conn, "2026-11-09", min_coverage=0.9)
        assert ok is True
        assert cov == 1.0

    def test_missing_data_rejected(self, conn):
        conn.executemany(
            "INSERT INTO stocks(code,code_num,name,type,status,updated_at) VALUES (?,?,?,?, '1','now')",
            [("sh.600000", "600000", "浦发银行", "1"), ("sz.000001", "000001", "平安银行", "1")])
        self._seed_bars(conn, ["sh.600000"], "2026-11-09")
        ok, cov, _ = check_coverage(conn, "2026-11-09", min_coverage=0.9)
        assert ok is False
        assert cov == 0.5

    def test_delisted_stocks_excluded_from_denominator(self, conn):
        conn.executemany(
            "INSERT INTO stocks(code,code_num,name,type,status,updated_at) VALUES (?,?,?,?,?, 'now')",
            [("sh.600000", "600000", "浦发银行", "1", "1"),
             ("sh.600001", "600001", "已退市", "1", "0")])
        self._seed_bars(conn, ["sh.600000"], "2026-11-09")
        ok, cov, _ = check_coverage(conn, "2026-11-09", min_coverage=0.9)
        assert ok is True
        assert cov == 1.0

    def test_no_active_stocks_not_ok(self, conn):
        ok, cov, _ = check_coverage(conn, "2026-11-09", min_coverage=0.9)
        assert ok is False