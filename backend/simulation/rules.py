"""A 股模拟交易规则（纯函数，便于测试与复现）。

约定：
- 价格单位：元；股数单位：股。
- 涨跌停价按交易所四舍五入到分（Decimal ROUND_HALF_UP）。
- 成交判定保守：无法确认能成交时一律视为不可成交，保留未成交订单。
- 费用默认：佣金万2.5（最低5元）、印花税卖出0.05%、过户费0.001%双边。
  实际数值从配置注入，默认值见 trade_costs 参数。
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP


def _code_num(code: str) -> str:
    """'sh.600000' -> '600000'；兼容纯数字代码。"""
    return code.split(".")[-1]


def price_limit_pct(code: str, is_st: bool = False) -> float:
    """证券适用涨跌幅比例。

    主板 10%；创业板 300/301、科创板 688/689 20%；ST/*ST 5%。
    北交所（8xx/4xx/920）30%（本系统数据源暂不覆盖，仅规则预留）。
    """
    num = _code_num(code)
    if is_st:
        return 0.05
    if num.startswith(("300", "301", "688", "689")):
        return 0.20
    if num.startswith(("83", "87", "88", "43", "92")):
        return 0.30
    return 0.10


def _round2(x: float | Decimal) -> float:
    return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def limit_prices(code: str, preclose: float, is_st: bool = False) -> tuple[float, float]:
    """返回 (涨停价, 跌停价)。"""
    pct = price_limit_pct(code, is_st)
    upper = _round2(Decimal(str(preclose)) * (1 + Decimal(str(pct))))
    lower = _round2(Decimal(str(preclose)) * (1 - Decimal(str(pct))))
    return upper, lower


def round_buy_shares(code: str, shares: int | float) -> int:
    """按交易单位取整买入股数。

    主板/创业板：100 股整数倍。
    科创板：最低 200 股，超过部分可 1 股递增。
    不足最低单位返回 0（不买）。
    """
    shares = int(shares)
    num = _code_num(code)
    if num.startswith(("688", "689")):
        return shares if shares >= 200 else 0
    return (shares // 100) * 100


def trade_costs(
    amount: float,
    side: str,
    commission_rate: float = 0.00025,
    min_commission: float = 5.0,
    stamp_tax_rate: float = 0.0005,
    transfer_fee_rate: float = 0.00001,
) -> dict:
    """计算交易费用。amount 为成交金额（元），side 为 buy/sell。"""
    if amount <= 0:
        return {"commission": 0.0, "stamp_tax": 0.0, "transfer_fee": 0.0, "total": 0.0}
    commission = max(amount * commission_rate, min_commission)
    stamp_tax = amount * stamp_tax_rate if side == "sell" else 0.0
    transfer_fee = amount * transfer_fee_rate
    return {
        "commission": round(commission, 2),
        "stamp_tax": round(stamp_tax, 2),
        "transfer_fee": round(transfer_fee, 2),
        "total": round(commission + stamp_tax + transfer_fee, 2),
    }


def can_sell_t1(buy_date: str, sell_date: str) -> bool:
    """T+1：买入当日不可卖出，次一交易日起可卖。

    入参均为交易日（YYYY-MM-DD）。跨节假日由交易日历保证：
    只要 sell_date 是晚于 buy_date 的交易日即可。
    """
    return sell_date > buy_date


def _at_or_beyond(price: float, limit: float) -> bool:
    return price >= limit - 1e-9


def _at_or_below(price: float, limit: float) -> bool:
    return price <= limit + 1e-9


def fill_check_buy(code: str, bar: dict, is_st: bool = False) -> tuple[bool, float, str]:
    """判断次日开盘买入是否可确认成交。

    bar 需含 open/high/low/close/preclose/volume/trade_status。
    返回 (可成交, 成交价, 原因)。成交价=开盘价（次日最早可得价格，无未来信息）。
    保守规则：停牌、开盘即涨停、一字板 -> 不可成交。
    """
    if int(bar.get("trade_status", 1)) != 1 or float(bar.get("volume", 0)) <= 0:
        return False, 0.0, "停牌或无成交"
    o, h, l = float(bar["open"]), float(bar["high"]), float(bar["low"])
    if h <= l + 1e-9:
        return False, 0.0, "一字板无法确认成交"
    upper, _ = limit_prices(code, float(bar["preclose"]), is_st)
    if _at_or_beyond(o, upper):
        return False, 0.0, "开盘涨停无法确认买入成交"
    return True, o, ""


def fill_check_sell(code: str, bar: dict, is_st: bool = False) -> tuple[bool, float, str]:
    """判断次日开盘卖出是否可确认成交。

    保守规则：停牌、开盘即跌停、一字板 -> 不可成交。
    """
    if int(bar.get("trade_status", 1)) != 1 or float(bar.get("volume", 0)) <= 0:
        return False, 0.0, "停牌或无成交"
    o, h, l = float(bar["open"]), float(bar["high"]), float(bar["low"])
    if h <= l + 1e-9:
        return False, 0.0, "一字板无法确认成交"
    _, lower = limit_prices(code, float(bar["preclose"]), is_st)
    if _at_or_below(o, lower):
        return False, 0.0, "开盘跌停无法确认卖出成交"
    return True, o, ""