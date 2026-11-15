"""每日自动执行流程编排（盘后全流程 + 上午订单处理）。

顺序：交易日历门控 -> 行情更新与覆盖率校验 -> 次日订单撮合（开盘价）->
收盘估值 -> 初筛 -> 新闻 -> AI 选股 -> 生成次日模拟订单 -> 复盘昨日 -> 日报。

数据未就绪抛 DataNotReadyError（调度器稍后重试），绝不用旧行情冒充当日。
AI 失效降级：不产生新选股/订单，仍完成估值与量化复盘。
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import sqlite3
from zoneinfo import ZoneInfo

from .ai_analysis.client import AIClient, AIError
from .ai_analysis.stock_pick import build_payload, pick_stocks
from .config import Settings
from .data_sources.baostock_source import BaoStockSource, DataSourceError
from .data_sources.calendar import is_trading_day, prev_trading_day
from .data_sources.collector import active_stock_codes
from .data_sources.news_collect import collect_news
from .data_sources.update import (
    ensure_calendar,
    latest_available_date,
    refresh_stock_pool,
    update_bars,
    update_indices,
)
from .data_sources.validate import check_coverage
from .review.review_pipeline import run_review
from .screening.pipeline import run_prescreen
from .simulation.account import ensure_account, get_account, get_positions, mark_to_market
from .simulation.broker import create_order, process_pending_orders
from .simulation.planning import plan_buy

log = logging.getLogger("nine-quarter.pipeline")


class DataNotReadyError(RuntimeError):
    """当日行情尚未发布完整，停止并等待重试。"""


def beijing_today() -> str:
    return dt.datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()


def make_client(cfg: Settings) -> AIClient | None:
    if not (cfg.ai_base_url and cfg.ai_api_key and cfg.ai_model):
        return None
    return AIClient(cfg.ai_base_url, cfg.ai_api_key, cfg.ai_model,
                    temperature=cfg.ai_temperature, timeout=cfg.ai_timeout,
                    max_tokens=cfg.ai_max_tokens, proxy=cfg.ai_proxy or None)


def _cost_kwargs(cfg: Settings) -> dict:
    return dict(commission_rate=cfg.commission_rate, min_commission=cfg.min_commission,
                stamp_tax_rate=cfg.stamp_tax_rate, transfer_fee_rate=cfg.transfer_fee_rate)


def _job_start(conn, name, biz_date) -> None:
    conn.execute(
        "INSERT INTO job_runs(job_name,biz_date,started_at,status) "
        "VALUES (?,?,datetime('now'),'running') "
        "ON CONFLICT(job_name,biz_date) DO UPDATE SET started_at=excluded.started_at, "
        "status='running', finished_at='', message=''", (name, biz_date))
    conn.commit()


def _job_end(conn, name, biz_date, status, message="") -> None:
    conn.execute(
        "UPDATE job_runs SET status=?, finished_at=datetime('now'), message=? "
        "WHERE job_name=? AND biz_date=?", (status, message[:1000], name, biz_date))
    conn.commit()


def _bars_on(conn, date, codes=None) -> dict[str, dict]:
    q = ("SELECT code,open,high,low,close,preclose,volume,trade_status,is_st "
         "FROM daily_bars WHERE date=?")
    params = [date]
    if codes is not None:
        if not codes:
            return {}
        q += " AND code IN (%s)" % ",".join("?" * len(codes))
        params += list(codes)
    return {r["code"]: dict(r) for r in conn.execute(q, params)}


def _save_screen(conn, screen: dict) -> None:
    conn.execute(
        "INSERT INTO screen_runs(run_date,rule_version,market_env,candidates,created_at) "
        "VALUES (?,?,?,?,datetime('now')) "
        "ON CONFLICT(run_date) DO UPDATE SET rule_version=excluded.rule_version, "
        "market_env=excluded.market_env, candidates=excluded.candidates",
        (screen["run_date"], screen["rule_version"],
         json.dumps(screen["market_env"], ensure_ascii=False),
         json.dumps(screen["candidates"], ensure_ascii=False)))
    conn.commit()


def _save_picks(conn, run_date, result, model, ai_status) -> None:
    conn.execute(
        "INSERT INTO daily_decisions(run_date,model,ai_status,ai_raw,market_comment,created_at) "
        "VALUES (?,?,?,?,?,datetime('now')) "
        "ON CONFLICT(run_date) DO UPDATE SET model=excluded.model, ai_status=excluded.ai_status, "
        "ai_raw=excluded.ai_raw, market_comment=excluded.market_comment",
        (run_date, model, ai_status,
         json.dumps(result.get("raw", {}), ensure_ascii=False),
         result.get("market_comment", "")))
    for p in result.get("picks", []):
        conn.execute(
            "INSERT INTO picks(run_date,code,name,action,ref_price,ref_price_time,reason,"
            "bull_logic,bear_risks,horizon,buy_trigger,invalid_condition,edge_vs_peers,"
            "potential_level,suggested_weight,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now')) "
            "ON CONFLICT(run_date,code) DO UPDATE SET action=excluded.action",
            (run_date, p["code"], p["name"], p["action"], p["ref_price"],
             p["ref_price_time"], p["reason"], p["bull_logic"], p["bear_risks"],
             p["horizon"], p["buy_trigger"], p["invalid_condition"], p["edge_vs_peers"],
             p["potential_level"], p["suggested_weight"]))
    conn.commit()


def _update_market_data(conn: sqlite3.Connection, cfg: Settings, today: str) -> str:
    """更新行情到当日并校验覆盖率。未就绪抛 DataNotReadyError。返回目标日期。"""
    with BaoStockSource() as bs:
        refresh_stock_pool(conn, bs)
        target = latest_available_date(bs, today)
        if target != today:
            raise DataNotReadyError(f"行情未更新到当日（最新 {target}，期望 {today}）")
        start = (dt.date.fromisoformat(today)
                 - dt.timedelta(days=cfg.backfill_calendar_days)).isoformat()
        update_bars(conn, bs, start, target)
        update_indices(conn, bs, start, target, cfg.index_codes)
    ok, _cov, detail = check_coverage(conn, target, cfg.min_data_coverage)
    if not ok:
        raise DataNotReadyError(detail)
    return target


def run_daily(conn: sqlite3.Connection, cfg: Settings, today: str | None = None,
              client: AIClient | None = None) -> dict:
    today = today or beijing_today()
    cfg.ensure_dirs()
    ensure_account(conn, cfg.initial_capital)

    with BaoStockSource() as bs:
        ensure_calendar(conn, bs,
                        (dt.date.fromisoformat(today) - dt.timedelta(days=10)).isoformat(),
                        (dt.date.fromisoformat(today) + dt.timedelta(days=30)).isoformat())
    if not is_trading_day(conn, today):
        log.info("%s 非交易日，跳过", today)
        return {"status": "skipped", "reason": "非交易日", "date": today}

    done = conn.execute(
        "SELECT status FROM job_runs WHERE job_name='daily' AND biz_date=?",
        (today,)).fetchone()
    if done and done["status"] == "success":
        # 当日流程已完成不重跑；但若此前仅因 AI 不可用而留下空结果，
        # 且现在 AI 已配置，则允许重试一次 AI 选股，避免整天缺失主观结论。
        prev = conn.execute(
            "SELECT ai_status FROM daily_decisions WHERE run_date=?",
            (today,)).fetchone()
        ai_failed = prev is not None and prev["ai_status"] != "ok"
        if not (ai_failed and make_client(cfg) is not None):
            return {"status": "skipped", "reason": "当日已完成", "date": today}

    _job_start(conn, "daily", today)
    client = client if client is not None else make_client(cfg)
    try:
        # 1 行情更新与覆盖率校验
        target = _update_market_data(conn, cfg, today)

        # 2 撮合昨日订单（今日开盘价，无未来价格）
        pending_codes = [r["code"] for r in conn.execute(
            "SELECT DISTINCT code FROM orders WHERE status='pending'")]
        bars_today = _bars_on(conn, target, pending_codes)
        fill_events = process_pending_orders(
            conn, target, bars_today, cfg.order_expire_days, _cost_kwargs(cfg))

        # 3 收盘估值
        held = list(get_positions(conn).keys())
        prices = {c: b["close"] for c, b in _bars_on(conn, target, held).items()
                  if b.get("close") is not None}
        snap = mark_to_market(conn, target, prices)

        # 4 初筛
        screen = run_prescreen(
            conn, target, prescreen_count=cfg.prescreen_count,
            min_history=cfg.min_history_bars, min_avg_amount=cfg.min_avg_amount_20d,
            min_price=cfg.min_price, exclude_st=cfg.exclude_st)
        _save_screen(conn, screen)
        cand_codes = [c["code"] for c in screen["candidates"]]

        # 5 新闻
        news_by_code, market_news = collect_news(conn, target, cand_codes, client)

        # 6 AI 选股 + 次日订单
        ai_status = "ok"
        result = {"picks": [], "market_comment": "", "raw": {}}
        if client is None:
            ai_status = "failed"
            result["market_comment"] = "AI 未配置（需 AI_MODEL），当日不产生选股"
        else:
            try:
                holdings_summary = [
                    {"code": c, "weight": round(p["cost_amount"] / snap["total_assets"], 4)}
                    for c, p in get_positions(conn).items()]
                payload = build_payload(screen, news_by_code, market_news,
                                        holdings_summary, cfg.max_position_weight)
                result = pick_stocks(client, payload, screen["candidates"],
                                     cfg.max_position_weight)
            except (AIError, ValueError) as e:
                ai_status = "failed"
                result["market_comment"] = f"AI 选股失败：{e}"
                log.warning("AI 选股失败 %s: %s", target, e)
        _save_picks(conn, target, result, cfg.ai_model, ai_status)

        created_orders = []
        if ai_status == "ok":
            acc = get_account(conn)
            positions = get_positions(conn)
            for p in result["picks"]:
                if p["action"] != "buy_candidate":
                    continue
                held = positions.get(p["code"])
                held_value = (held["shares"] * (prices.get(p["code"]) or held["avg_cost"])
                              if held else 0.0)
                plan = plan_buy(p, snap["total_assets"], acc["cash"],
                                cfg.max_position_weight, held_value=held_value)
                if plan:
                    oid = create_order(conn, target, plan["code"], plan["name"], "buy",
                                       plan["target_weight"], plan["planned_shares"],
                                       plan["ref_price"], plan["reason"])
                    created_orders.append(oid)

        # 7 复盘昨日决策
        prev = prev_trading_day(conn, target)
        review_status = None
        if prev:
            rv = run_review(conn, client or _NoAIClient(), target, prev, cfg.reports_dir)
            review_status = rv["ai_status"]

        # 8 日报
        _write_daily_report(conn, cfg, target, screen, result, ai_status, snap,
                            fill_events, created_orders, review_status)
        _job_end(conn, "daily", target, "success",
                 f"picks={len(result['picks'])} orders={len(created_orders)} ai={ai_status}")
        return {"status": "success", "date": target, "ai_status": ai_status,
                "picks": len(result["picks"]), "orders": len(created_orders),
                "fills": len(fill_events), "review": review_status,
                "total_assets": snap["total_assets"]}
    except DataNotReadyError as e:
        _job_end(conn, "daily", today, "data_not_ready", str(e))
        log.warning("数据未就绪 %s: %s", today, e)
        raise
    except Exception as e:
        _job_end(conn, "daily", today, "failed", str(e))
        log.exception("每日流程失败 %s", today)
        raise


class _NoAIClient:
    def chat_json(self, *a, **k):
        raise AIError("AI 未配置")


def _write_daily_report(conn, cfg, target, screen, result, ai_status, snap,
                        fills, orders, review_status) -> None:
    lines = [f"# nine-quarter 每日报告 {target}", ""]
    lines.append(f"市场环境：{screen['market_env'].get('regime')}；"
                 f"初筛 {screen['stats']['passed']} 只通过，候选 {len(screen['candidates'])} 只")
    lines.append(f"账户总资产：{snap['total_assets']}；累计收益：{snap['cum_return']:.2%}；"
                 f"最大回撤：{snap['max_drawdown']:.2%}")
    lines.append(f"今日撮合：{len(fills)} 笔；新建模拟订单：{len(orders)} 笔")
    lines.append("")
    lines.append(f"## AI 选股（{ai_status}）")
    lines.append(result.get("market_comment", ""))
    for p in result.get("picks", []):
        lines.append(f"- {p['code']} {p['name']} [{p['action']}] 仓位{p['suggested_weight']:.0%} "
                     f"潜力{p['potential_level']}：{p['reason']}")
        lines.append(f"  - 上涨逻辑：{p['bull_logic']}；风险：{p['bear_risks']}")
    if not result.get("picks"):
        lines.append("- 当日无选股（空仓或 AI 不可用）")
    lines.append("")
    lines.append(f"## 复盘（{review_status}）")
    lines.append(f"详见复盘文件 reports/{target}.md")
    (cfg.reports_dir / f"daily-{target}.md").write_text("\n".join(lines) + "\n",
                                                      encoding="utf-8")


def run_morning(conn: sqlite3.Connection, cfg: Settings,
                today: str | None = None) -> dict:
    """上午按实时可得价格处理昨日订单；不可得则留待盘后按开盘价撮合。"""
    from .data_sources.akshare_source import fetch_realtime
    today = today or beijing_today()
    ensure_account(conn, cfg.initial_capital)
    try:
        if not is_trading_day(conn, today):
            return {"status": "skipped", "reason": "非交易日"}
    except ValueError:
        return {"status": "skipped", "reason": "日历未覆盖"}
    _job_start(conn, "morning", today)
    try:
        pending = conn.execute(
            "SELECT DISTINCT code FROM orders WHERE status='pending' AND decision_date<?",
            (today,)).fetchall()
        bars: dict[str, dict] = {}
        for r in pending:
            rt = fetch_realtime(r["code"])
            if not rt or rt.get("latest") is None or rt.get("preclose") is None:
                continue
            latest = rt["latest"]
            bars[r["code"]] = {
                "open": latest, "high": rt.get("high") or latest,
                "low": rt.get("low") or latest, "close": latest,
                "preclose": rt["preclose"], "volume": 1, "trade_status": 1, "is_st": 0,
            }
        events = process_pending_orders(
            conn, today, bars, cfg.order_expire_days, _cost_kwargs(cfg),
            price_source="realtime_snapshot")
        log.info("上午撮合 %s：%d 笔", today, len(events))
        _job_end(conn, "morning", today, "success", f"fills={len(events)}")
        return {"status": "success", "date": today, "fills": len(events)}
    except Exception as e:
        _job_end(conn, "morning", today, "failed", str(e))
        log.exception("上午撮合失败 %s", today)
        raise