"""复盘编排测试：量化摘要 + AI 复盘 + 建议保存 + 持仓建议转订单 + AI 失效降级。"""
import sqlite3

import pytest

from backend.ai_analysis.client import AIError
from backend.db import SCHEMA
from backend.review.review_pipeline import build_quant_summary, run_review
from backend.simulation.account import ensure_account, record_buy
from backend.simulation.rules import trade_costs


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    ensure_account(c, 100000)
    c.execute("INSERT INTO stocks(code,code_num,name,industry,type,status,updated_at) "
              "VALUES ('sh.600000','600000','浦发','银行','1','1','now')")
    c.execute("INSERT INTO daily_decisions(run_date,ai_status,created_at) "
              "VALUES ('2026-11-06','ok','now')")
    c.execute("INSERT INTO picks(run_date,code,name,action,ref_price,reason,created_at) "
              "VALUES ('2026-11-06','sh.600000','浦发','buy_candidate',10.0,'看好','now')")
    record_buy(c, "sh.600000", "2026-11-06", 1000, 10.0, trade_costs(10000, "buy"))
    c.execute("INSERT INTO daily_bars(code,date,close,trade_status) "
              "VALUES ('sh.600000','2026-11-09',11.0,1)")
    c.execute("INSERT INTO index_bars(code,date,close) VALUES ('sh.000300','2026-11-09',4000)")
    c.commit()
    yield c
    c.close()


class _Stub:
    def __init__(self, output):
        self.output = output

    def chat_json(self, system, user, retries=1):
        return self.output


class _Fail:
    def chat_json(self, system, user, retries=1):
        raise AIError("接口失效")


_REVIEW = {
    "summary": "昨日推荐上涨，判断正确",
    "correct_judgments": ["选中浦发上涨10%"],
    "mistakes": [{"type": "交易", "detail": "仓位偏低"}],
    "uncertain": [],
    "improvements": [{"category": "仓位", "content": "可适度提高确定性高的仓位"}],
    "position_advice": [{"code": "sh.600000", "action": "sell", "reason": "止盈"}],
}


class TestQuantSummary:
    def test_includes_picks_holdings(self, conn):
        q = build_quant_summary(conn, "2026-11-06", "2026-11-09")
        assert q["target_date"] == "2026-11-06"
        assert q["picks"][0]["code"] == "sh.600000"
        assert q["holdings"][0]["shares"] == 1000
        assert q["holdings"][0]["latest_price"] == 11.0
        assert "account" in q

    def test_pick_without_next_day_fill_is_not_bought(self, conn):
        """买入发生在决策日、不在（决策日, 评估日] 窗口：账户口径应为未买入。"""
        q = build_quant_summary(conn, "2026-11-06", "2026-11-09")
        assert q["picks"][0]["account_view"] == {"bought": False}

    def test_account_view_uses_real_fill_price_with_fees(self, conn):
        """账户可实现收益按次日真实成交价与费用计算，而非收盘价口径。"""
        conn.execute(
            "INSERT INTO trades(order_id,code,side,trade_date,price,shares,amount,"
            "commission,stamp_tax,transfer_fee,created_at) "
            "VALUES (0,'sh.600000','buy','2026-11-09',10.5,1000,10500,5,0,0.1,'now')")
        conn.commit()
        q = build_quant_summary(conn, "2026-11-06", "2026-11-09")
        av = q["picks"][0]["account_view"]
        assert av["bought"] is True
        assert av["fill_price"] == 10.5
        assert av["unit_cost"] == pytest.approx(10.5051, abs=1e-4)  # 含费用
        assert av["shares"] == 1000
        assert av["mark_price"] == 11.0
        assert av["account_ret_pct"] == pytest.approx((11 / 10.5051 - 1) * 100, abs=1e-3)


