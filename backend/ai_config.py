"""应用内 AI 配置：存入本地 SQLite，保存后覆盖环境变量并立即生效。

优先级：本机保存的值 > .env/环境变量。API Key 只以掩码形式回传前端，
不写入日志；连通测试只做一次极小的 chat 请求，不落库。
"""
from __future__ import annotations

import sqlite3

from .ai_analysis.client import AIClient
from .config import Settings

AI_KEYS = ("ai_base_url", "ai_api_key", "ai_model")


def save_ai_overrides(conn: sqlite3.Connection, base_url: str, model: str,
                      api_key: str = "") -> None:
    """保存非空字段；api_key 为空时保留旧值（前端不必重复输入 Key）。"""
    values = {"ai_base_url": base_url.strip().rstrip("/"), "ai_model": model.strip()}
    if api_key and api_key.strip():
        values["ai_api_key"] = api_key.strip()
    for k, v in values.items():
        conn.execute(
            "INSERT INTO app_settings(key,value,updated_at) VALUES (?,?,datetime('now')) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
            "updated_at=excluded.updated_at", (k, v))
    conn.commit()


def load_ai_overrides(conn: sqlite3.Connection) -> dict[str, str]:
    rows = conn.execute(
        "SELECT key,value FROM app_settings WHERE key IN (?,?,?)", AI_KEYS)
    return {r["key"]: r["value"] for r in rows}


def apply_ai_overrides(cfg: Settings, values: dict[str, str]) -> None:
    for k, v in values.items():
        if k in AI_KEYS and v:
            setattr(cfg, k, v)


def mask_key(key: str) -> str:
    if not key:
        return ""
    return "****" + key[-4:] if len(key) > 8 else "****"


def probe_ai(base_url: str, api_key: str, model: str,
             proxy: str | None = None) -> str:
    """连通性测试：极小请求，成功返回模型回复片段；失败抛 AIError。"""
    kwargs = {"timeout": 20, "max_tokens": 32}
    if proxy:
        kwargs["proxy"] = proxy
    client = AIClient(base_url, api_key, model, **kwargs)
    return client.chat("你是连通性测试助手，只回复 OK。", "ping")[:80]
