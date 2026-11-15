"""FastAPI 只读查询接口 + 手动任务触发。数据全部来自 SQLite（真实数据）。"""
from __future__ import annotations

import json
import sqlite3
import threading

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .ai_analysis.client import AIError
from .ai_config import (
    apply_ai_overrides,
    load_ai_overrides,
    mask_key,
    probe_ai,
    save_ai_overrides,
)
from .config import settings
from .db import connect

router = APIRouter(prefix="/api")
_job_lock = threading.Lock()


def _conn() -> sqlite3.Connection:
    return connect(settings.db_path)


def _rows(conn, q, params=()) -> list[dict]:
    return [dict(r) for r in conn.execute(q, params)]


@router.get("/status")
def status():
    conn = _conn()
    try:
        counts = {}
        for t in ("stocks", "daily_bars", "picks", "orders", "trades", "reviews"):
            counts[t] = conn.execute(f"SELECT COUNT(*) n FROM {t}").fetchone()["n"]
        latest_bar = conn.execute("SELECT MAX(date) d FROM daily_bars").fetchone()["d"]
        active = conn.execute(
            "SELECT COUNT(*) n FROM stocks WHERE type='1' AND status='1'").fetchone()["n"]
        jobs = _rows(conn, "SELECT job_name,biz_date,status,started_at,finished_at,message "
                           "FROM job_runs ORDER BY started_at DESC LIMIT 10")
        acc = conn.execute("SELECT * FROM account WHERE id=1").fetchone()
        snap = conn.execute(
            "SELECT * FROM account_daily ORDER BY date DESC LIMIT 1").fetchone()
        ai_configured = bool(settings.ai_base_url and settings.ai_api_key and settings.ai_model)
        return {
            "counts": counts, "latest_bar_date": latest_bar, "active_stocks": active,
            "jobs": jobs, "ai_configured": ai_configured, "ai_model": settings.ai_model,
            "account": dict(acc) if acc else None,
            "latest_snapshot": dict(snap) if snap else None,
        }
    finally:
        conn.close()


@router.get("/picks")
def picks(date: str | None = None):
    conn = _conn()
    try:
        if date is None:
            r = conn.execute("SELECT MAX(run_date) d FROM daily_decisions").fetchone()
            date = r["d"]
        if date is None:
            return {"date": None, "picks": [], "decision": None, "market_env": None}
        ps = _rows(conn, "SELECT * FROM picks WHERE run_date=? ORDER BY "
                         "CASE action WHEN 'buy_candidate' THEN 0 ELSE 1 END, id", (date,))
        for p in ps:
            p["outcomes"] = _rows(
                conn, "SELECT checkpoint,eval_date,ret_pct,industry_ret_pct,"
                      "index_ret_pct,excess_vs_index FROM pick_outcomes "
                      "WHERE pick_id=? ORDER BY checkpoint", (p["id"],))
        dec = conn.execute("SELECT * FROM daily_decisions WHERE run_date=?", (date,)).fetchone()
        screen = conn.execute("SELECT market_env,candidates,rule_version FROM screen_runs "
                              "WHERE run_date=?", (date,)).fetchone()
        return {
            "date": date, "picks": ps,
            "decision": dict(dec) if dec else None,
            "market_env": json.loads(screen["market_env"]) if screen else None,
            "rule_version": screen["rule_version"] if screen else None,
            "candidate_count": len(json.loads(screen["candidates"])) if screen else 0,
        }
    finally:
        conn.close()


@router.get("/account")
def account():
    conn = _conn()
    try:
        acc = conn.execute("SELECT * FROM account WHERE id=1").fetchone()
        if acc is None:
            raise HTTPException(404, "账户未初始化")
        snaps = _rows(conn, "SELECT * FROM account_daily ORDER BY date DESC LIMIT 60")
        positions = []
        lots = _rows(conn, "SELECT code,SUM(shares) shares,SUM(cost_amount) cost "
                           "FROM position_lots GROUP BY code HAVING SUM(shares)>0")
        total_assets = snaps[0]["total_assets"] if snaps else acc["cash"]
        for lot in lots:
            code = lot["code"]
            px = conn.execute(
                "SELECT close,date FROM daily_bars WHERE code=? AND close IS NOT NULL "
                "ORDER BY date DESC LIMIT 1", (code,)).fetchone()
            name = conn.execute("SELECT name,industry FROM stocks WHERE code=?",
                                (code,)).fetchone()
            price = px["close"] if px else None
            mv = lot["shares"] * (price if price is not None else lot["cost"] / lot["shares"])
            advice = conn.execute(
                "SELECT decision_date,action,reason,ref_price FROM position_decisions "
                "WHERE code=? ORDER BY decision_date DESC, id DESC LIMIT 1",
                (code,)).fetchone()
            positions.append({
                "code": code, "name": name["name"] if name else "",
                "industry": name["industry"] if name else "",
                "shares": lot["shares"], "avg_cost": round(lot["cost"] / lot["shares"], 3),
                "latest_price": price, "price_date": px["date"] if px else None,
                "market_value": round(mv, 2),
                "unrealized_pnl": round(mv - lot["cost"], 2),
                "weight": round(mv / total_assets, 4) if total_assets else 0,
                "ai_advice": dict(advice) if advice else None,
            })
        return {"account": dict(acc), "snapshots": snaps, "positions": positions}
    finally:
        conn.close()


@router.get("/orders")
def orders(status: str | None = None, limit: int = 100):
    conn = _conn()
    try:
        q = "SELECT * FROM orders"
        params: list = []
        if status:
            q += " WHERE status=?"
            params.append(status)
        q += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        return {"orders": _rows(conn, q, params)}
    finally:
        conn.close()


