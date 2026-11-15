"""新闻 AI 分析测试（stub 客户端，验证映射与白名单过滤）。"""
from backend.ai_analysis.news_analysis import analyze_news_batch


class _Stub:
    def __init__(self, output):
        self.output = output

    def chat_json(self, system, user, retries=1):
        return self.output


def _items():
    return [
        {"id": 1, "title": "央行降准", "summary": "释放流动性", "stock_code": ""},
        {"id": 2, "title": "浦发回购", "summary": "回购股份", "stock_code": "sh.600000"},
    ]


class TestNewsAnalysis:
    def test_maps_by_id(self):
        out = [
            {"id": 1, "sentiment": "positive", "horizon": "short",
             "affected_codes": [], "verified": True, "relevant": True},
            {"id": 2, "sentiment": "positive", "horizon": "medium_long",
             "affected_codes": ["sh.600000"], "verified": True, "relevant": True},
        ]
        res = analyze_news_batch(_Stub(out), _items(), ["sh.600000"])
        assert res[1]["sentiment"] == "positive"
        assert res[2]["affected_codes"] == ["sh.600000"]

    def test_affected_codes_whitelisted(self):
        out = [{"id": 1, "sentiment": "positive", "horizon": "short",
                "affected_codes": ["sh.600000", "sh.999999"],
                "verified": True, "relevant": True}]
        res = analyze_news_batch(_Stub(out), _items(), ["sh.600000"])
        assert res[1]["affected_codes"] == ["sh.600000"]

    def test_invalid_sentiment_normalized(self):
        out = [{"id": 1, "sentiment": "very_good", "horizon": "xxx",
                "affected_codes": [], "verified": True, "relevant": True}]
        res = analyze_news_batch(_Stub(out), _items(), [])
        assert res[1]["sentiment"] == "neutral"
        assert res[1]["horizon"] == ""

    def test_unverified_flag(self):
        out = [{"id": 1, "sentiment": "positive", "horizon": "short",
                "affected_codes": [], "verified": False, "relevant": True}]
        res = analyze_news_batch(_Stub(out), _items(), [])
        assert res[1]["verified"] is False

    def test_missing_id_skipped(self):
        out = [{"sentiment": "positive"}]
        res = analyze_news_batch(_Stub(out), _items(), [])
        assert res == {}

    def test_empty_items(self):
        assert analyze_news_batch(_Stub([]), [], []) == {}