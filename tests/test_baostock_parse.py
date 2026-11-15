"""BaoStock 原始行解析测试（纯函数，不触网）。"""
from backend.data_sources.baostock_source import parse_daily_row, parse_index_row


DAILY_FIELDS = ["date", "code", "open", "high", "low", "close", "preclose",
                "volume", "amount", "turn", "tradestatus", "pctChg",
                "peTTM", "pbMRQ", "isST"]


class TestParseDaily:
    def test_normal_row(self):
        row = ["2026-11-09", "sh.600000", "9.00", "9.20", "8.90", "9.10",
               "8.95", "1000000", "9100000", "0.5", "1", "1.68",
               "5.1", "0.6", "0"]
        d = parse_daily_row(DAILY_FIELDS, row)
        assert d["code"] == "sh.600000"
        assert d["date"] == "2026-11-09"
        assert d["close"] == 9.10
        assert d["trade_status"] == 1
        assert d["pct_chg"] == 1.68
        assert d["is_st"] == 0
        assert d["pe_ttm"] == 5.1

    def test_empty_numeric_becomes_none(self):
        row = ["2026-11-09", "sh.600000", "", "", "", "", "", "0", "0",
               "", "0", "", "", "", "1"]
        d = parse_daily_row(DAILY_FIELDS, row)
        assert d["close"] is None
        assert d["trade_status"] == 0
        assert d["is_st"] == 1
        assert d["pe_ttm"] is None

    def test_missing_optional_fields_ok(self):
        fields = ["date", "code", "close", "volume", "tradestatus"]
        row = ["2026-11-09", "sh.600000", "9.1", "100", "1"]
        d = parse_daily_row(fields, row)
        assert d["close"] == 9.1
        assert d["pe_ttm"] is None


class TestParseIndex:
    def test_index_row(self):
        fields = ["date", "code", "open", "high", "low", "close",
                  "preclose", "volume", "amount", "pctChg"]
        row = ["2026-11-09", "sh.000001", "3000", "3050", "2990", "3040",
               "3000", "100000000", "100000000000", "1.33"]
        d = parse_index_row(fields, row)
        assert d["code"] == "sh.000001"
        assert d["close"] == 3040.0
        assert d["pct_chg"] == 1.33