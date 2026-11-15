"""初筛指标、过滤、排序测试（合成序列夹具，纯函数）。

对应验收要求 3：同一份输入稳定执行可复现的初筛规则。
"""
import datetime as dt

import pytest

from backend.screening.indicators import compute_indicators, market_environment
from backend.screening.filters import passes_filters
from backend.screening.ranker import prescreen, score_candidate


def make_bars(n=70, start_price=10.0, daily_ret=0.01, volume=1_000_000,
              amount=1.0e8, status=1, is_st=0, start="2026-08-01", code="sh.600000"):
    bars = []
    price = start_price
    d = dt.date.fromisoformat(start)
    for i in range(n):
        preclose = price
        close = round(price * (1 + daily_ret), 4)
        bars.append(dict(
            code=code, date=d.isoformat(), open=preclose, high=close * 1.01,
            low=preclose * 0.99, close=close, preclose=preclose,
            volume=volume, amount=amount, turn=0.5, trade_status=status,
            pct_chg=round(daily_ret * 100, 4), pe_ttm=10.0, pb_mrq=1.0, is_st=is_st,
        ))
        price = close
        d += dt.timedelta(days=1)
    return bars


class TestIndicators:
    def test_uptrend(self):
        ind = compute_indicators(make_bars(daily_ret=0.01))
        assert ind is not None
        assert ind["ret_5d"] > 0
        assert ind["ret_20d"] > 0
        assert ind["above_ma20"] is True
        assert ind["bars_count"] == 70
        assert ind["traded_today"] is True

    def test_ma20_value(self):
        bars = make_bars(daily_ret=0.0)  # 价格恒定 10
        ind = compute_indicators(bars)
        assert ind["ma20"] == pytest.approx(10.0, abs=1e-6)
        assert ind["ret_5d"] == pytest.approx(0.0, abs=1e-6)

    def test_insufficient_bars_returns_none(self):
        assert compute_indicators(make_bars(n=30), min_bars=60) is None

    def test_volume_ratio(self):
        bars = make_bars(volume=1_000_000)
        bars[-1]["volume"] = 3_000_000  # 今日放量3倍
        ind = compute_indicators(bars)
        assert ind["vol_ratio"] == pytest.approx(3.0, abs=0.01)

    def test_suspended_today(self):
        bars = make_bars()
        bars[-1]["trade_status"] = 0
        bars[-1]["volume"] = 0
        ind = compute_indicators(bars)
        assert ind["traded_today"] is False

    def test_volatility_positive(self):
        ind = compute_indicators(make_bars(daily_ret=0.02))
        assert ind["volatility_20d"] >= 0


class TestMarketEnv:
    def test_strong(self):
        env = market_environment(make_bars(daily_ret=0.01))
        assert env["regime"] == "strong"
        assert env["above_ma20"] is True

    def test_weak(self):
        env = market_environment(make_bars(daily_ret=-0.01))
        assert env["regime"] == "weak"

    def test_flat_neutral(self):
        env = market_environment(make_bars(daily_ret=0.0))
        assert env["regime"] == "neutral"


class TestFilters:
    def _meta(self, status="1"):
        return dict(status=status, industry="银行")

    def test_valid_passes(self):
        ind = compute_indicators(make_bars())
        ok, reason = passes_filters(ind, self._meta(), "2026-10-09",
                                    min_history=60, min_avg_amount=5e7,
                                    min_price=2.0, exclude_st=True)
        assert ok is True, reason

    def test_st_excluded(self):
        ind = compute_indicators(make_bars(is_st=1))
        ok, reason = passes_filters(ind, self._meta(), ind["last_date"],
                                    exclude_st=True)
        assert ok is False and "ST" in reason

    def test_suspended_excluded(self):
        bars = make_bars()
        bars[-1]["trade_status"] = 0
        bars[-1]["volume"] = 0
        ind = compute_indicators(bars)
        ok, reason = passes_filters(ind, self._meta(), ind["last_date"])
        assert ok is False and "停牌" in reason

    def test_low_liquidity_excluded(self):
        ind = compute_indicators(make_bars(amount=1e6))
        ok, reason = passes_filters(ind, self._meta(), ind["last_date"],
                                    min_avg_amount=5e7)
        assert ok is False and "流动性" in reason

    def test_stale_date_excluded(self):
        ind = compute_indicators(make_bars())
        ok, reason = passes_filters(ind, self._meta(), "2026-10-10")
        assert ok is False and "当日" in reason

    def test_delisted_excluded(self):
        ind = compute_indicators(make_bars())
        ok, reason = passes_filters(ind, self._meta(status="0"), ind["last_date"])
        assert ok is False

    def test_none_indicators_excluded(self):
        ok, reason = passes_filters(None, self._meta(), "2026-10-09")
        assert ok is False


class TestRanker:
    def _cand(self, code, ret, amount=1e8):
        ind = compute_indicators(make_bars(daily_ret=ret, amount=amount, code=code))
        return dict(code=code, name=code, indicators=ind, industry_rs=0.0)

    def test_deterministic(self):
        cands = [self._cand("sh.600000", 0.01), self._cand("sz.000001", 0.02),
                 self._cand("sz.300750", 0.005)]
        env = dict(regime="neutral")
        a = prescreen(cands, 10, env)
        b = prescreen(cands, 10, env)
        assert [x["code"] for x in a] == [x["code"] for x in b]

    def test_higher_momentum_ranks_first(self):
        cands = [self._cand("sh.600000", 0.001), self._cand("sz.000001", 0.03)]
        res = prescreen(cands, 10, dict(regime="neutral"))
        assert res[0]["code"] == "sz.000001"

    def test_count_limit(self):
        cands = [self._cand(f"sh.60000{i}", 0.01) for i in range(10)]
        res = prescreen(cands, 3, dict(regime="neutral"))
        assert len(res) == 3

    def test_score_range(self):
        c = self._cand("sh.600000", 0.01)
        s = score_candidate(c, dict(regime="neutral"))
        assert 0.0 <= s <= 1.0