"""初筛排序：固定权重的透明 composite 评分，确定性可复现。

RULE_VERSION 变更即视为规则变更，需经历史验证方可正式采用（见复盘模块）。
评分仅用于缩小候选范围，最终判断由 AI 横向比较完成；
评分不是上涨概率，不得对外解释为概率。
"""
from __future__ import annotations

import math

RULE_VERSION = "screen-v1.0"

# 各分项权重（和为 1.0），公开可审计
WEIGHTS = {
    "mom5": 0.20, "mom20": 0.20, "volume": 0.15, "trend": 0.15,
    "industry_rs": 0.15, "liquidity": 0.10, "low_vol": 0.05,
}


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, x))


def score_candidate(cand: dict, market_env: dict) -> float:
    ind = cand["indicators"]
    ma60 = ind.get("ma60") or ind["close"]
    components = {
        "mom5": _clip01((ind["ret_5d"] + 0.10) / 0.30),
        "mom20": _clip01((ind["ret_20d"] + 0.15) / 0.50),
        "volume": _clip01((ind["vol_ratio"] - 0.5) / 3.0),
        "trend": 0.5 * (1.0 if ind["above_ma20"] else 0.0)
                 + 0.5 * _clip01((ind["close"] / ma60 - 1 + 0.10) / 0.30),
        "industry_rs": _clip01((cand.get("industry_rs", 0.0) + 0.10) / 0.20),
        "liquidity": _clip01(math.log10(max(ind["avg_amount_20d"], 1.0) / 1e7) / 2),
        "low_vol": _clip01((0.08 - ind["volatility_20d"]) / 0.06),
    }
    score = sum(WEIGHTS[k] * components[k] for k in WEIGHTS)
    # 弱市透明降权（风险规避），强市/震荡不调整
    if market_env.get("regime") == "weak":
        score *= 0.9
    return round(score, 6)


def prescreen(cands: list[dict], count: int, market_env: dict) -> list[dict]:
    """按评分降序取前 count；同分按代码升序，保证确定性。"""
    scored = []
    for c in cands:
        if c.get("indicators") is None:
            continue
        d = dict(c)
        d["score"] = score_candidate(c, market_env)
        scored.append(d)
    scored.sort(key=lambda d: (-d["score"], d["code"]))
    return scored[:count]