"""AI 选股编排：构造紧凑 payload -> 调用 AI -> 校验/钳制输出 -> 填充真实价格。

价格、名称、指标均由 Python 从真实数据填充；AI 只做研究判断。
"""
from __future__ import annotations

from .prompts import PICK_SYSTEM, build_user_prompt

_REQUIRED_TEXT = ("reason", "bull_logic", "bear_risks", "horizon",
                  "buy_trigger", "invalid_condition", "edge_vs_peers")
_ACTIONS = {"buy_candidate", "watch"}
_LEVELS = {"high", "medium", "low"}
MAX_FOCUS = 5
MAX_BUY = 3


def build_payload(prescreen: dict, news_by_code: dict, market_news: list,
                  holdings: list, max_weight: float) -> dict:
    """压缩候选信息，控制 Token。每只候选只带关键指标与相关消息。"""
    cands = []
    for c in prescreen.get("candidates", []):
        ind = c.get("indicators", {})
        cands.append({
            "code": c["code"], "name": c.get("name", ""),
            "industry": c.get("industry", ""), "screen_score": c.get("score"),
            "industry_rs": c.get("industry_rs", 0.0),
            "close": ind.get("close"), "ret_5d": ind.get("ret_5d"),
            "ret_20d": ind.get("ret_20d"), "vol_ratio": ind.get("vol_ratio"),
            "above_ma20": ind.get("above_ma20"),
            "avg_amount_20d": ind.get("avg_amount_20d"),
            "volatility_20d": ind.get("volatility_20d"),
            "pe_ttm": ind.get("pe_ttm"), "pb_mrq": ind.get("pb_mrq"),
        })
    return {
        "market_env": prescreen.get("market_env", {}),
        "max_position_weight": max_weight,
        "candidates": cands,
        "news_by_code": news_by_code,
        "market_news": market_news,
        "holdings": holdings,
    }


def validate_picks(ai_output: dict, candidates: list[dict],
                   max_weight: float) -> dict:
    """校验 AI 输出：白名单代码、必填字段、权重钳制、数量约束、价格由系统填充。"""
    if not isinstance(ai_output, dict):
        raise ValueError("AI 选股输出不是 JSON 对象")
    raw_picks = ai_output.get("picks", [])
    if not isinstance(raw_picks, list):
        raise ValueError("picks 不是数组")
    cand_map = {c["code"]: c for c in candidates}
    seen: set[str] = set()
    validated: list[dict] = []
    for p in raw_picks:
        if not isinstance(p, dict):
            raise ValueError("pick 元素不是对象")
        code = p.get("code")
        if code not in cand_map:
            continue  # 非候选股，丢弃（不编造）
        if code in seen:
            continue
        action = p.get("action")
        if action not in _ACTIONS:
            raise ValueError(f"非法 action: {action}")
        for f in _REQUIRED_TEXT:
            if not p.get(f):
                raise ValueError(f"缺少必填字段 {f}（{code}）")
        level = p.get("potential_level", "medium")
        if level not in _LEVELS:
            level = "medium"
        weight = float(p.get("suggested_weight", 0.0) or 0.0)
        weight = max(0.0, min(weight, max_weight))
        if action == "watch":
            weight = 0.0
        cand = cand_map[code]
        ind = cand.get("indicators", {})
        seen.add(code)
        validated.append({
            "code": code, "name": cand.get("name", ""), "action": action,
            "potential_level": level, "suggested_weight": round(weight, 4),
            "ref_price": ind.get("close"), "ref_price_time": ind.get("last_date"),
            "reason": p["reason"], "bull_logic": p["bull_logic"],
            "bear_risks": p["bear_risks"], "horizon": p["horizon"],
            "buy_trigger": p["buy_trigger"], "invalid_condition": p["invalid_condition"],
            "edge_vs_peers": p["edge_vs_peers"],
        })
    # 数量约束：买入候选≤3（超出者降级为观察），总关注≤5（保持 AI 优先顺序）
    buys = [p for p in validated if p["action"] == "buy_candidate"][:MAX_BUY]
    buy_codes = {p["code"] for p in buys}
    adjusted = []
    for p in validated:
        if p["action"] == "buy_candidate" and p["code"] not in buy_codes:
            p = dict(p, action="watch", suggested_weight=0.0)
        adjusted.append(p)
    trimmed = adjusted[:MAX_FOCUS]
    return {
        "picks": trimmed,
        "market_comment": str(ai_output.get("market_comment", "")),
    }


def pick_stocks(client, payload: dict, candidates: list[dict],
                max_weight: float) -> dict:
    """调用 AI 并校验。返回 {picks, market_comment, raw}。AIError 由调用方处理。"""
    raw = client.chat_json(PICK_SYSTEM, build_user_prompt(payload), retries=1)
    result = validate_picks(raw, candidates, max_weight)
    result["raw"] = raw
    return result