"""模拟交易规则测试：涨跌停、交易单位、费用、T+1、成交判定。

这些测试对应验收要求 6/7：模拟买卖必须遵守 A 股规则，
且 conservative（无法确认成交时不得虚构成交）。
"""
from decimal import Decimal

import pytest

from backend.simulation.rules import (
    can_sell_t1,
    fill_check_buy,
    fill_check_sell,
    limit_prices,
    price_limit_pct,
    round_buy_shares,
    trade_costs,
)


class TestPriceLimits:
    def test_main_board_10pct(self):
        assert price_limit_pct("sh.600000", is_st=False) == 0.10
        assert price_limit_pct("sz.000001", is_st=False) == 0.10

    def test_chinext_and_star_20pct(self):
        assert price_limit_pct("sz.300750", is_st=False) == 0.20
        assert price_limit_pct("sz.301001", is_st=False) == 0.20
        assert price_limit_pct("sh.688981", is_st=False) == 0.20

    def test_st_5pct(self):
        assert price_limit_pct("sh.600000", is_st=True) == 0.05

    def test_limit_price_round_half_up(self):
        # 10.05 * 1.1 = 11.055 -> 四舍五入 11.06（不是银行家舍入 11.05）
        upper, lower = limit_prices("sh.600000", preclose=10.05, is_st=False)
        assert upper == 11.06
        assert lower == 9.05  # 10.05*0.9=9.045 -> 9.05

    def test_limit_price_normal(self):
        upper, lower = limit_prices("sz.300750", preclose=100.0, is_st=False)
        assert upper == 120.0
        assert lower == 80.0


class TestLotSize:
    def test_main_board_100_multiples(self):
        assert round_buy_shares("sh.600000", 1234) == 1200
        assert round_buy_shares("sz.000001", 99) == 0
        assert round_buy_shares("sz.300750", 1050) == 1000

    def test_star_market_min_200_then_1_share(self):
        assert round_buy_shares("sh.688981", 199) == 0
        assert round_buy_shares("sh.688981", 200) == 200
        assert round_buy_shares("sh.688981", 251) == 251


class TestTradeCosts:
    def test_buy_small_amount_min_commission(self):
        c = trade_costs(10000.0, "buy")
        assert c["commission"] == 5.0  # 万2.5=2.5 不足最低5元
        assert c["stamp_tax"] == 0.0  # 买入无印花税
        assert c["transfer_fee"] == pytest.approx(0.1)
        assert c["total"] == pytest.approx(5.1)

    def test_sell_has_stamp_tax(self):
        c = trade_costs(10000.0, "sell")
        assert c["commission"] == 5.0
        assert c["stamp_tax"] == 5.0  # 卖出 0.05%
        assert c["transfer_fee"] == pytest.approx(0.1)

    def test_large_amount_commission_above_min(self):
        c = trade_costs(100000.0, "buy")
        assert c["commission"] == 25.0

    def test_zero_amount_no_cost(self):
        c = trade_costs(0.0, "buy")
        assert c["total"] == 0.0


class TestT1:
    def test_cannot_sell_same_day(self):
        assert can_sell_t1("2026-11-09", "2026-11-09") is False

    def test_can_sell_next_trading_day(self):
        assert can_sell_t1("2026-11-09", "2026-11-10") is True

    def test_sell_before_buy_rejected(self):
        assert can_sell_t1("2026-11-10", "2026-11-09") is False


def _bar(**kw):
    base = dict(
        open=10.0, high=10.5, low=9.8, close=10.2, preclose=10.0,
        volume=1_000_000, trade_status=1,
    )
    base.update(kw)
    return base


class TestFillBuy:
    def test_normal_bar_fills_at_open(self):
        ok, price, reason = fill_check_buy("sh.600000", _bar(), is_st=False)
        assert ok is True
        assert price == 10.0
        assert reason == ""

    def test_suspended_not_fillable(self):
        ok, price, reason = fill_check_buy(
            "sh.600000", _bar(trade_status=0, volume=0), is_st=False)
        assert ok is False
        assert "停牌" in reason

    def test_open_at_limit_up_not_fillable(self):
        # 开盘即涨停（盘中曾打开也保守视为无法确认成交）
        ok, _, reason = fill_check_buy(
            "sh.600000", _bar(open=11.0, high=11.0, low=10.6), is_st=False)
        assert ok is False
        assert "涨停" in reason

    def test_one_word_limit_up_not_fillable(self):
        ok, _, reason = fill_check_buy(
            "sh.600000", _bar(open=11.0, high=11.0, low=11.0, close=11.0),
            is_st=False)
        assert ok is False

    def test_one_word_board_not_fillable(self):
        ok, _, _ = fill_check_buy(
            "sh.600000", _bar(open=10.0, high=10.0, low=10.0, close=10.0),
            is_st=False)
        assert ok is False

    def test_chinext_limit_20pct(self):
        ok, price, _ = fill_check_buy(
            "sz.300750", _bar(preclose=10.0, open=11.5, high=12.0, low=11.0),
            is_st=False)
        assert ok is True  # 11.5 未到 20% 涨停 12.0
        assert price == 11.5


class TestFillSell:
    def test_normal_bar_fills_at_open(self):
        ok, price, _ = fill_check_sell("sh.600000", _bar(), is_st=False)
        assert ok is True
        assert price == 10.0

    def test_suspended_not_fillable(self):
        ok, _, reason = fill_check_sell(
            "sh.600000", _bar(trade_status=0), is_st=False)
        assert ok is False
        assert "停牌" in reason

    def test_open_at_limit_down_not_fillable(self):
        ok, _, reason = fill_check_sell(
            "sh.600000", _bar(open=9.0, high=9.4, low=9.0), is_st=False)
        assert ok is False
        assert "跌停" in reason

    def test_one_word_limit_down_not_fillable(self):
        ok, _, _ = fill_check_sell(
            "sh.600000", _bar(open=9.0, high=9.0, low=9.0, close=9.0),
            is_st=False)
        assert ok is False