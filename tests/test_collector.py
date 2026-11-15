"""数据写入层测试：幂等、校验过滤、增量断点。

对应验收要求 1/2/5 与测试要求（数据重复、任务中断恢复）。
"""
import sqlite3

import pytest

from backend.data_sources.collector import (
    last_bar_date,
    upsert_bars,
    upsert_index_bars,
    upsert_stocks,
)
from backend.db import SCHEMA


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    yield c
    c.close()


def _bar(code="sh.600000", date="2026-11-09", close=10.0, status=1, vol=1000):
    return dict(code=code, date=date, open=close, high=close + 0.5,
                low=close - 0.2, close=close, preclose=close - 0.1,
                volume=vol, amount=vol * close, turn=0.5,
                trade_status=status, pct_chg=1.0, pe_ttm=5.0, pb_mrq=0.6,
                is_st=0)


class TestUpsertBars:
    def test_insert_then_count(self, conn):
        ins, rej = upsert_bars(conn, [_bar()])
        assert ins == 1 and rej == 0
        assert conn.execute("SELECT COUNT(*) n FROM daily_bars").fetchone()["n"] == 1

    def test_duplicate_is_idempotent(self, conn):
        upsert_bars(conn, [_bar()])
        ins, rej = upsert_bars(conn, [_bar(close=10.5)])  # 同 code+date 覆盖
        assert conn.execute("SELECT COUNT(*) n FROM daily_bars").fetchone()["n"] == 1
        row = conn.execute("SELECT close FROM daily_bars").fetchone()
        assert row["close"] == 10.5

    def test_invalid_bar_rejected(self, conn):
        bad = _bar()
        bad["high"] = 1.0  # high < low
        ins, rej = upsert_bars(conn, [bad, _bar(code="sz.000001")])
        assert ins == 1 and rej == 1
        codes = [r["code"] for r in conn.execute("SELECT code FROM daily_bars")]
        assert codes == ["sz.000001"]

    def test_suspended_bar_kept(self, conn):
        susp = dict(code="sh.600000", date="2026-11-09", open=None, high=None,
                    low=None, close=None, preclose=None, volume=0, amount=0,
                    turn=None, trade_status=0, pct_chg=None, pe_ttm=None,
                    pb_mrq=None, is_st=0)
        ins, rej = upsert_bars(conn, [susp])
        assert ins == 1 and rej == 0


class TestLastBarDate:
    def test_none_when_empty(self, conn):
        assert last_bar_date(conn, "sh.600000") is None

    def test_returns_max_date(self, conn):
        upsert_bars(conn, [_bar(date="2026-11-06"), _bar(date="2026-11-09")])
        assert last_bar_date(conn, "sh.600000") == "2026-11-09"


class TestUpsertStocks:
    def test_insert_and_filter_non_stock(self, conn):
        rows = [
            dict(code="sh.600000", code_name="浦发银行", ipoDate="1999-11-10",
                 outDate="", type="1", status="1"),
            dict(code="sh.000001", code_name="上证指数", ipoDate="", outDate="",
                 type="2", status="1"),  # 指数非股票
        ]
        n = upsert_stocks(conn, rows)
        assert n == 1
        r = conn.execute("SELECT * FROM stocks").fetchone()
        assert r["code"] == "sh.600000"
        assert r["name"] == "浦发银行"
        assert r["code_num"] == "600000"

    def test_update_existing(self, conn):
        row = dict(code="sh.600000", code_name="浦发银行", ipoDate="1999-11-10",
                   outDate="", type="1", status="1")
        upsert_stocks(conn, [row])
        row2 = dict(row, code_name="浦发银行A", status="0")
        upsert_stocks(conn, [row2])
        r = conn.execute("SELECT name,status FROM stocks").fetchone()
        assert r["name"] == "浦发银行A"
        assert r["status"] == "0"
        assert conn.execute("SELECT COUNT(*) n FROM stocks").fetchone()["n"] == 1


class TestIndexBars:
    def test_upsert_index(self, conn):
        bar = dict(code="sh.000001", date="2026-11-09", open=3000, high=3050,
                   low=2990, close=3040, preclose=3000, volume=1e8,
                   amount=1e11, pct_chg=1.33)
        n = upsert_index_bars(conn, [bar])
        assert n == 1
        assert conn.execute("SELECT close FROM index_bars").fetchone()["close"] == 3040