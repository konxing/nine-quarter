"""每日流水线编排测试：非交易日、数据未就绪、AI 不可用降级。

网络与初筛/新闻以桩替换（各自已单测），聚焦编排与失败隔离逻辑。
对应测试要求：AI 接口失效、无行情数据、非交易日、任务中断恢复。
"""
import sqlite3

import pytest

from backend import pipeline
from backend.config import Settings
from backend.db import SCHEMA
from backend.pipeline import DataNotReadyError, run_daily


class _DummyBS:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def trade_dates(self, s, e):
        return []


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    c.executemany("INSERT INTO trade_calendar VALUES (?,?)",
                  [("2026-11-06", 1), ("2026-11-07", 0), ("2026-11-08", 0),
                   ("2026-11-09", 1), ("2026-11-10", 1), ("2026-11-11", 1)])
    c.commit()
    yield c
    c.close()


@pytest.fixture
def cfg(tmp_path):
    s = Settings()
    s.reports_dir = tmp_path
    s.data_dir = tmp_path
    return s


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(pipeline, "BaoStockSource", _DummyBS)


class TestGates:
    def test_non_trading_day_skipped(self, conn, cfg):
        res = run_daily(conn, cfg, today="2026-11-08")
        assert res["status"] == "skipped"
        assert res["reason"] == "非交易日"

    def test_data_not_ready_stops(self, conn, cfg, monkeypatch):
        def _not_ready(conn, cfg, today):
            raise DataNotReadyError("行情未更新到当日")
        monkeypatch.setattr(pipeline, "_update_market_data", _not_ready)
        with pytest.raises(DataNotReadyError):
            run_daily(conn, cfg, today="2026-11-10")
        job = conn.execute("SELECT status FROM job_runs WHERE job_name='daily'").fetchone()
        assert job["status"] == "data_not_ready"
        # 停止后不得产生选股
        assert conn.execute("SELECT COUNT(*) n FROM picks").fetchone()["n"] == 0

    def test_idempotent_after_success(self, conn, cfg, monkeypatch):
        conn.execute("INSERT INTO job_runs(job_name,biz_date,started_at,status) "
                     "VALUES ('daily','2026-11-10','now','success')")
        conn.commit()
        called = {"n": 0}
        def _upd(conn, cfg, today):
            called["n"] += 1
            return today
        monkeypatch.setattr(pipeline, "_update_market_data", _upd)
        res = run_daily(conn, cfg, today="2026-11-10")
        assert res["status"] == "skipped"
        assert called["n"] == 0  # 已完成不再重复更新


    def test_rerun_after_ai_failed_when_ai_now_configured(self, conn, cfg, monkeypatch):
        """当日已成功跑完但 AI 失败；AI 配置好后重试应补做 AI 选股。"""
        conn.execute("INSERT INTO job_runs(job_name,biz_date,started_at,status) "
                     "VALUES ('daily','2026-11-10','now','success')")
        conn.execute("INSERT INTO daily_decisions(run_date,model,ai_status,created_at) "
                     "VALUES ('2026-11-10','','failed','now')")
        conn.commit()

        calls = {"n": 0}

        def _upd(c, cfg, today):
            calls["n"] += 1
            return today

        class _AI:
            def chat_json(self, system, user, retries=1):
                return {"picks": [], "summary": "", "correct_judgments": [],
                        "mistakes": [], "uncertain": [], "improvements": [],
                        "position_advice": []}

        monkeypatch.setattr(pipeline, "_update_market_data", _upd)
        monkeypatch.setattr(pipeline, "make_client", lambda cfg: _AI())
        monkeypatch.setattr(pipeline, "run_prescreen", lambda *a, **k: {
            "run_date": "2026-11-10", "rule_version": "v1",
            "market_env": {"regime": "neutral"}, "candidates": [],
            "stats": {"passed": 0}})
        monkeypatch.setattr(pipeline, "collect_news", lambda *a, **k: ({}, []))
        res = run_daily(conn, cfg, today="2026-11-10")
        assert res["status"] == "success"
        assert res["ai_status"] == "ok"
        assert calls["n"] == 1
        dec = conn.execute("SELECT ai_status FROM daily_decisions").fetchone()
        assert dec["ai_status"] == "ok"

    def test_no_rerun_when_ai_still_unconfigured(self, conn, cfg, monkeypatch):
        conn.execute("INSERT INTO job_runs(job_name,biz_date,started_at,status) "
                     "VALUES ('daily','2026-11-10','now','success')")
        conn.execute("INSERT INTO daily_decisions(run_date,model,ai_status,created_at) "
                     "VALUES ('2026-11-10','','failed','now')")
        conn.commit()
        called = {"n": 0}
        def _upd(c, cfg, today):
            called["n"] += 1
            return today
        monkeypatch.setattr(pipeline, "_update_market_data", _upd)
        monkeypatch.setattr(pipeline, "make_client", lambda cfg: None)
        res = run_daily(conn, cfg, today="2026-11-10")
        assert res["status"] == "skipped"
        assert called["n"] == 0


