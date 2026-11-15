"""API 查询接口测试：临时数据库 + 仅挂载路由的测试 app（不启动调度器）。"""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import router
from backend.config import settings
from backend.db import connect, init_db


@pytest.fixture
def client(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    monkeypatch.setenv("DB_PATH", str(db))
    init_db(db)
    conn = connect(db)
    conn.executescript("""
        INSERT INTO account(id,initial_capital,cash,realized_pnl,updated_at)
            VALUES (1,100000,90000,0,'now');
        INSERT INTO account_daily(date,cash,market_value,total_assets,unrealized_pnl,
            realized_pnl,cum_return,peak_assets,max_drawdown)
            VALUES ('2026-11-09',90000,11000,101000,1000,0,0.01,101000,0);
        INSERT INTO stocks(code,code_num,name,industry,type,status,updated_at)
            VALUES ('sh.600000','600000','浦发银行','银行','1','1','now');
        INSERT INTO daily_bars(code,date,close,trade_status) VALUES ('sh.600000','2026-11-09',11.0,1);
        INSERT INTO position_lots(code,buy_date,shares,cost_amount) VALUES ('sh.600000','2026-11-06',1000,10000);
        INSERT INTO daily_decisions(run_date,model,ai_status,market_comment,created_at)
            VALUES ('2026-11-09','m','ok','震荡市','now');
        INSERT INTO screen_runs(run_date,rule_version,market_env,candidates,created_at)
            VALUES ('2026-11-09','v1','{"regime":"neutral"}','[{"code":"sh.600000"}]','now');
        INSERT INTO picks(id,run_date,code,name,action,ref_price,reason,created_at)
            VALUES (1,'2026-11-09','sh.600000','浦发银行','buy_candidate',10.0,'看好','now');
        INSERT INTO pick_outcomes(pick_id,checkpoint,eval_date,ret_pct,index_ret_pct,excess_vs_index)
            VALUES (1,1,'2026-11-10',10.0,2.0,8.0);
        INSERT INTO orders(id,decision_date,code,name,side,status,planned_shares,created_at,updated_at)
            VALUES (1,'2026-11-09','sh.600000','浦发银行','buy','pending',1000,'now','now');
        INSERT INTO trades(order_id,code,side,trade_date,price,shares,amount,created_at)
            VALUES (0,'sh.600000','buy','2026-11-06',10.0,1000,10000,'now');
        INSERT INTO reviews(review_date,target_date,ai_status,quant_json,report_md,created_at)
            VALUES ('2026-11-09','2026-11-06','ok','{}','# 复盘','now');
        INSERT INTO suggestions(review_date,category,content,status,created_at)
            VALUES ('2026-11-09','仓位','提高确定性仓位','proposed','now');
        INSERT INTO job_runs(job_name,biz_date,started_at,status) VALUES ('daily','2026-11-09','now','success');
    """)
    conn.commit()
    conn.close()
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as c:
        yield c


class TestAPI:
    def test_status(self, client):
        r = client.get("/api/status")
        assert r.status_code == 200
        d = r.json()
        assert d["counts"]["picks"] == 1
        assert d["latest_bar_date"] == "2026-11-09"
        assert d["active_stocks"] == 1
        assert "ai_configured" in d

    def test_picks_latest_with_outcomes(self, client):
        r = client.get("/api/picks")
        d = r.json()
        assert d["date"] == "2026-11-09"
        assert d["picks"][0]["code"] == "sh.600000"
        assert d["picks"][0]["outcomes"][0]["ret_pct"] == 10.0
        assert d["market_env"]["regime"] == "neutral"

    def test_account_positions(self, client):
        d = client.get("/api/account").json()
        assert d["account"]["cash"] == 90000
        p = d["positions"][0]
        assert p["shares"] == 1000
        assert p["latest_price"] == 11.0
        assert p["unrealized_pnl"] == 1000.0
        assert p["ai_advice"] is None

    def test_account_shows_latest_ai_advice_per_position(self, client):
        conn = connect(settings.db_path)
        conn.execute(
            "INSERT INTO position_decisions(decision_date,code,name,action,reason,"
            "ref_price,created_at) VALUES "
            "('2026-11-08','sh.600000','浦发银行','hold','趋势未破','10.9','now')")
        conn.execute(
            "INSERT INTO position_decisions(decision_date,code,name,action,reason,"
            "ref_price,created_at) VALUES "
            "('2026-11-09','sh.600000','浦发银行','reduce','涨幅过大','11.0','now')")
        conn.commit()
        conn.close()
        d = client.get("/api/account").json()
        adv = d["positions"][0]["ai_advice"]
        assert adv["action"] == "reduce"
        assert adv["decision_date"] == "2026-11-09"
        assert adv["reason"] == "涨幅过大"

    def test_orders(self, client):
        d = client.get("/api/orders").json()
        assert d["orders"][0]["status"] == "pending"
        d2 = client.get("/api/orders?status=filled").json()
        assert d2["orders"] == []

    def test_trades(self, client):
        assert client.get("/api/trades").json()["trades"][0]["price"] == 10.0

    def test_reviews(self, client):
        d = client.get("/api/reviews").json()
        assert d["review"]["ai_status"] == "ok"
        assert d["suggestions"][0]["content"] == "提高确定性仓位"
        assert d["position_decisions"] == []

    def test_history(self, client):
        d = client.get("/api/history").json()
        h = d["history"][0]
        assert h["run_date"] == "2026-11-09"
        assert h["pick_count"] == 1
        assert h["buy_count"] == 1
        assert h["account"]["total_assets"] == 101000

    def test_suggestions(self, client):
        assert client.get("/api/suggestions").json()["suggestions"][0]["status"] == "proposed"

    def test_picks_empty_date(self, client):
        d = client.get("/api/picks?date=1999-01-01").json()
        assert d["picks"] == []

    def test_picks_latest_uses_decision_date_even_without_picks(self, client):
        """最新一天 AI 失败、无选股时，不应回退展示旧一天的选股。"""
        conn = connect(settings.db_path)
        conn.execute("INSERT INTO daily_decisions(run_date,model,ai_status,market_comment,created_at) "
                     "VALUES ('2026-11-10','m','failed','AI 未配置','now')")
        conn.execute("INSERT INTO screen_runs(run_date,rule_version,market_env,candidates,created_at) "
                     "VALUES ('2026-11-10','v1','{\"regime\":\"weak\"}','[]','now')")
        conn.commit()
        conn.close()
        d = client.get("/api/picks").json()
        assert d["date"] == "2026-11-10"
        assert d["picks"] == []
        assert d["decision"]["ai_status"] == "failed"
        assert d["market_env"]["regime"] == "weak"

    def test_run_job_invalid(self, client):
        assert client.post("/api/jobs/run?job=bad").status_code == 400