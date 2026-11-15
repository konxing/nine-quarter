"""AI 持仓判断记录与后续追踪测试（判断落库 + 第1/3/5日对错验证）。"""
import sqlite3

import pytest

from backend.db import SCHEMA
from backend.review.review_pipeline import run_review
from backend.review.tracker import update_position_outcomes
from backend.simulation.account import ensure_account, record_buy
from backend.simulation.rules import trade_costs


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    ensure_account(c, 100000)
    c.executemany("INSERT INTO trade_calendar VALUES (?,?)",
                  [("2026-11-05", 1), ("2026-11-06", 1), ("2026-11-07", 0),
                   ("2026-11-08", 0), ("2026-11-09", 1), ("2026-11-10", 1)])
    c.execute("INSERT INTO stocks(code,code_num,name,industry,type,status,updated_at) "
              "VALUES ('sh.600000','600000','浦发','银行','1','1','now')")
    record_buy(c, "sh.600000", "2026-11-06", 1000, 10.0, trade_costs(10000, "buy"))
    c.execute("INSERT INTO daily_bars(code,date,close,trade_status) "
              "VALUES ('sh.600000','2026-11-09',11.0,1)")
    c.execute("INSERT INTO daily_bars(code,date,close,trade_status) "
              "VALUES ('sh.600000','2026-11-10',12.0,1)")
    c.execute("INSERT INTO index_bars(code,date,close) VALUES ('sh.000300','2026-11-09',4000)")
    c.execute("INSERT INTO index_bars(code,date,close) VALUES ('sh.000300','2026-11-10',4040)")
    c.commit()
    yield c
    c.close()


class _Stub:
    def __init__(self, output):
        self.output = output

    def chat_json(self, system, user, retries=1):
        return self.output


_REVIEW = {
    "summary": "复盘", "correct_judgments": [], "mistakes": [], "uncertain": [],
    "improvements": [],
    "position_advice": [
        {"code": "sh.600000", "action": "hold", "reason": "趋势仍在"},
    ],
}


class TestPositionDecisionRecord:
    def test_advice_saved_structured_including_hold(self, conn, tmp_path):
        run_review(conn, _Stub(_REVIEW), "2026-11-09", "2026-11-06", tmp_path)
        rows = conn.execute("SELECT * FROM position_decisions").fetchall()
        assert len(rows) == 1
        r = rows[0]
        assert r["code"] == "sh.600000"
        assert r["action"] == "hold"
        assert r["decision_date"] == "2026-11-09"
        assert r["ref_price"] == 11.0
        assert r["reason"] == "趋势仍在"
        # hold 不产生订单
        assert conn.execute("SELECT COUNT(*) n FROM orders").fetchone()["n"] == 0

    def test_sell_advice_both_records_and_order(self, conn, tmp_path):
        review = dict(_REVIEW, position_advice=[
            {"code": "sh.600000", "action": "sell", "reason": "止盈"}])
        run_review(conn, _Stub(review), "2026-11-09", "2026-11-06", tmp_path)
        assert conn.execute("SELECT COUNT(*) n FROM position_decisions").fetchone()["n"] == 1
        o = conn.execute("SELECT * FROM orders WHERE side='sell'").fetchone()
        assert o is not None

    def test_idempotent_no_duplicate(self, conn, tmp_path):
        run_review(conn, _Stub(_REVIEW), "2026-11-09", "2026-11-06", tmp_path)
        run_review(conn, _Stub(_REVIEW), "2026-11-09", "2026-11-06", tmp_path)
        assert conn.execute("SELECT COUNT(*) n FROM position_decisions").fetchone()["n"] == 1


class TestPositionOutcomes:
    def _seed_decision(self, conn):
        conn.execute("INSERT INTO position_decisions(decision_date,code,name,action,"
                     "reason,ref_price,created_at) "
                     "VALUES ('2026-11-09','sh.600000','浦发','hold','趋势仍在',11.0,'now')")
        conn.commit()
        return conn.execute("SELECT id FROM position_decisions").fetchone()["id"]

    def test_checkpoint1_return(self, conn):
        did = self._seed_decision(conn)
        n = update_position_outcomes(conn, "2026-11-10")
        assert n == 1
        row = conn.execute("SELECT * FROM position_decision_outcomes").fetchone()
        assert row["decision_id"] == did
        assert row["checkpoint"] == 1
        # 11.0 -> 12.0 上涨 9.09%；hold 判断正确性由复盘解读
        assert row["ret_pct"] == pytest.approx(9.0909, abs=0.01)
        assert row["index_ret_pct"] == pytest.approx(1.0, abs=0.01)

    def test_no_duplicate(self, conn):
        self._seed_decision(conn)
        update_position_outcomes(conn, "2026-11-10")
        assert update_position_outcomes(conn, "2026-11-10") == 0

    def test_quant_includes_position_decisions(self, conn, tmp_path):
        did = self._seed_decision(conn)
        from backend.review.review_pipeline import build_quant_summary
        update_position_outcomes(conn, "2026-11-10")
        q = build_quant_summary(conn, "2026-11-09", "2026-11-10")
        pds = q["position_decisions"]
        assert len(pds) == 1
        assert pds[0]["action"] == "hold"
        assert pds[0]["outcomes"][0]["ret_pct"] == pytest.approx(9.0909, abs=0.01)

    def test_missed_checkpoint_backfilled_with_actual_day(self, conn):
        """持仓判断的第3日检查点漏跑时，后续复盘应补记第3日真实表现。"""
        conn.executemany("INSERT INTO trade_calendar VALUES (?,?)",
                         [("2026-11-11", 1), ("2026-11-12", 1), ("2026-11-13", 1)])
        conn.execute("INSERT INTO daily_bars(code,date,close,trade_status) "
                     "VALUES ('sh.600000','2026-11-11',12.5,1)")
        conn.execute("INSERT INTO daily_bars(code,date,close,trade_status) "
                     "VALUES ('sh.600000','2026-11-12',13.0,1)")
        conn.execute("INSERT INTO daily_bars(code,date,close,trade_status) "
                     "VALUES ('sh.600000','2026-11-13',13.2,1)")
        conn.execute("INSERT INTO index_bars(code,date,close) "
                     "VALUES ('sh.000300','2026-11-11',4050)")
        conn.execute("INSERT INTO index_bars(code,date,close) "
                     "VALUES ('sh.000300','2026-11-12',4060)")
        conn.execute("INSERT INTO index_bars(code,date,close) "
                     "VALUES ('sh.000300','2026-11-13',4070)")
        conn.commit()
        self._seed_decision(conn)
        assert update_position_outcomes(conn, "2026-11-10") == 1  # 第1日正常记录
        n = update_position_outcomes(conn, "2026-11-13")  # 跳过第3日，第5日才复盘
        assert n == 1
        row = conn.execute("SELECT * FROM position_decision_outcomes "
                           "WHERE checkpoint=3").fetchone()
        assert row["eval_date"] == "2026-11-12"  # 第3个交易日，不用第5日价格冒充
        assert row["ret_pct"] == pytest.approx((13.0 / 11.0 - 1) * 100, abs=0.01)