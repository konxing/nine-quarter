"""初筛过滤规则：透明、可配置。返回 (是否通过, 原因)。"""
from __future__ import annotations


def passes_filters(
    ind: dict | None,
    meta: dict,
    expected_date: str,
    min_history: int = 60,
    min_avg_amount: float = 5e7,
    min_price: float = 2.0,
    exclude_st: bool = True,
) -> tuple[bool, str]:
    if ind is None:
        return False, "指标缺失或历史数据不足"
    if str(meta.get("status", "1")) != "1":
        return False, "非在市或已退市"
    if ind["bars_count"] < min_history:
        return False, f"历史数据不足（{ind['bars_count']}<{min_history}）"
    if ind["last_date"] != expected_date:
        return False, f"数据非当日（{ind['last_date']}!={expected_date}）"
    if not ind["traded_today"]:
        return False, "停牌或当日无成交"
    if exclude_st and ind["is_st"]:
        return False, "ST 高风险股票"
    if ind["close"] < min_price:
        return False, f"低价股（<{min_price}元）"
    if ind["avg_amount_20d"] < min_avg_amount:
        return False, "流动性不足（20日均成交额过低）"
    return True, ""