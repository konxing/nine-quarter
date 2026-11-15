"""数据校验：异常数据不得进入筛选与模拟成交。

对应验收要求 2：数据异常时停止使用错误数据。
"""
from __future__ import annotations

import sqlite3

_PRICE_FIELDS = ("open", "high", "low", "close")


def _num(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def bar_errors(row: dict) -> list[str]:
    """检查单根日线 bar 的合理性，返回错误描述列表（空=通过）。

    停牌且无成交（trade_status=0, volume=0）允许价格为空。
    """
    errors: list[str] = []
    status = _num(row.get("trade_status"))
    volume = _num(row.get("volume"))
    amount = _num(row.get("amount"))
    prices = {f: _num(row.get(f)) for f in _PRICE_FIELDS}

    # 停牌且无成交：BaoStock 返回空价格/空成交量，属正常，直接放行。
    suspended = status == 0 and (volume is None or volume == 0)
    if suspended:
        if amount is not None and amount < 0:
            errors.append("amount 为负")
        return errors

    if status is None:
        errors.append("trade_status 缺失")
    if volume is None:
        errors.append("volume 缺失")
    elif volume < 0:
        errors.append("volume 为负")
    if amount is not None and amount < 0:
        errors.append("amount 为负")

    if any(p is None for p in prices.values()):
        errors.append("交易 bar 价格缺失")
        return errors
    if any(p <= 0 for p in prices.values()):
        errors.append("交易 bar 价格非正")
        return errors

    o, h, l, c = prices["open"], prices["high"], prices["low"], prices["close"]
    if h < l:
        errors.append(f"high({h}) < low({l})")
    if not (l - 1e-9 <= c <= h + 1e-9):
        errors.append(f"close({c}) 超出 [low,high]")
    if not (l - 1e-9 <= o <= h + 1e-9):
        errors.append(f"open({o}) 超出 [low,high]")
    if (volume or 0) <= 0:
        errors.append("交易状态正常但 volume<=0")
    return errors


def check_coverage(
    conn: sqlite3.Connection, date: str, min_coverage: float = 0.9
) -> tuple[bool, float, str]:
    """检查某日行情覆盖率：有当日 bar 的在市股票 / 全部在市股票。

    覆盖率不足 -> (False, ...)，调用方必须停止，不得用旧行情冒充当日。
    """
    active = conn.execute(
        "SELECT COUNT(*) AS n FROM stocks WHERE type='1' AND status='1'"
    ).fetchone()["n"]
    if active == 0:
        return False, 0.0, "股票池为空，无法校验覆盖率"
    have = conn.execute(
        "SELECT COUNT(DISTINCT b.code) AS n FROM daily_bars b "
        "JOIN stocks s ON s.code=b.code "
        "WHERE b.date=? AND s.type='1' AND s.status='1'",
        (date,),
    ).fetchone()["n"]
    cov = have / active
    ok = cov >= min_coverage
    detail = f"{date} 覆盖率 {have}/{active} = {cov:.2%}（阈值 {min_coverage:.0%}）"
    return ok, cov, detail