@router.get("/trades")
def trades(limit: int = 100):
    conn = _conn()
    try:
        return {"trades": _rows(conn, "SELECT * FROM trades ORDER BY id DESC LIMIT ?",
                                (limit,))}
    finally:
        conn.close()


@router.get("/reviews")
def reviews(date: str | None = None):
    conn = _conn()
    try:
        if date is None:
            r = conn.execute("SELECT MAX(review_date) d FROM reviews").fetchone()
            date = r["d"]
        if date is None:
            return {"date": None, "review": None}
        r = conn.execute("SELECT * FROM reviews WHERE review_date=?", (date,)).fetchone()
        suggestions = _rows(conn, "SELECT * FROM suggestions WHERE review_date=? ORDER BY id",
                            (date,))
        pds = _rows(conn, "SELECT * FROM position_decisions WHERE decision_date=? ORDER BY id",
                    (date,))
        for pd in pds:
            pd["outcomes"] = _rows(
                conn, "SELECT checkpoint,eval_date,ret_pct,index_ret_pct "
                      "FROM position_decision_outcomes WHERE decision_id=? "
                      "ORDER BY checkpoint", (pd["id"],))
        return {"date": date, "review": dict(r) if r else None,
                "suggestions": suggestions, "position_decisions": pds}
    finally:
        conn.close()


@router.get("/history")
def history(limit: int = 60):
    conn = _conn()
    try:
        decisions = _rows(conn, "SELECT run_date,model,ai_status,market_comment,created_at "
                                "FROM daily_decisions ORDER BY run_date DESC LIMIT ?", (limit,))
        for d in decisions:
            d["pick_count"] = conn.execute(
                "SELECT COUNT(*) n FROM picks WHERE run_date=?", (d["run_date"],)).fetchone()["n"]
            d["buy_count"] = conn.execute(
                "SELECT COUNT(*) n FROM picks WHERE run_date=? AND action='buy_candidate'",
                (d["run_date"],)).fetchone()["n"]
            snap = conn.execute("SELECT total_assets,cum_return,max_drawdown FROM account_daily "
                                "WHERE date=?", (d["run_date"],)).fetchone()
            d["account"] = dict(snap) if snap else None
        return {"history": decisions}
    finally:
        conn.close()


@router.get("/suggestions")
def suggestions(limit: int = 100):
    conn = _conn()
    try:
        return {"suggestions": _rows(
            conn, "SELECT * FROM suggestions ORDER BY id DESC LIMIT ?", (limit,))}
    finally:
        conn.close()


class AISettingsIn(BaseModel):
    base_url: str = ""
    model: str = ""
    api_key: str = ""


def _ai_state() -> dict:
    configured = bool(settings.ai_base_url and settings.ai_api_key and settings.ai_model)
    conn = _conn()
    try:
        overrides = load_ai_overrides(conn)
    finally:
        conn.close()
    return {
        "base_url": settings.ai_base_url,
        "model": settings.ai_model,
        "key_configured": bool(settings.ai_api_key),
        "key_masked": mask_key(settings.ai_api_key),
        "source": "db" if overrides else ("env" if configured else "none"),
    }


def _validate_ai(body: AISettingsIn) -> tuple[str, str, str]:
    base = (body.base_url or "").strip().rstrip("/")
    model = (body.model or "").strip()
    if not base or not model:
        raise HTTPException(400, "接口地址与模型名必填")
    if not (base.startswith("http://") or base.startswith("https://")):
        raise HTTPException(400, "接口地址必须以 http:// 或 https:// 开头")
    key = (body.api_key or "").strip() or settings.ai_api_key
    if not key:
        raise HTTPException(400, "API Key 未配置")
    return base, model, key


@router.get("/settings/ai")
def get_ai_settings():
    return _ai_state()


@router.post("/settings/ai")
def save_ai_settings(body: AISettingsIn):
    """保存本机配置并立即覆盖当前进程的 AI 设置（无需重启）。"""
    base, model, key = _validate_ai(body)
    conn = _conn()
    try:
        save_ai_overrides(conn, base, model, (body.api_key or "").strip())
        apply_ai_overrides(settings, load_ai_overrides(conn))
    finally:
        conn.close()
    return _ai_state()


@router.post("/settings/ai/test")
def test_ai_settings(body: AISettingsIn):
    """用表单值（不落库）做一次最小请求，验证地址/模型/Key 是否可用。"""
    base, model, key = _validate_ai(body)
    try:
        reply = probe_ai(base, key, model, settings.ai_proxy or None)
    except AIError as e:
        return {"ok": False, "message": str(e)}
    return {"ok": True, "message": f"连接成功：{reply}"}


@router.post("/jobs/run")
def run_job(job: str = "daily"):
    """手动触发（运维/测试用）。后台线程执行，立即返回；状态见 /api/status。"""
    if job not in ("daily", "morning"):
        raise HTTPException(400, "job 须为 daily 或 morning")
    if not _job_lock.acquire(blocking=False):
        raise HTTPException(409, "已有任务在运行")

    def _work():
        from .pipeline import run_daily, run_morning
        conn = _conn()
        try:
            if job == "daily":
                run_daily(conn, settings)
            else:
                run_morning(conn, settings)
        except Exception:
            pass  # 已记录到 job_runs / 日志
        finally:
            conn.close()
            _job_lock.release()

    threading.Thread(target=_work, daemon=True).start()
    return {"status": "started", "job": job}