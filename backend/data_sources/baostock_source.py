"""BaoStock 数据源封装（行情/日历/股票池/行业）。

重要：baostock 的 ResultSet.get_data() 依赖 pandas.DataFrame.append，
在 pandas>=2.0 已失效。本模块一律用 rs.next()/get_row_data() 逐行读取。

BaoStock 为免费证券数据平台，个人非商业研究使用；匿名登录。
所有网络调用设置 socket 超时，失败抛 DataSourceError，绝不返回伪造数据。
"""
from __future__ import annotations

import socket
from contextlib import contextmanager

# 数值字段映射：baostock 字段名 -> 本系统字段名
_FLOAT_MAP = {
    "open": "open", "high": "high", "low": "low", "close": "close",
    "preclose": "preclose", "volume": "volume", "amount": "amount",
    "turn": "turn", "pctChg": "pct_chg", "peTTM": "pe_ttm",
    "pbMRQ": "pb_mrq", "psTTM": "ps_ttm", "pcfNcfTTM": "pcf_ncf_ttm",
}
_INT_MAP = {"tradestatus": "trade_status", "isST": "is_st"}

DAILY_FIELDS = (
    "date,code,open,high,low,close,preclose,volume,amount,adjustflag,"
    "turn,tradestatus,pctChg,peTTM,pbMRQ,isST"
)
INDEX_FIELDS = "date,code,open,high,low,close,preclose,volume,amount,pctChg"


class DataSourceError(RuntimeError):
    """数据源不可用或返回异常。调用方必须停止，不得用旧数据冒充。"""


def _to_float(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _to_int(v) -> int | None:
    f = _to_float(v)
    return int(f) if f is not None else None


def _parse_row(fields: list[str], row: list[str]) -> dict:
    raw = dict(zip(fields, row))
    out: dict = {"date": raw.get("date", ""), "code": raw.get("code", "")}
    for src, dst in _FLOAT_MAP.items():
        out[dst] = _to_float(raw.get(src))
    for src, dst in _INT_MAP.items():
        out[dst] = _to_int(raw.get(src))
    # 保证关键键存在（即便字段未请求）
    for k in ("open", "high", "low", "close", "preclose", "volume", "amount"):
        out.setdefault(k, None)
    out.setdefault("trade_status", None)
    out.setdefault("pct_chg", None)
    out.setdefault("is_st", 0)
    out.setdefault("pe_ttm", None)
    out.setdefault("pb_mrq", None)
    out.setdefault("turn", None)
    return out


def parse_daily_row(fields: list[str], row: list[str]) -> dict:
    return _parse_row(fields, row)


def parse_index_row(fields: list[str], row: list[str]) -> dict:
    return _parse_row(fields, row)


def _rows(rs) -> list[list[str]]:
    if rs.error_code != "0":
        raise DataSourceError(f"BaoStock 错误 {rs.error_code}: {rs.error_msg}")
    out = []
    while rs.next():
        out.append(rs.get_row_data())
    return out


class BaoStockSource:
    """上下文管理器：with BaoStockSource() as bs: ..."""

    def __init__(self, timeout: float = 30):
        self.timeout = timeout
        self._bs = None
        self._old_timeout = None

    def __enter__(self):
        import baostock as bs
        self._bs = bs
        self._old_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(self.timeout)
        lg = bs.login()
        if lg.error_code != "0":
            raise DataSourceError(f"BaoStock 登录失败: {lg.error_msg}")
        return self

    def __exit__(self, *exc):
        try:
            self._bs.logout()
        finally:
            socket.setdefaulttimeout(self._old_timeout)
        return False

    def trade_dates(self, start: str, end: str) -> list[tuple[str, int]]:
        rs = self._bs.query_trade_dates(start_date=start, end_date=end)
        return [(r[0], int(r[1])) for r in _rows(rs)]

    def stock_basic(self) -> list[dict]:
        rs = self._bs.query_stock_basic()
        fields = rs.fields
        out = []
        for r in _rows(rs):
            d = dict(zip(fields, r))
            out.append({
                "code": d.get("code", ""),
                "code_name": d.get("code_name", ""),
                "ipoDate": d.get("ipoDate", ""),
                "outDate": d.get("outDate", ""),
                "type": d.get("type", ""),
                "status": d.get("status", ""),
            })
        return out

    def industry(self) -> list[dict]:
        rs = self._bs.query_stock_industry()
        fields = rs.fields
        out = []
        for r in _rows(rs):
            d = dict(zip(fields, r))
            out.append({
                "code": d.get("code", ""),
                "industry": d.get("industry", ""),
                "industryClassification": d.get("industryClassification", ""),
            })
        return out

    def daily(self, code: str, start: str, end: str) -> list[dict]:
        rs = self._bs.query_history_k_data_plus(
            code, DAILY_FIELDS, start_date=start, end_date=end,
            frequency="d", adjustflag="3")  # 不复权：涨跌停/收益以真实价格为准
        fields = rs.fields
        return [parse_daily_row(fields, r) for r in _rows(rs)]

    def index_daily(self, code: str, start: str, end: str) -> list[dict]:
        rs = self._bs.query_history_k_data_plus(
            code, INDEX_FIELDS, start_date=start, end_date=end,
            frequency="d", adjustflag="3")
        fields = rs.fields
        return [parse_index_row(fields, r) for r in _rows(rs)]