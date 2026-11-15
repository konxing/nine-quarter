"""AKShare 中文列映射测试（合成 DataFrame 夹具，不触网）。"""
import pandas as pd

from backend.data_sources.akshare_source import (
    info_from_individual,
    realtime_from_bid_ask,
    rows_from_announcements,
    rows_from_global,
    rows_from_stock_news,
)


class TestGlobalNews:
    def test_mapping(self):
        df = pd.DataFrame([{
            "标题": "央行降准", "摘要": "释放流动性", "发布时间": "2026-11-10 08:00:00",
            "链接": "https://example.com/a",
        }])
        rows = rows_from_global(df)
        assert rows[0]["title"] == "央行降准"
        assert rows[0]["summary"] == "释放流动性"
        assert rows[0]["scope"] == "market"
        assert rows[0]["url"] == "https://example.com/a"
        assert rows[0]["publish_time"] == "2026-11-10 08:00:00"


class TestStockNews:
    def test_mapping(self):
        df = pd.DataFrame([{
            "新闻标题": "浦发银行回购", "新闻内容": "回购60万股",
            "发布时间": "2026-11-06 19:54:00", "文章来源": "证券日报",
            "新闻链接": "https://example.com/n",
        }])
        rows = rows_from_stock_news(df, "sh.600000")
        assert rows[0]["title"] == "浦发银行回购"
        assert rows[0]["stock_code"] == "sh.600000"
        assert rows[0]["scope"] == "stock"
        assert rows[0]["source"] == "证券日报"


class TestAnnouncements:
    def test_mapping(self):
        df = pd.DataFrame([{
            "代码": "688827", "名称": "某公司", "公告标题": "上市公告",
            "公告类型": "首发提示性公告", "公告日期": "2026-11-09",
            "网址": "https://example.com/notice",
        }])
        rows = rows_from_announcements(df)
        assert rows[0]["stock_code"] == "688827"
        assert rows[0]["title"] == "上市公告"
        assert rows[0]["category"] == "announcement"
        assert rows[0]["publish_time"] == "2026-11-09"


class TestRealtime:
    def test_trading_values(self):
        df = pd.DataFrame({"item": ["最新", "今开", "昨收", "涨停", "跌停", "最高", "最低"],
                           "value": ["10.5", "10.0", "10.1", "11.11", "9.09", "10.6", "9.9"]})
        rt = realtime_from_bid_ask(df)
        assert rt["latest"] == 10.5
        assert rt["open"] == 10.0
        assert rt["preclose"] == 10.1
        assert rt["upper_limit"] == 11.11

    def test_premarket_dash_becomes_none(self):
        df = pd.DataFrame({"item": ["最新", "今开", "昨收"], "value": ["-", "-", "10.1"]})
        rt = realtime_from_bid_ask(df)
        assert rt["latest"] is None
        assert rt["open"] is None
        assert rt["preclose"] == 10.1


class TestIndividualInfo:
    def test_mapping(self):
        df = pd.DataFrame({"item": ["行业", "总市值", "股票简称"],
                           "value": ["银行Ⅱ", "336388966830.0", "浦发银行"]})
        info = info_from_individual(df)
        assert info["industry"] == "银行Ⅱ"
        assert info["total_mv"] == 336388966830.0
        assert info["name"] == "浦发银行"