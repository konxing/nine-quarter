"""新闻存储与去重测试。对应模块一信息处理：删除重复、保存来源/时间/相关股票。"""
import sqlite3

import pytest

from backend.data_sources.news import (
    mark_analyzed,
    save_news,
    title_hash,
    unanalyzed_news,
)
from backend.db import SCHEMA


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    yield c
    c.close()


def _item(title="央行降准", publish_time="2026-11-10 08:00:00", **kw):
    d = dict(title=title, summary="释放流动性", source="东方财富",
             url="https://example.com", publish_time=publish_time,
             scope="market", stock_code="", category="news")
    d.update(kw)
    return d


class TestTitleHash:
    def test_normalizes_whitespace_punct(self):
        assert title_hash("央行 降准！") == title_hash("央行降准")

    def test_different_titles_differ(self):
        assert title_hash("央行降准") != title_hash("央行加息")


class TestSaveNews:
    def test_insert_new(self, conn):
        new, dup = save_news(conn, [_item()])
        assert new == 1 and dup == 0
        assert conn.execute("SELECT COUNT(*) n FROM news").fetchone()["n"] == 1

    def test_duplicate_ignored(self, conn):
        save_news(conn, [_item()])
        new, dup = save_news(conn, [_item()])
        assert new == 0 and dup == 1
        assert conn.execute("SELECT COUNT(*) n FROM news").fetchone()["n"] == 1

    def test_normalized_duplicate_ignored(self, conn):
        save_news(conn, [_item(title="央行降准")])
        new, dup = save_news(conn, [_item(title="央行 降准！")])
        assert new == 0 and dup == 1

    def test_different_time_kept(self, conn):
        save_news(conn, [_item()])
        new, dup = save_news(conn, [_item(publish_time="2026-11-10 09:00:00")])
        assert new == 1 and dup == 0

    def test_new_news_is_marked_unverified(self, conn):
        """未经过 AI 分析的新闻默认标记为未验证。"""
        save_news(conn, [_item()])
        row = conn.execute("SELECT verified,ai_analyzed FROM news").fetchone()
        assert row["verified"] == 0
        assert row["ai_analyzed"] == 0


class TestAnalyze:
    def test_unanalyzed_then_mark(self, conn):
        save_news(conn, [_item()])
        items = unanalyzed_news(conn)
        assert len(items) == 1
        nid = items[0]["id"]
        mark_analyzed(conn, nid, sentiment="positive", horizon="short",
                      affected_codes=["sh.600000"], verified=True, relevant=True)
        assert unanalyzed_news(conn) == []
        row = conn.execute("SELECT * FROM news WHERE id=?", (nid,)).fetchone()
        assert row["sentiment"] == "positive"
        assert row["ai_analyzed"] == 1
        assert "sh.600000" in row["affected_codes"]

    def test_irrelevant_excluded_from_unanalyzed_after_mark(self, conn):
        save_news(conn, [_item()])
        nid = unanalyzed_news(conn)[0]["id"]
        mark_analyzed(conn, nid, sentiment="neutral", horizon="",
                      affected_codes=[], verified=True, relevant=False)
        assert unanalyzed_news(conn) == []