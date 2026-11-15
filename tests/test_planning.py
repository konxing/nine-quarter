"""仓位计划测试：由 AI 建议权重生成模拟买入计划（Python 计算股数）。"""
from backend.simulation.planning import plan_buy, plan_sell


class TestPlanBuy:
    def test_basic_lot_rounding(self):
        pick = {"code": "sh.600000", "name": "浦发", "suggested_weight": 0.15,
                "ref_price": 10.0, "reason": "看好"}
        p = plan_buy(pick, total_assets=100000, cash=100000, max_weight=0.20)
        # 0.15×100000=15000 /10 =1500 股
        assert p["planned_shares"] == 1500
        assert p["target_weight"] == 0.15
        assert p["side"] == "buy"

    def test_weight_clamped(self):
        pick = {"code": "sh.600000", "name": "x", "suggested_weight": 0.5,
                "ref_price": 10.0, "reason": "r"}
        p = plan_buy(pick, 100000, 100000, 0.20)
        assert p["target_weight"] == 0.20
        assert p["planned_shares"] == 2000

    def test_cash_constraint(self):
        pick = {"code": "sh.600000", "name": "x", "suggested_weight": 0.20,
                "ref_price": 10.0, "reason": "r"}
        p = plan_buy(pick, total_assets=100000, cash=5000, max_weight=0.20)
        assert p["planned_shares"] == 500  # 现金仅5000

    def test_existing_holding_reduces_remaining_room(self):
        """已持有 15% 时，再按 20% 建议买入只能补到 20% 上限（剩余 5%）。"""
        pick = {"code": "sh.600000", "name": "x", "suggested_weight": 0.20,
                "ref_price": 10.0, "reason": "r"}
        p = plan_buy(pick, 100000, 100000, 0.20, held_value=15000)
        assert p["planned_shares"] == 500

    def test_holding_at_limit_returns_none(self):
        pick = {"code": "sh.600000", "name": "x", "suggested_weight": 0.20,
                "ref_price": 10.0, "reason": "r"}
        assert plan_buy(pick, 100000, 100000, 0.20, held_value=20000) is None

    def test_star_min_200(self):
        pick = {"code": "sh.688981", "name": "x", "suggested_weight": 0.01,
                "ref_price": 10.0, "reason": "r"}
        # 0.01×100000=1000/10=100 <200 -> 科创板最低200需2000元；分配1000不足 -> None
        p = plan_buy(pick, 100000, 100000, 0.20)
        assert p is None

    def test_zero_weight_returns_none(self):
        pick = {"code": "sh.600000", "name": "x", "suggested_weight": 0.0,
                "ref_price": 10.0, "reason": "r"}
        assert plan_buy(pick, 100000, 100000, 0.20) is None

    def test_zero_price_returns_none(self):
        pick = {"code": "sh.600000", "name": "x", "suggested_weight": 0.1,
                "ref_price": 0, "reason": "r"}
        assert plan_buy(pick, 100000, 100000, 0.20) is None


class TestPlanSell:
    def test_sell_all(self):
        p = plan_sell("sh.600000", "浦发", action="sell", held_shares=1000, reason="止盈")
        assert p["planned_shares"] == 1000
        assert p["side"] == "sell"

    def test_reduce_half(self):
        p = plan_sell("sh.600000", "浦发", action="reduce", held_shares=1000, reason="减仓")
        assert p["planned_shares"] == 500

    def test_hold_returns_none(self):
        assert plan_sell("sh.600000", "x", action="hold", held_shares=1000, reason="") is None

    def test_no_position_returns_none(self):
        assert plan_sell("sh.600000", "x", action="sell", held_shares=0, reason="") is None