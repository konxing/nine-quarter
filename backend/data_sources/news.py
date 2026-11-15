"""新闻/公告存储：归一化去重、保存来源与时间、AI 分析标记。"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3

_PUNCT = re.compile(r"[\s\W_]+", re.UNICODE)


def title_hash(title: str) -> str:
    norm = _PUNCT.sub("", title).lower()
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()


def save_news(conn: sqlite3.Connection, items: list[dict]) -> tuple[int, int]:
    """写入新闻，按 (标题归一化哈希, 发布时间) 去重。返回 (新增, 重复)。"""
    new = dup = 0
    for it in items:
        title = it.get("title", "")
        if not title:
            continue
        h = title_hash(title)
        cur = conn.execute(
            "INSERT OR IGNORE INTO news(title,summary,source,url,publish_time,"
            "fetched_at,scope,stock_code,category,title_hash,verified) "
            "VALUES (?,?,?,?,?,datetime('now'),?,?,?,?,0)",
            (title, it.get("summary", ""), it.get("source", ""), it.get("url", ""),
             it.get("publish_time", ""), it.get("scope", "market"),
             it.get("stock_code", ""), it.get("category", "news"), h),
        )
        if cur.rowcount:
            new += 1
        else:
            dup += 1
    conn.commit()
    return new, dup


def unanalyzed_news(conn: sqlite3.Connection, scope: str | None = None,
                    limit: int = 200) -> list[dict]:
    q = "SELECT * FROM news WHERE ai_analyzed=0"
    params: list = []
    if scope:
        q += " AND scope=?"
        params.append(scope)
    q += " ORDER BY publish_time DESC LIMIT ?"
    params.append(limit)
    return [dict(r) for r in conn.execute(q, params)]


def mark_analyzed(conn: sqlite3.Connection, news_id: int, sentiment: str,
                  horizon: str, affected_codes: list[str], verified: bool,
                  relevant: bool) -> None:
    conn.execute(
        "UPDATE news SET sentiment=?, horizon=?, affected_codes=?, verified=?, "
        "relevant=?, ai_analyzed=1 WHERE id=?",
        (sentiment, horizon, json.dumps(affected_codes, ensure_ascii=False),
         1 if verified else 0, 1 if relevant else 0, news_id),
    )
    conn.commit()