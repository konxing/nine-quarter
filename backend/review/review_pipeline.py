"""复盘编排：量化表现摘要 -> AI 复盘 -> 保存报告/建议 -> 持仓建议转卖出订单。

AI 失效时降级为纯量化报告（ai_status=failed），不伪造结论、不产生订单。
改进建议仅保存（status=proposed），不自动修改筛股算法。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from ..ai_analysis.client import AIError
from ..ai_analysis.prompts import REVIEW_SYSTEM
from ..simulation.account import get_account, get_positions
from ..simulation.broker import create_order
from ..simulation.planning import plan_sell
from .tracker import update_outcomes, update_position_outcomes

log = logging.getLogger("nine-quarter.review")


def _latest_price(conn, code, date):
    r = conn.execute("SELECT close FROM daily_bars WHERE code=? AND date=?",
                     (code, date)).fetchone()
    return float(r["close"]) if r and r["close"] is not None else None


def _account_view(conn, code, target_date, eval_date, mark_price) -> dict:
    """账户口径：推荐后实际成交价（含费用）对比评估日价格。

    收盘价口径回答"选股对不对"，账户口径回答"这个账户实际能赚多少"。
    买入只能发生在决策日之后，故只统计 (target_date, eval_date] 的买入成交；
    未成交则明确标记未买入，不估算。
    """
    buys = conn.execute(
        "SELECT trade_date,price,shares,amount,commission,stamp_tax,transfer_fee "
        "FROM trades WHERE code=? AND side='buy' AND trade_date>? AND trade_date<=? "
        "ORDER BY trade_date,id", (code, target_date, eval_date)).fetchall()
    if not buys:
        return {"bought": False}
    shares = sum(int(b["shares"]) for b in buys)
    amount = sum(float(b["amount"]) for b in buys)
    fees = sum(float(b["commission"] or 0) + float(b["stamp_tax"] or 0)
               + float(b["transfer_fee"] or 0) for b in buys)
    if shares <= 0:
        return {"bought": False}
    fill_price = amount / shares
    unit_cost = (amount + fees) / shares
    ret = (mark_price / unit_cost - 1) * 100 if mark_price and unit_cost else None
    return {
        "bought": True,
        "fill_date": buys[0]["trade_date"],
        "fill_price": round(fill_price, 4),
        "unit_cost": round(unit_cost, 4),
        "shares": shares,
        "fees": round(fees, 2),
        "mark_price": mark_price,
        "account_ret_pct": round(ret, 4) if ret is not None else None,
    }


def build_quant_summary(conn, target_date: str, eval_date: str,
                        index_code: str = "sh.000300") -> dict:
    picks = []
    for p in conn.execute("SELECT * FROM picks WHERE run_date=? ORDER BY id",
                          (target_date,)):
        outcomes = [dict(o) for o in conn.execute(
            "SELECT checkpoint,eval_date,ret_pct,industry_ret_pct,index_ret_pct,"
            "excess_vs_index FROM pick_outcomes WHERE pick_id=? ORDER BY checkpoint",
            (p["id"],))]
        d = dict(p)
        d["outcomes"] = outcomes
        d["account_view"] = _account_view(
            conn, p["code"], target_date, eval_date,
            _latest_price(conn, p["code"], eval_date))
        picks.append(d)

    acc = get_account(conn)
    positions = get_positions(conn)
    holdings = []
    for code, pos in positions.items():
        px = _latest_price(conn, code, eval_date)
        name = conn.execute("SELECT name FROM stocks WHERE code=?", (code,)).fetchone()
        mv = pos["shares"] * (px if px is not None else pos["avg_cost"])
        holdings.append({
            "code": code, "name": name["name"] if name else "",
            "shares": pos["shares"], "avg_cost": round(pos["avg_cost"], 3),
            "latest_price": px, "market_value": round(mv, 2),
            "unrealized_pnl": round(mv - pos["cost_amount"], 2),
        })
    idx0 = conn.execute("SELECT close FROM index_bars WHERE code=? AND date=?",
                        (index_code, target_date)).fetchone()
    idx1 = conn.execute("SELECT close FROM index_bars WHERE code=? AND date=?",
                        (index_code, eval_date)).fetchone()
    index_ret = None
    if idx0 and idx1 and idx0["close"]:
        index_ret = round((idx1["close"] / idx0["close"] - 1) * 100, 4)
    trades = [dict(t) for t in conn.execute(
        "SELECT code,side,trade_date,price,shares FROM trades "
        "WHERE trade_date>? AND trade_date<=? ORDER BY trade_date",
        (target_date, eval_date))]
    # AI 持仓判断及后续表现（供复盘验证当时判断对错）
    position_decisions = []
    for d in conn.execute(
            "SELECT * FROM position_decisions WHERE decision_date=? ORDER BY id",
            (target_date,)):
        outcomes = [dict(o) for o in conn.execute(
            "SELECT checkpoint,eval_date,ret_pct,index_ret_pct "
            "FROM position_decision_outcomes WHERE decision_id=? ORDER BY checkpoint",
            (d["id"],))]
        dd = dict(d)
        dd["outcomes"] = outcomes
        position_decisions.append(dd)
    return {
        "target_date": target_date, "eval_date": eval_date,
        "picks": picks, "holdings": holdings, "trades": trades,
        "position_decisions": position_decisions,
        "account": {"cash": round(acc["cash"], 2),
                    "realized_pnl": round(acc["realized_pnl"], 2),
                    "initial_capital": acc["initial_capital"]},
        "index_code": index_code, "index_ret_pct": index_ret,
    }


def _normalize_review(raw: dict) -> dict:
    def _list(key):
        v = raw.get(key, [])
        return v if isinstance(v, list) else []
    advice = []
    for a in _list("position_advice"):
        if isinstance(a, dict) and a.get("action") in ("hold", "reduce", "sell") and a.get("code"):
            advice.append(a)
    return {
        "summary": str(raw.get("summary", "")),
        "correct_judgments": _list("correct_judgments"),
        "mistakes": [m for m in _list("mistakes") if isinstance(m, dict)],
        "uncertain": _list("uncertain"),
        "improvements": [m for m in _list("improvements") if isinstance(m, dict)],
        "position_advice": advice,
    }


def _render_md(quant: dict, report: dict, ai_status: str) -> str:
    lines = [f"# 每日复盘 {quant['eval_date']}（复盘 {quant['target_date']} 决策）", ""]
    lines.append(f"基准 {quant['index_code']} 区间涨跌：{quant['index_ret_pct']}%")
    lines.append("")
    lines.append("## 昨日推荐表现")
    for p in quant["picks"]:
        oc = ", ".join(
            f"第{o['checkpoint']}日 {o['ret_pct']}%(超额{o['excess_vs_index']})"
            for o in p["outcomes"] if o.get("ret_pct") is not None)
        lines.append(f"- {p['code']} {p['name']} [{p['action']}] 参考价{p['ref_price']}：{oc or '暂无后续数据'}")
        av = p.get("account_view") or {}
        if av.get("bought"):
            c1 = next((o for o in p["outcomes"] if o["checkpoint"] == 1), None)
            close_ret = f"{c1['ret_pct']}%" if c1 and c1.get("ret_pct") is not None else "暂无"
            acc_ret = (f"{av['account_ret_pct']}%" if av.get("account_ret_pct") is not None
                       else "暂无评估日价格")
            lines.append(f"  - 账户口径：{av['fill_date']} 成交价{av['fill_price']}"
                         f"（含费用单位成本{av['unit_cost']}）{av['shares']}股，"
                         f"账户收益{acc_ret} vs 收盘价口径{close_ret}")
        else:
            lines.append("  - 账户口径：未买入，仅观察，不产生账户收益")
    lines.append("")
    lines.append("## 当前持仓")
    for h in quant["holdings"]:
        lines.append(f"- {h['code']} {h['name']} {h['shares']}股 成本{h['avg_cost']} "
                     f"现价{h['latest_price']} 浮盈{h['unrealized_pnl']}")
    if not quant["holdings"]:
        lines.append("- 空仓")
    lines.append("")
    if ai_status == "ok":
        lines.append("## AI 复盘")
        lines.append(report.get("summary", ""))
        lines.append("\n### 主要正确判断")
        lines += [f"- {x}" for x in report.get("correct_judgments", [])]
        lines.append("\n### 主要决策失误")
        lines += [f"- [{m.get('type','')}] {m.get('detail','')}" for m in report.get("mistakes", [])]
        lines.append("\n### 尚无法确定")
        lines += [f"- {x}" for x in report.get("uncertain", [])]
        lines.append("\n### 改进建议（仅保存，待验证）")
        lines += [f"- [{m.get('category','')}] {m.get('content','')}" for m in report.get("improvements", [])]
        lines.append("\n### 持仓建议")
        lines += [f"- {a.get('code','')} {a.get('action','')}：{a.get('reason','')}" for a in report.get("position_advice", [])]
    else:
        lines.append("## AI 复盘不可用")
        lines.append("本日 AI 接口失效，仅保留上方量化数据，不产生主观结论与交易订单。")
    return "\n".join(lines) + "\n"


def run_review(conn, client, review_date: str, target_date: str,
               reports_dir: Path, index_code: str = "sh.000300") -> dict:
    reports_dir = Path(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    update_outcomes(conn, review_date, index_code)
    update_position_outcomes(conn, review_date, index_code)
    quant = build_quant_summary(conn, target_date, review_date, index_code)

    prev = conn.execute("SELECT ai_status FROM reviews WHERE review_date=?",
                        (review_date,)).fetchone()
    # 仅当此前已成功复盘过才跳过副作用，避免重复建议/重复下单；
    # 若此前失败（如 AI 临时不可用），重试成功时应正常写入。
    already_ok = prev is not None and prev["ai_status"] == "ok"
    ai_status = "ok"
    report: dict = {}
    raw: dict = {}
    try:
        raw = client.chat_json(REVIEW_SYSTEM, json.dumps(quant, ensure_ascii=False), retries=1)
        if not isinstance(raw, dict):
            raise ValueError("复盘输出非对象")
        report = _normalize_review(raw)
    except (AIError, ValueError) as e:
        ai_status = "failed"
        log.warning("AI 复盘失败 %s: %s", review_date, e)

    report_md = _render_md(quant, report, ai_status)
    conn.execute(
        "INSERT INTO reviews(review_date,target_date,ai_status,quant_json,report_md,ai_raw,created_at) "
        "VALUES (?,?,?,?,?,?,datetime('now')) "
        "ON CONFLICT(review_date) DO UPDATE SET target_date=excluded.target_date, "
        "ai_status=excluded.ai_status, quant_json=excluded.quant_json, "
        "report_md=excluded.report_md, ai_raw=excluded.ai_raw",
        (review_date, target_date, ai_status, json.dumps(quant, ensure_ascii=False),
         report_md, json.dumps(raw, ensure_ascii=False)))
    conn.commit()

    if ai_status == "ok" and not already_ok:
        for m in report.get("improvements", []):
            conn.execute(
                "INSERT INTO suggestions(review_date,category,content,status,created_at) "
                "VALUES (?,?,?,'proposed',datetime('now'))",
                (review_date, m.get("category", ""), m.get("content", "")))
        positions = get_positions(conn)
        for a in report.get("position_advice", []):
            code = a["code"]
            if code not in positions:
                continue
            name_row = conn.execute("SELECT name FROM stocks WHERE code=?", (code,)).fetchone()
            name = name_row["name"] if name_row else ""
            ref_price = _latest_price(conn, code, review_date)
            # 结构化保存 AI 当日持仓判断（含 hold），供后续复盘验证
            conn.execute(
                "INSERT INTO position_decisions(decision_date,code,name,action,reason,"
                "ref_price,created_at) VALUES (?,?,?,?,?,?,datetime('now')) "
                "ON CONFLICT(decision_date,code) DO UPDATE SET action=excluded.action, "
                "reason=excluded.reason, ref_price=excluded.ref_price",
                (review_date, code, name, a["action"], a.get("reason", ""), ref_price))
            # 仅卖出/减仓生成模拟订单
            plan = plan_sell(code, name, a["action"], positions[code]["shares"],
                             a.get("reason", ""))
            if plan:
                create_order(conn, review_date, code, plan["name"], "sell", 0.0,
                             plan["planned_shares"], ref_price or 0.0, plan["reason"])
        conn.commit()

    (reports_dir / f"{review_date}.md").write_text(report_md, encoding="utf-8")
    return {"ai_status": ai_status, "review_date": review_date,
            "target_date": target_date, "report_md": report_md}