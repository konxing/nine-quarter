"""AKShare 数据源封装：新闻、公告、实时盘口、个股信息。

AKShare 聚合东方财富等公开免费接口，个人非商业研究使用。
每个 fetch_* 独立 try/except：单一来源失败不影响整体，失败抛 DataSourceError
由调用方决定跳过。绝不伪造数据。中文列名按实测接口固定映射。
"""
from __future__ import annotations

import logging

from .baostock_source import DataSourceError

log = logging.getLogger("nine-quarter.akshare")


def _s(v) -> str:
    if v is None:
        return ""
    return str(v).strip()


def _f(v) -> float | None:
    s = _s(v)
    if s in ("", "-", "--", "—"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def rows_from_global(df) -> list[dict]:
    out = []
    for _, r in df.iterrows():
        title = _s(r.get("标题"))
        if not title:
            continue
        out.append({
            "title": title, "summary": _s(r.get("摘要")),
            "publish_time": _s(r.get("发布时间")), "url": _s(r.get("链接")),
            "source": "东方财富全球快讯", "scope": "market", "stock_code": "",
            "category": "news",
        })
    return out


def rows_from_stock_news(df, code: str) -> list[dict]:
    out = []
    for _, r in df.iterrows():
        title = _s(r.get("新闻标题"))
        if not title:
            continue
        out.append({
            "title": title, "summary": _s(r.get("新闻内容"))[:500],
            "publish_time": _s(r.get("发布时间")), "source": _s(r.get("文章来源")),
            "url": _s(r.get("新闻链接")), "scope": "stock", "stock_code": code,
            "category": "news",
        })
    return out


def rows_from_announcements(df) -> list[dict]:
    out = []
    for _, r in df.iterrows():
        title = _s(r.get("公告标题"))
        if not title:
            continue
        out.append({
            "title": title, "summary": _s(r.get("公告类型")),
            "publish_time": _s(r.get("公告日期")), "url": _s(r.get("网址")),
            "source": "东方财富公告", "scope": "stock",
            "stock_code": _s(r.get("代码")), "name": _s(r.get("名称")),
            "category": "announcement",
        })
    return out


def realtime_from_bid_ask(df) -> dict:
    m = {_s(r["item"]): r["value"] for _, r in df.iterrows()}
    return {
        "latest": _f(m.get("最新")), "open": _f(m.get("今开")),
        "preclose": _f(m.get("昨收")), "high": _f(m.get("最高")),
        "low": _f(m.get("最低")), "upper_limit": _f(m.get("涨停")),
        "lower_limit": _f(m.get("跌停")),
    }


def info_from_individual(df) -> dict:
    m = {_s(r["item"]): r["value"] for _, r in df.iterrows()}
    return {
        "industry": _s(m.get("行业")), "total_mv": _f(m.get("总市值")),
        "name": _s(m.get("股票简称")),
    }


# ---- 网络调用（真实运行验收）----

def fetch_global_news(limit: int = 100) -> list[dict]:
    import akshare as ak
    try:
        df = ak.stock_info_global_em()
        return rows_from_global(df)[:limit]
    except Exception as e:
        raise DataSourceError(f"全球快讯获取失败: {e}") from e


def fetch_stock_news(code: str) -> list[dict]:
    import akshare as ak
    num = code.split(".")[-1]
    try:
        df = ak.stock_news_em(symbol=num)
        return rows_from_stock_news(df, code)
    except Exception as e:
        raise DataSourceError(f"个股新闻获取失败 {code}: {e}") from e


def fetch_announcements(date_yyyymmdd: str) -> list[dict]:
    import akshare as ak
    try:
        df = ak.stock_notice_report(symbol="全部", date=date_yyyymmdd)
        return rows_from_announcements(df)
    except Exception as e:
        raise DataSourceError(f"公告获取失败 {date_yyyymmdd}: {e}") from e


def fetch_realtime(code: str) -> dict | None:
    import akshare as ak
    num = code.split(".")[-1]
    try:
        df = ak.stock_bid_ask_em(symbol=num)
        return realtime_from_bid_ask(df)
    except Exception as e:
        log.warning("实时盘口获取失败 %s: %s", code, e)
        return None


def fetch_stock_info(code: str) -> dict | None:
    import akshare as ak
    num = code.split(".")[-1]
    try:
        df = ak.stock_individual_info_em(symbol=num)
        return info_from_individual(df)
    except Exception as e:
        log.warning("个股信息获取失败 %s: %s", code, e)
        return None