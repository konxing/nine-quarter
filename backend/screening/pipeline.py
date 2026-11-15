"""初筛编排：从 SQLite 读全市场行情 -> 指标 -> 过滤 -> 行业相对强度 -> 排序取前 N。

确定性：同一份数据库输入产出完全相同的候选与评分（验收要求 3）。
行业相对强度：个股 20 日收益减去同行业（通过过滤者）中位数；无行业标签则为 0。
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from statistics import median

from .filters import passes_filters
from .indicators import compute_indicators, market_environment
from .ranker import RULE_VERSION, prescreen

_BAR_COLS = ("code,date,open,high,low,close,preclose,volume,amount,turn,"
             "trade_status,pct_chg,pe_ttm,pb_mrq,is_st")


def _load_recent_bars(conn: sqlite3.Connection, cutoff: str,
                      as_of: str | None = None) -> dict[str, list[dict]]:
    """Load bars only up to the decision date; never read future rows."""
    as_of = as_of or cutoff
    rows = conn.execute(
        f"SELECT {_BAR_COLS} FROM daily_bars WHERE date>=? AND date<=? ORDER BY code,date",
        (cutoff, as_of),
    ).fetchall()
    grouped: dict[str, list[dict]] = {}
    for r in rows:
        grouped.setdefault(r["code"], []).append(dict(r))
    return grouped


def run_prescreen(
    conn: sqlite3.Connection,
    expected_date: str,
    prescreen_count: int = 30,
    min_history: int = 60,
    min_avg_amount: float = 5e7,
    min_price: float = 2.0,
    exclude_st: bool = True,
    index_code: str = "sh.000300",
    lookback_calendar_days: int = 200,
) -> dict:
    cutoff = (dt.date.fromisoformat(expected_date)
              - dt.timedelta(days=lookback_calendar_days)).isoformat()
    stocks = {
        r["code"]: dict(r)
        for r in conn.execute(
            "SELECT code,name,industry,status,total_mv FROM stocks WHERE type='1'")
    }
    bars_by_code = _load_recent_bars(conn, cutoff, expected_date)

    idx_rows = conn.execute(
        "SELECT date,code,close,preclose,volume,amount,pct_chg FROM index_bars "
        "WHERE code=? AND date>=? AND date<=? ORDER BY date",
        (index_code, cutoff, expected_date),
    ).fetchall()
    mkt = market_environment([dict(r) for r in idx_rows])

    passed: list[tuple[str, dict, dict]] = []
    for code, meta in stocks.items():
        ind = compute_indicators(bars_by_code.get(code, []), min_bars=min_history)
        ok, _reason = passes_filters(
            ind, meta, expected_date, min_history=min_history,
            min_avg_amount=min_avg_amount, min_price=min_price, exclude_st=exclude_st)
        if ok:
            passed.append((code, meta, ind))

    groups: dict[str, list[float]] = {}
    for _code, meta, ind in passed:
        industry = meta.get("industry") or ""
        if industry:
            groups.setdefault(industry, []).append(ind["ret_20d"])
    ind_median = {k: median(v) for k, v in groups.items()}

    cands = []
    for code, meta, ind in passed:
        industry = meta.get("industry") or ""
        rs = (ind["ret_20d"] - ind_median[industry]) if industry else 0.0
        cands.append({
            "code": code, "name": meta["name"], "industry": industry,
            "indicators": ind, "industry_rs": round(rs, 6),
            "total_mv": meta.get("total_mv"),
        })
    top = prescreen(cands, prescreen_count, mkt)
    return {
        "run_date": expected_date, "rule_version": RULE_VERSION,
        "market_env": mkt, "candidates": top,
        "stats": {"universe": len(stocks), "passed": len(passed), "selected": len(top)},
    }