class TestMorning:
    def test_fills_pending_at_realtime_snapshot(self, conn, cfg, monkeypatch):
        """上午任务用实时快照价撮合昨日订单（价格来源 realtime_snapshot）。"""
        from backend.data_sources import akshare_source
        from backend.pipeline import run_morning
        from backend.simulation.broker import create_order

        oid = create_order(conn, "2026-11-09", "sh.600000", "浦发", "buy",
                           0.1, 1000, 10.0, "测试")
        monkeypatch.setattr(
            akshare_source, "fetch_realtime",
            lambda code: {"latest": 10.2, "open": 10.0, "preclose": 10.0,
                          "high": 10.3, "low": 9.9})
        res = run_morning(conn, cfg, today="2026-11-10")
        assert res["status"] == "success"
        assert res["fills"] == 1
        o = conn.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
        assert o["status"] == "filled"
        assert o["filled_date"] == "2026-11-10"
        assert o["filled_price"] == 10.2
        t = conn.execute("SELECT * FROM trades WHERE order_id=?", (oid,)).fetchone()
        assert t["price_source"] == "realtime_snapshot"
        job = conn.execute("SELECT * FROM job_runs WHERE job_name='morning' AND biz_date=?",
                           ("2026-11-10",)).fetchone()
        assert job["status"] == "success"
        assert job["finished_at"]


