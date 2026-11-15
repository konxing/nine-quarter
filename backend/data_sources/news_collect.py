"""新闻收集编排：市场快讯 + 公告 + 候选股新闻 -> 去重入库 -> AI 分析 -> 紧凑摘要。

来源失败独立跳过（不阻塞主流程）；无 AI 时保留原始标题摘要（不做主观判断）。
只保留对候选股/大盘有意义的信息，控制 Token。
"""
from __future__ import annotations

import json
import logging
import sqlite3

from ..ai_analysis.news_analysis import analyze_news_batch
from .akshare_source import (
    fetch_announcements,
    fetch_global_news,
    fetch_stock_news,
)
from .baostock_source import DataSourceError
from .news import mark_analyzed, save_news, unanalyzed_news

log = logging.getLogger("nine-quarter.news")


def collect_news(conn: sqlite3.Connection, target_date: str,
                 candidate_codes: list[str], client=None,
                 per_stock_limit: int = 5) -> tuple[dict, list]:
    # 1 收集（各来源独立容错）
    try:
        save_news(conn, fetch_global_news(100))
    except DataSourceError as e:
        log.warning("市场快讯跳过: %s", e)
    try:
        anns = fetch_announcements(target_date.replace("-", ""))
        save_news(conn, anns)
    except DataSourceError as e:
        log.warning("公告跳过: %s", e)
    for code in candidate_codes:
        try:
            items = fetch_stock_news(code)
            save_news(conn, items[:20])
        except DataSourceError as e:
            log.warning("个股新闻跳过 %s: %s", code, e)

    # 2 AI 分析（分批，每批≤40）
    if client is not None:
        pending = unanalyzed_news(conn, limit=400)
        for i in range(0, len(pending), 40):
            batch = pending[i:i + 40]
            try:
                res = analyze_news_batch(client, batch, candidate_codes)
                for nid, r in res.items():
                    mark_analyzed(conn, nid, r["sentiment"], r["horizon"],
                                  r["affected_codes"], r["verified"], r["relevant"])
            except Exception as e:
                log.warning("新闻 AI 分析批次失败: %s", e)
                break

    # 3 构建紧凑摘要
    code_set = set(candidate_codes)
    news_by_code: dict[str, list] = {c: [] for c in candidate_codes}
    market_news: list[dict] = []
    rows = conn.execute(
        "SELECT * FROM news WHERE relevant=1 ORDER BY publish_time DESC LIMIT 500"
    ).fetchall()
    for r in rows:
        item = {
            "title": r["title"], "sentiment": r["sentiment"] or "未分析",
            "horizon": r["horizon"], "verified": bool(r["verified"]),
            "publish_time": r["publish_time"], "category": r["category"],
            "source": r["source"],
        }
        affected = set(json.loads(r["affected_codes"] or "[]"))
        if r["stock_code"]:
            affected.add(r["stock_code"])
        if r["scope"] == "market":
            if len(market_news) < 10:
                market_news.append(item)
        for code in affected & code_set:
            if len(news_by_code[code]) < per_stock_limit:
                news_by_code[code].append(item)
    return news_by_code, market_news