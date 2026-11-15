"""新闻 AI 分析：批量判断利好/利空/中性、影响周期、相关股票、可信度。"""
from __future__ import annotations

import json

from .prompts import NEWS_SYSTEM

_SENTIMENTS = {"positive", "negative", "neutral"}
_HORIZONS = {"short", "medium_long", ""}


def analyze_news_batch(client, items: list[dict],
                       relevant_codes: list[str]) -> dict[int, dict]:
    """返回 {news_id: 分类结果}。白名单过滤受影响代码，非法值归一化。"""
    if not items:
        return {}
    compact = [
        {"id": it["id"], "title": it.get("title", ""),
         "summary": (it.get("summary", "") or "")[:200],
         "related_code": it.get("stock_code", "")}
        for it in items
    ]
    user = json.dumps(
        {"relevant_codes": relevant_codes, "news": compact}, ensure_ascii=False)
    raw = client.chat_json(NEWS_SYSTEM, user, retries=1)
    if not isinstance(raw, list):
        raise ValueError("新闻分析输出不是数组")
    whitelist = set(relevant_codes)
    out: dict[int, dict] = {}
    for r in raw:
        if not isinstance(r, dict) or "id" not in r:
            continue
        try:
            nid = int(r["id"])
        except (TypeError, ValueError):
            continue
        sentiment = r.get("sentiment", "neutral")
        if sentiment not in _SENTIMENTS:
            sentiment = "neutral"
        horizon = r.get("horizon", "")
        if horizon not in _HORIZONS:
            horizon = ""
        codes = r.get("affected_codes", []) or []
        codes = [c for c in codes if c in whitelist]
        out[nid] = {
            "sentiment": sentiment, "horizon": horizon, "affected_codes": codes,
            "verified": bool(r.get("verified", True)),
            "relevant": bool(r.get("relevant", True)),
        }
    return out