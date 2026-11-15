"""初筛编排集成测试：种子数据库 -> run_prescreen 端到端。"""
import sqlite3

import pytest

from backend.db import SCHEMA
from backend.screening.pipeline import run_prescreen
from tests.test_screening import make_bars


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    yield c
    c.close()


def seed(conn, code, name, bars, industry="", status="1"):
    conn.execute(
        "INSERT INTO stocks(code,code_num,name,industry,type,status,updated_at) "
        "VALUES (?,?,?,?, '1',?, 'now')",
        (code, code.split(".")[-1], name, industry, status))
    conn.executemany(
        "INSERT INTO daily_bars(code,date,open,high,low,close,preclose,volume,"
        "amount,turn,trade_status,pct_chg,pe_ttm,pb_mrq,is_st) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(b["code"], b["date"], b["open"], b["high"], b["low"], b["close"],
          b["preclose"], b["volume"], b["amount"], b["turn"], b["trade_status"],
          b["pct_chg"], b["pe_ttm"], b["pb_mrq"], b["is_st"]) for b in bars])
    conn.commit()


def seed_index(conn, bars):
    conn.executemany(
        "INSERT INTO index_bars(code,date,open,high,low,close,preclose,volume,amount,pct_chg) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        [(b["code"], b["date"], b["open"], b["high"], b["low"], b["close"],
          b["preclose"], b["volume"], b["amount"], b["pct_chg"]) for b in bars])
    conn.commit()


class TestPrescreenPipeline:
    def test_filters_and_ranks(self, conn):
        strong = make_bars(daily_ret=0.02, amount=2e8, code="sh.600000")
        st = make_bars(daily_ret=0.02, amount=2e8, code="sz.000001", is_st=1)
        illiquid = make_bars(daily_ret=0.02, amount=1e6, code="sz.300750")
        seed(conn, "sh.600000", "强势股", strong, industry="银行")
        seed(conn, "sz.000001", "ST股", st, industry="银行")
        seed(conn, "sz.300750", "低流动性", illiquid, industry="电池")
        idx = make_bars(daily_ret=0.005, code="sh.000300")
        seed_index(conn, idx)
        expected = strong[-1]["date"]
        res = run_prescreen(conn, expected, prescreen_count=30, index_code="sh.000300")
        codes = [c["code"] for c in res["candidates"]]
        assert "sh.600000" in codes
        assert "sz.000001" not in codes  # ST 排除
        assert "sz.300750" not in codes  # 流动性排除
        assert res["rule_version"]
        assert res["market_env"]["regime"] in ("strong", "neutral", "weak")
        assert res["run_date"] == expected

    def test_empty_universe(self, conn):
        idx = make_bars(daily_ret=0.0, code="sh.000300")
        seed_index(conn, idx)
        res = run_prescreen(conn, idx[-1]["date"], index_code="sh.000300")
        assert res["candidates"] == []

    def test_deterministic_same_input(self, conn):
        for i in range(5):
            code = f"sh.60000{i}"
            seed(conn, code, f"股{i}", make_bars(daily_ret=0.01 + i * 0.002, code=code),
                 industry="银行")
        seed_index(conn, make_bars(daily_ret=0.005, code="sh.000300"))
        expected = make_bars()[-1]["date"]
        a = run_prescreen(conn, expected, index_code="sh.000300")
        b = run_prescreen(conn, expected, index_code="sh.000300")
        assert [c["code"] for c in a["candidates"]] == [c["code"] for c in b["candidates"]]
        assert [c["score"] for c in a["candidates"]] == [c["score"] for c in b["candidates"]]

def test_historical_screen_ignores_future_stock_and_index_bars(conn):
    from backend.screening.pipeline import _load_recent_bars
    earlier = "2026-11-09"
    later = "2026-11-10"
    conn.execute(
        "INSERT INTO daily_bars(code,date,open,high,low,close,preclose,volume,"
        "amount,trade_status,pct_chg,is_st) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        ("sh.600000", earlier, 10, 11, 9, 10, 10, 1000, 100000, 1, 0, 0))
    conn.execute(
        "INSERT INTO daily_bars(code,date,open,high,low,close,preclose,volume,"
        "amount,trade_status,pct_chg,is_st) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        ("sh.600000", later, 15, 16, 14, 15, 10, 1000, 100000, 1, 50, 0))
    rows = _load_recent_bars(conn, earlier, earlier)
    assert [b["date"] for b in rows["sh.600000"]] == [earlier]
