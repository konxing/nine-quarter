"""仓位计划：把 AI 建议权重/持仓建议转成可执行模拟订单（股数由 Python 计算）。"""
from __future__ import annotations

from .rules import round_buy_shares


def plan_buy(pick: dict, total_assets: float, cash: float,
             max_weight: float, held_value: float = 0.0) -> dict | None:
    weight = min(float(pick.get("suggested_weight", 0.0)), max_weight)
    price = float(pick.get("ref_price") or 0.0)
    if weight <= 0 or price <= 0 or total_assets <= 0:
        return None
    # 单只股票总仓位上限：已持有市值计入，只补剩余空间，避免重复加仓超限
    room = max_weight * total_assets - held_value
    if room <= 0:
        return None
    alloc = min(weight * total_assets, room, cash)
    shares = round_buy_shares(pick["code"], int(alloc / price))
    if shares <= 0:
        return None
    return {
        "code": pick["code"], "name": pick.get("name", ""), "side": "buy",
        "target_weight": round(weight, 4), "planned_shares": shares,
        "ref_price": price, "reason": pick.get("reason", ""),
    }


def plan_sell(code: str, name: str, action: str, held_shares: int,
              reason: str) -> dict | None:
    if action not in ("sell", "reduce") or held_shares <= 0:
        return None
    shares = held_shares if action == "sell" else (held_shares // 2)
    # 减仓至少卖出一手（100）或全部（不足一手时）
    if action == "reduce" and shares < 100:
        shares = min(100, held_shares)
    if shares <= 0:
        return None
    return {
        "code": code, "name": name, "side": "sell", "target_weight": 0.0,
        "planned_shares": shares, "ref_price": 0.0, "reason": reason,
    }