"""AI 选股编排与输出校验测试。

对应验收要求 4/5：AI 形成有依据的结论、保存原始记录；
权重由 Python 钳制（≤20%），价格由 Python 填充（不让 AI 编造）。
"""
import pytest

from backend.ai_analysis.stock_pick import (
    build_payload,
    pick_stocks,
    validate_picks,
)


def _cand(code="sh.600000", name="浦发银行"):
    return {
        "code": code, "name": name, "industry": "银行", "score": 0.7,
        "industry_rs": 0.02,
        "indicators": {
            "close": 10.0, "last_date": "2026-11-09", "ret_5d": 0.05,
            "ret_20d": 0.10, "vol_ratio": 2.0, "above_ma20": True,
            "avg_amount_20d": 1e8, "volatility_20d": 0.03,
            "pe_ttm": 5.0, "pb_mrq": 0.6,
        },
    }


def _pick(code="sh.600000", action="buy_candidate", weight=0.15):
    return {
        "code": code, "action": action, "potential_level": "high",
        "suggested_weight": weight, "reason": "放量突破",
        "bull_logic": "行业景气", "bear_risks": "大盘回调",
        "horizon": "1-5个交易日", "buy_trigger": "次日开盘未涨停",
        "invalid_condition": "跌破10日线", "edge_vs_peers": "强于同业",
    }


class TestValidatePicks:
    def test_valid_pick_gets_price_from_candidate(self):
        cands = [_cand()]
        out = validate_picks({"picks": [_pick()]}, cands, max_weight=0.20)
        p = out["picks"][0]
        assert p["code"] == "sh.600000"
        assert p["name"] == "浦发银行"
        assert p["ref_price"] == 10.0  # Python 填充，非 AI
        assert p["ref_price_time"] == "2026-11-09"
        assert p["suggested_weight"] == 0.15

    def test_weight_clamped_to_cap(self):
        out = validate_picks({"picks": [_pick(weight=0.9)]}, [_cand()], max_weight=0.20)
        assert out["picks"][0]["suggested_weight"] == 0.20

    def test_unknown_code_dropped(self):
        out = validate_picks({"picks": [_pick(code="sh.999999")]}, [_cand()], 0.20)
        assert out["picks"] == []

    def test_watch_weight_zero(self):
        out = validate_picks({"picks": [_pick(action="watch", weight=0.3)]},
                             [_cand()], 0.20)
        assert out["picks"][0]["suggested_weight"] == 0.0
        assert out["picks"][0]["action"] == "watch"

    def test_buy_candidates_trimmed_to_3(self):
        cands = [_cand(f"sh.60000{i}", f"股{i}") for i in range(5)]
        picks = [_pick(f"sh.60000{i}") for i in range(5)]
        out = validate_picks({"picks": picks}, cands, 0.20)
        buys = [p for p in out["picks"] if p["action"] == "buy_candidate"]
        assert len(buys) == 3

    def test_total_focus_trimmed_to_5(self):
        cands = [_cand(f"sh.60000{i}", f"股{i}") for i in range(8)]
        picks = [_pick(f"sh.60000{i}", action="watch") for i in range(8)]
        out = validate_picks({"picks": picks}, cands, 0.20)
        assert len(out["picks"]) == 5

    def test_empty_picks_allowed(self):
        out = validate_picks({"picks": [], "market_comment": "市场弱势空仓"},
                             [_cand()], 0.20)
        assert out["picks"] == []
        assert out["market_comment"] == "市场弱势空仓"

    def test_missing_required_field_raises(self):
        bad = _pick()
        del bad["bull_logic"]
        with pytest.raises(ValueError):
            validate_picks({"picks": [bad]}, [_cand()], 0.20)

    def test_invalid_action_raises(self):
        bad = _pick(action="strong_buy")
        with pytest.raises(ValueError):
            validate_picks({"picks": [bad]}, [_cand()], 0.20)

    def test_duplicate_code_deduped(self):
        out = validate_picks({"picks": [_pick(), _pick()]}, [_cand()], 0.20)
        assert len(out["picks"]) == 1


class TestBuildPayload:
    def test_includes_candidates_news_holdings(self):
        payload = build_payload(
            prescreen={"market_env": {"regime": "neutral"}, "candidates": [_cand()]},
            news_by_code={"sh.600000": [{"title": "回购", "sentiment": "positive"}]},
            market_news=[{"title": "央行降准", "sentiment": "positive"}],
            holdings=[{"code": "sz.000001", "weight": 0.1}],
            max_weight=0.20,
        )
        assert payload["candidates"][0]["code"] == "sh.600000"
        assert payload["news_by_code"]["sh.600000"][0]["title"] == "回购"
        assert payload["market_news"][0]["title"] == "央行降准"
        assert payload["holdings"][0]["code"] == "sz.000001"
        assert payload["max_position_weight"] == 0.20


class _StubClient:
    def __init__(self, output):
        self.output = output
        self.calls = []

    def chat_json(self, system, user, retries=1):
        self.calls.append((system, user))
        return self.output


class TestPickStocks:
    def test_end_to_end(self):
        client = _StubClient({"picks": [_pick()], "market_comment": "震荡市精选"})
        res = pick_stocks(client, {"candidates": [_cand()]}, [_cand()], max_weight=0.20)
        assert res["picks"][0]["ref_price"] == 10.0
        assert res["market_comment"] == "震荡市精选"
        assert res["raw"] == {"picks": [_pick()], "market_comment": "震荡市精选"}
        assert len(client.calls) == 1