class TestRunReview:
    def test_ok_saves_review_suggestions_order(self, conn, tmp_path):
        res = run_review(conn, _Stub(_REVIEW), "2026-11-09", "2026-11-06", tmp_path)
        assert res["ai_status"] == "ok"
        r = conn.execute("SELECT * FROM reviews").fetchone()
        assert r["ai_status"] == "ok"
        assert r["target_date"] == "2026-11-06"
        assert conn.execute("SELECT COUNT(*) n FROM suggestions").fetchone()["n"] == 1
        o = conn.execute("SELECT * FROM orders WHERE side='sell'").fetchone()
        assert o["code"] == "sh.600000"
        assert o["decision_date"] == "2026-11-09"
        assert o["planned_shares"] == 1000
        assert (tmp_path / "2026-11-09.md").exists()

    def test_report_shows_account_basis_beside_close_basis(self, conn, tmp_path):
        """复盘报告应同时给收盘价口径与账户成交价口径，避免把账面涨幅当成可实现收益。"""
        conn.execute(
            "INSERT INTO trades(order_id,code,side,trade_date,price,shares,amount,"
            "commission,stamp_tax,transfer_fee,created_at) "
            "VALUES (0,'sh.600000','buy','2026-11-09',10.5,1000,10500,5,0,0.1,'now')")
        conn.commit()
        res = run_review(conn, _Stub(_REVIEW), "2026-11-09", "2026-11-06", tmp_path)
        assert "账户口径" in res["report_md"]
        assert "成交价" in res["report_md"]

    def test_ai_failed_degrades_gracefully(self, conn, tmp_path):
        res = run_review(conn, _Fail(), "2026-11-09", "2026-11-06", tmp_path)
        assert res["ai_status"] == "failed"
        r = conn.execute("SELECT * FROM reviews").fetchone()
        assert r["ai_status"] == "failed"
        assert conn.execute("SELECT COUNT(*) n FROM suggestions").fetchone()["n"] == 0
        assert conn.execute("SELECT COUNT(*) n FROM orders").fetchone()["n"] == 0
        assert (tmp_path / "2026-11-09.md").exists()  # 量化报告仍生成

    def test_advice_for_non_holding_ignored(self, conn, tmp_path):
        review = dict(_REVIEW, position_advice=[
            {"code": "sz.999999", "action": "sell", "reason": "x"}])
        run_review(conn, _Stub(review), "2026-11-09", "2026-11-06", tmp_path)
        assert conn.execute("SELECT COUNT(*) n FROM orders").fetchone()["n"] == 0

    def test_idempotent_review(self, conn, tmp_path):
        run_review(conn, _Stub(_REVIEW), "2026-11-09", "2026-11-06", tmp_path)
        run_review(conn, _Stub(_REVIEW), "2026-11-09", "2026-11-06", tmp_path)
        assert conn.execute("SELECT COUNT(*) n FROM reviews").fetchone()["n"] == 1

    def test_retry_after_ai_failure_saves_side_effects(self, conn, tmp_path):
        """当日 AI 先失败、重试成功时，建议/持仓判断仍应写入且不重复。"""
        run_review(conn, _Fail(), "2026-11-09", "2026-11-06", tmp_path)
        res = run_review(conn, _Stub(_REVIEW), "2026-11-09", "2026-11-06", tmp_path)
        assert res["ai_status"] == "ok"
        assert conn.execute("SELECT COUNT(*) n FROM suggestions").fetchone()["n"] == 1
        assert conn.execute("SELECT COUNT(*) n FROM position_decisions").fetchone()["n"] == 1
        assert conn.execute("SELECT COUNT(*) n FROM orders WHERE side='sell'").fetchone()["n"] == 1
        # 再次成功运行不应重复下单/重复建议
        run_review(conn, _Stub(_REVIEW), "2026-11-09", "2026-11-06", tmp_path)
        assert conn.execute("SELECT COUNT(*) n FROM suggestions").fetchone()["n"] == 1
        assert conn.execute("SELECT COUNT(*) n FROM orders WHERE side='sell'").fetchone()["n"] == 1