"""初筛：透明、可计算、可复现的技术指标与市场环境判定。

全部为纯函数，输入日线序列输出指标字典。收益用 BaoStock pctChg
（已正确处理除权除息），均线用不复权收盘价。
"""
from __future__ import annotations

import math


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _std(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def _cum_ret(rets: list[float], n: int) -> float:
    seg = rets[-n:] if n else rets
    p = 1.0
    for r in seg:
        p *= (1 + r)
    return p - 1


def compute_indicators(bars: list[dict], min_bars: int = 60) -> dict | None:
    """由日线序列计算指标。有效（有收盘价）bar 不足 min_bars 返回 None。"""
    if not bars:
        return None
    sb = sorted(bars, key=lambda b: b["date"])
    last = sb[-1]
    valid = [b for b in sb if b.get("close") is not None and b["close"] > 0]
    if len(valid) < min_bars:
        return None
    closes = [b["close"] for b in valid]
    rets: list[float] = []
    for i in range(1, len(valid)):
        pc = valid[i].get("pct_chg")
        if pc is not None:
            rets.append(pc / 100.0)
        else:
            prev = valid[i - 1]["close"]
            rets.append(closes[i] / prev - 1 if prev else 0.0)
    vols = [b.get("volume") or 0 for b in valid]
    amounts = [b.get("amount") or 0 for b in valid]
    ma5, ma10, ma20, ma60 = (_mean(closes[-n:]) for n in (5, 10, 20, 60))
    prev5_vol = _mean(vols[-6:-1]) if len(vols) >= 6 else _mean(vols[:-1])
    vol_ratio = (vols[-1] / prev5_vol) if prev5_vol else 0.0
    last_status = last.get("trade_status")
    last_vol = last.get("volume") or 0
    return {
        "last_date": last["date"],
        "close": closes[-1],
        "bars_count": len(valid),
        "ret_1d": rets[-1] if rets else 0.0,
        "ret_5d": _cum_ret(rets, 5),
        "ret_10d": _cum_ret(rets, 10),
        "ret_20d": _cum_ret(rets, 20),
        "ret_60d": _cum_ret(rets, 60),
        "ma5": ma5, "ma10": ma10, "ma20": ma20, "ma60": ma60,
        "above_ma20": closes[-1] > ma20,
        "vol_ratio": vol_ratio,
        "avg_amount_20d": _mean(amounts[-20:]),
        "volatility_20d": _std(rets[-20:]),
        "traded_today": last_status == 1 and last_vol > 0,
        "is_st": int(last.get("is_st") or 0),
        "turn": last.get("turn"),
        "pe_ttm": last.get("pe_ttm"),
        "pb_mrq": last.get("pb_mrq"),
    }


def market_environment(index_bars: list[dict]) -> dict:
    """由指数日线判定市场环境：strong/neutral/weak。"""
    ind = compute_indicators(index_bars, min_bars=20)
    if ind is None:
        return {"regime": "neutral", "above_ma20": False, "ret_5d": 0.0,
                "close": None, "ma20": None}
    above = ind["above_ma20"]
    r5 = ind["ret_5d"]
    if above and r5 > 0:
        regime = "strong"
    elif (not above) and r5 < 0:
        regime = "weak"
    else:
        regime = "neutral"
    return {"regime": regime, "above_ma20": above, "ret_5d": r5,
            "close": ind["close"], "ma20": ind["ma20"]}