"""数据更新断点续传测试：中断后重跑跳过已完成股票（任务中断恢复）。"""
import sqlite3

import pytest

from backend.data_sources.update import update_bars
from backend.db import SCHEMA


class FakeBS:
    def __init__(self):
        self.calls = []

    def daily(self, code, start, end):
        self.calls.append(code)
        return [dict(code=code, date=end, open=10, high=10.5, low=9.8, close=10.2,
                     preclose=10, volume=1000, amount=10000, turn=0.5,
                     trade_status=1, pct_chg=1.0, pe_ttm=5, pb_mrq=0.6, is_st=0)]


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    c.executemany(
        "INSERT INTO stocks(code,code_num,name,type,status,updated_at) VALUES (?,?,?,'1','1','now')",
        [("sh.600000", "600000", "A"), ("sz.000001", "000001", "B")])
    c.commit()
    yield c
    c.close()


class TestResume:
    def test_skips_completed_stock(self, conn):
        # A 已有目标日 bar，B 没有
        conn.execute("INSERT INTO daily_bars(code,date,close,trade_status) "
                     "VALUES ('sh.600000','2026-11-09',10.0,1)")
        conn.commit()
        bs = FakeBS()
        stats = update_bars(conn, bs, "2026-06-01", "2026-11-09")
        assert bs.calls == ["sz.000001"]  # 只更新 B
        assert stats["skipped"] == 1
        assert stats["updated"] == 1

    def test_rerun_all_skipped(self, conn):
        bs = FakeBS()
        update_bars(conn, bs, "2026-06-01", "2026-11-09")
        bs.calls.clear()
        stats = update_bars(conn, bs, "2026-06-01", "2026-11-09")
        assert bs.calls == []  # 全部已完成，重跑不重复拉取
        assert stats["skipped"] == 2

    def test_empty_pool_raises(self, conn):
        conn.execute("DELETE FROM stocks")
        conn.commit()
        from backend.data_sources.baostock_source import DataSourceError
        with pytest.raises(DataSourceError):
            update_bars(conn, FakeBS(), "2026-06-01", "2026-11-09")