"""决策追踪测试：推荐股第1/3/5交易日表现，相对行业/基准。

对应验收要求 8/9：次日复盘先前决策，保留决策历史与后续结果。
"""
import sqlite3

import pytest

from backend.db import SCHEMA
from backend.review.tracker import trading_day_count, update_outcomes


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    days = [("2026-11-05", 1), ("2026-11-06", 1), ("2026-11-07", 0),
            ("2026-11-08", 0), ("2026-11-09", 1), ("2026-11-10", 1),
            ("2026-11-11", 1), ("2026-11-12", 1), ("2026-11-13", 1)]
    c.executemany("INSERT INTO trade_calendar VALUES (?,?)", days)
    c.execute("INSERT INTO stocks(code,code_num,name,industry,type,status,updated_at) "
              "VALUES ('sh.600000','600000','浦发','银行','1','1','now')")
    c.execute("INSERT INTO daily_decisions(run_date,ai_status,created_at) "
              "VALUES ('2026-11-06','ok','now')")
    c.execute("INSERT INTO picks(run_date,code,name,action,ref_price,ref_price_time,created_at) "
              "VALUES ('2026-11-06','sh.600000','浦发','watch',10.0,'2026-11-06','now')")
    c.commit()
    yield c
    c.close()


def _bar(conn, code, date, close):
    conn.execute("INSERT OR REPLACE INTO daily_bars(code,date,close,trade_status) "
                 "VALUES (?,?,?,1)", (code, date, close))
    conn.commit()


def _idx(conn, date, close):
    conn.execute("INSERT OR REPLACE INTO index_bars(code,date,close) "
                 "VALUES ('sh.000300',?,?)", (date, close))
    conn.commit()


class TestTradingDayCount:
    def test_skips_weekend(self, conn):
        assert trading_day_count(conn, "2026-11-06", "2026-11-09") == 1
        assert trading_day_count(conn, "2026-11-06", "2026-11-11") == 3

    def test_same_day_zero(self, conn):
        assert trading_day_count(conn, "2026-11-06", "2026-11-06") == 0


class TestOutcomes:
    def test_checkpoint1_return(self, conn):
        _bar(conn, "sh.600000", "2026-11-06", 10.0)
        _bar(conn, "sh.600000", "2026-11-09", 11.0)
        _idx(conn, "2026-11-06", 100.0)
        _idx(conn, "2026-11-09", 102.0)
        n = update_outcomes(conn, "2026-11-09")
        assert n == 1
        row = conn.execute("SELECT * FROM pick_outcomes").fetchone()
        assert row["checkpoint"] == 1
        assert row["ret_pct"] == pytest.approx(10.0)
        assert row["index_ret_pct"] == pytest.approx(2.0)
        assert row["excess_vs_index"] == pytest.approx(8.0)
        assert row["industry_ret_pct"] == pytest.approx(10.0)  # 同业仅该股

    def test_no_duplicate_on_rerun(self, conn):
        _bar(conn, "sh.600000", "2026-11-09", 11.0)
        _idx(conn, "2026-11-06", 100.0)
        _idx(conn, "2026-11-09", 102.0)
        update_outcomes(conn, "2026-11-09")
        n = update_outcomes(conn, "2026-11-09")
        assert n == 0
        assert conn.execute("SELECT COUNT(*) n FROM pick_outcomes").fetchone()["n"] == 1

    def test_missing_eval_bar_skipped(self, conn):
        _idx(conn, "2026-11-06", 100.0)
        _idx(conn, "2026-11-09", 102.0)
        n = update_outcomes(conn, "2026-11-09")  # 个股无 11-09 bar
        assert n == 0

    def test_checkpoint3(self, conn):
        _bar(conn, "sh.600000", "2026-11-11", 12.0)
        _idx(conn, "2026-11-06", 100.0)
        _idx(conn, "2026-11-11", 105.0)
        n = update_outcomes(conn, "2026-11-11")
        assert n == 1
        row = conn.execute("SELECT * FROM pick_outcomes").fetchone()
        assert row["checkpoint"] == 3
        assert row["ret_pct"] == pytest.approx(20.0)

    def test_missed_checkpoint_backfilled_with_actual_day(self, conn):
        """复盘恰好在第3日漏跑时，第4日复盘仍应补记第3日表现（用第3日真实收盘价）。"""
        _bar(conn, "sh.600000", "2026-11-11", 12.0)   # 第3个交易日
        _bar(conn, "sh.600000", "2026-11-12", 12.5)   # 第4个交易日
        _idx(conn, "2026-11-06", 100.0)
        _idx(conn, "2026-11-11", 105.0)
        _idx(conn, "2026-11-12", 106.0)
        n = update_outcomes(conn, "2026-11-12")
        assert n == 1
        row = conn.execute("SELECT * FROM pick_outcomes").fetchone()
        assert row["checkpoint"] == 3
        assert row["eval_date"] == "2026-11-11"  # 不是用第4日价格冒充第3日
        assert row["ret_pct"] == pytest.approx(20.0)