class TestEndToEndSimulation:
    """两日全流程：AI 选出买入 → 生成次日订单 → 次日开盘价成交 → 估值与复盘。"""

    def _screen(self, conn, target, **k):
        return {
            "run_date": target, "rule_version": "v1",
            "market_env": {"regime": "neutral", "above_ma20": True, "ret_5d": 0.01},
            "candidates": [{
                "code": "sh.600000", "name": "浦发", "industry": "银行",
                "score": 1.0, "industry_rs": 0.0,
                "indicators": {"close": 10.0, "last_date": target,
                               "ret_5d": 0.0, "ret_20d": 0.05, "vol_ratio": 1.2,
                               "above_ma20": True, "avg_amount_20d": 1e9,
                               "volatility_20d": 0.02, "pe_ttm": 6.0, "pb_mrq": 0.6},
            }],
            "stats": {"universe": 1, "passed": 1, "selected": 1},
        }

    def test_repeat_pick_respects_existing_position_limit(self, conn, cfg, monkeypatch):
        """已持有 15% 市值时，AI 再按 20% 推荐只能补 5%，不得超过单只 20% 上限。"""
        from backend.ai_analysis.prompts import PICK_SYSTEM, REVIEW_SYSTEM

        conn.execute("INSERT INTO account(id,initial_capital,cash,realized_pnl,updated_at) "
                     "VALUES (1,100000,85000,0,'now')")
        conn.execute("INSERT INTO position_lots(code,buy_date,shares,cost_amount) "
                     "VALUES ('sh.600000','2026-11-06',1500,15000)")
        conn.execute("INSERT INTO daily_bars(code,date,close,trade_status) "
                     "VALUES ('sh.600000','2026-11-10',10.0,1)")
        conn.commit()

        pick = {
            "code": "sh.600000", "action": "buy_candidate", "potential_level": "medium",
            "suggested_weight": 0.2, "reason": "继续看好", "bull_logic": "x",
            "bear_risks": "y", "horizon": "1-5日", "buy_trigger": "z",
            "invalid_condition": "w", "edge_vs_peers": "v",
        }

        class _Client:
            def chat_json(self, system, user, retries=1):
                if system == PICK_SYSTEM:
                    return {"picks": [pick], "market_comment": "中性"}
                return {"summary": "完成", "correct_judgments": [], "mistakes": [],
                        "uncertain": [], "improvements": [], "position_advice": []}

        monkeypatch.setattr(pipeline, "_update_market_data", lambda c, cfg, t: t)
        monkeypatch.setattr(pipeline, "make_client", lambda cfg: _Client())
        monkeypatch.setattr(pipeline, "run_prescreen", self._screen)
        monkeypatch.setattr(pipeline, "collect_news", lambda *a, **k: ({}, []))
        run_daily(conn, cfg, today="2026-11-10")
        o = conn.execute("SELECT * FROM orders WHERE side='buy'").fetchone()
        assert o["planned_shares"] == 500  # 剩余 5000 元 / 10 元

    def test_pick_then_fill_next_day(self, conn, cfg, monkeypatch):
        from backend.ai_analysis.prompts import PICK_SYSTEM, REVIEW_SYSTEM

        pick = {
            "code": "sh.600000", "action": "buy_candidate", "potential_level": "medium",
            "suggested_weight": 0.1, "reason": "量价齐升", "bull_logic": "银行修复",
            "bear_risks": "市场走弱", "horizon": "1-5个交易日",
            "buy_trigger": "次日不高开超3%", "invalid_condition": "跌破10日线",
            "edge_vs_peers": "强于同业",
        }

        class _Client:
            def chat_json(self, system, user, retries=1):
                if system == PICK_SYSTEM:
                    return {"picks": [pick], "market_comment": "中性"}
                return {"summary": "完成", "correct_judgments": [], "mistakes": [],
                        "uncertain": [], "improvements": [], "position_advice": []}

        monkeypatch.setattr(pipeline, "_update_market_data", lambda c, cfg, t: t)
        monkeypatch.setattr(pipeline, "make_client", lambda cfg: _Client())
        monkeypatch.setattr(pipeline, "run_prescreen", self._screen)
        monkeypatch.setattr(pipeline, "collect_news", lambda *a, **k: ({}, []))

        r1 = run_daily(conn, cfg, today="2026-11-10")
        assert r1["ai_status"] == "ok" and r1["picks"] == 1 and r1["orders"] == 1
        order = conn.execute("SELECT * FROM orders WHERE side='buy'").fetchone()
        assert order["status"] == "pending" and order["decision_date"] == "2026-11-10"

        # 次日日线：开盘 10.2（涨停价 11.0 以内，非一字板）
        conn.execute(
            "INSERT INTO daily_bars(code,date,open,high,low,close,preclose,volume,trade_status) "
            "VALUES ('sh.600000','2026-11-11',10.2,10.4,10.1,10.3,10.0,1000000,1)")
        conn.commit()

        r2 = run_daily(conn, cfg, today="2026-11-11")
        assert r2["fills"] == 1
        o = conn.execute("SELECT * FROM orders WHERE id=?", (order["id"],)).fetchone()
        assert o["status"] == "filled"
        assert o["filled_date"] == "2026-11-11"
        assert o["filled_price"] == 10.2
        t = conn.execute("SELECT * FROM trades WHERE order_id=?", (order["id"],)).fetchone()
        assert t["trade_date"] == "2026-11-11" and t["shares"] == 1000

        snap = conn.execute("SELECT * FROM account_daily WHERE date='2026-11-11'").fetchone()
        assert snap["total_assets"] > 100000 - 10200
        pos = conn.execute("SELECT SUM(shares) n FROM position_lots").fetchone()
        assert pos["n"] == 1000
        # 复盘与持仓判断不因 AI 再次调用而重复
        assert conn.execute("SELECT COUNT(*) n FROM reviews WHERE review_date='2026-11-11'").fetchone()["n"] == 1


class TestAIDegradation:
    def test_ai_unconfigured_no_picks_no_orders(self, conn, cfg, monkeypatch, tmp_path):
        monkeypatch.setattr(pipeline, "_update_market_data", lambda c, cfg, t: t)
        monkeypatch.setattr(pipeline, "make_client", lambda cfg: None)
        monkeypatch.setattr(pipeline, "run_prescreen", lambda *a, **k: {
            "run_date": "2026-11-10", "rule_version": "v1",
            "market_env": {"regime": "neutral"}, "candidates": [],
            "stats": {"universe": 0, "passed": 0, "selected": 0}})
        monkeypatch.setattr(pipeline, "collect_news", lambda *a, **k: ({}, []))
        res = run_daily(conn, cfg, today="2026-11-10")
        assert res["status"] == "success"
        assert res["ai_status"] == "failed"
        assert res["picks"] == 0
        assert res["orders"] == 0
        dec = conn.execute("SELECT ai_status FROM daily_decisions").fetchone()
        assert dec["ai_status"] == "failed"
        assert conn.execute("SELECT COUNT(*) n FROM orders").fetchone()["n"] == 0
        assert (tmp_path / "daily-2026-11-10.md").exists()
        # 量化复盘仍生成（AI 不可用降级）
        assert conn.execute("SELECT COUNT(*) n FROM reviews").fetchone()["n"] == 1