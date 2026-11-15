"""应用内 AI 配置：存 SQLite、掩码展示、保存即生效、连通测试不落库。"""
import json
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import ai_config
from backend.ai_analysis.client import AIError
from backend.ai_config import (
    apply_ai_overrides,
    load_ai_overrides,
    mask_key,
    probe_ai,
    save_ai_overrides,
)
from backend.config import Settings
from backend.db import SCHEMA, connect, init_db


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    yield c
    c.close()


@pytest.fixture
def client(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    monkeypatch.setenv("DB_PATH", str(db))
    init_db(db)
    import backend.api as api
    fresh = Settings(ai_base_url="", ai_api_key="", ai_model="")
    monkeypatch.setattr(api, "settings", fresh)
    app = FastAPI()
    app.include_router(api.router)
    with TestClient(app) as c:
        yield c


class TestStore:
    def test_save_load_apply_overrides_env(self, conn):
        save_ai_overrides(conn, "https://api.example.com/v1/", "ep-123", "sk-secret-123456")
        values = load_ai_overrides(conn)
        assert values["ai_base_url"] == "https://api.example.com/v1"
        assert values["ai_model"] == "ep-123"
        cfg = Settings(ai_base_url="https://env.example.com", ai_api_key="env-key",
                       ai_model="env-model")
        apply_ai_overrides(cfg, values)
        assert cfg.ai_base_url == "https://api.example.com/v1"
        assert cfg.ai_api_key == "sk-secret-123456"
        assert cfg.ai_model == "ep-123"

    def test_blank_key_keeps_previous(self, conn):
        save_ai_overrides(conn, "https://api.example.com/v1", "ep-1", "sk-first")
        save_ai_overrides(conn, "https://api.example.com/v1", "ep-2", "")
        values = load_ai_overrides(conn)
        assert values["ai_model"] == "ep-2"
        assert values["ai_api_key"] == "sk-first"

    def test_mask_never_exposes_full_key(self):
        assert mask_key("") == ""
        assert mask_key("short") == "****"
        assert mask_key("sk-1234567890") == "****7890"
        assert "1234567890" not in mask_key("sk-1234567890")

    def test_probe_uses_small_request(self, monkeypatch):
        captured = {}

        class FakeClient:
            def __init__(self, base_url, api_key, model, timeout, max_tokens):
                captured.update(base_url=base_url, api_key=api_key, model=model,
                                timeout=timeout, max_tokens=max_tokens)

            def chat(self, system, user):
                return "OK"

        monkeypatch.setattr(ai_config, "AIClient", FakeClient)
        assert probe_ai("https://api.example.com", "sk-x", "ep-1") == "OK"
        assert captured["model"] == "ep-1"
        assert captured["max_tokens"] <= 64
        assert captured["timeout"] <= 30


class TestAPI:
    def test_initial_state_unconfigured(self, client):
        d = client.get("/api/settings/ai").json()
        assert d["base_url"] == ""
        assert d["model"] == ""
        assert d["key_configured"] is False
        assert d["key_masked"] == ""
        assert d["source"] == "none"

    def test_save_persists_and_applies_immediately(self, client, monkeypatch):
        import backend.api as api
        res = client.post("/api/settings/ai", json={
            "base_url": "https://api.example.com/v1/",
            "model": "ep-999",
            "api_key": "sk-secret-abcdef",
        })
        assert res.status_code == 200
        d = res.json()
        assert d["base_url"] == "https://api.example.com/v1"
        assert d["model"] == "ep-999"
        assert d["key_configured"] is True
        assert d["key_masked"] == "****cdef"
        assert "sk-secret-abcdef" not in json.dumps(d, ensure_ascii=False)
        # 立即作用于全局配置对象，无需重启
        assert api.settings.ai_model == "ep-999"
        conn = connect(api.settings.db_path)
        row = conn.execute("SELECT value FROM app_settings WHERE key='ai_model'").fetchone()
        conn.close()
        assert row["value"] == "ep-999"

    def test_get_never_returns_full_key(self, client):
        client.post("/api/settings/ai", json={
            "base_url": "https://api.example.com", "model": "ep-1",
            "api_key": "sk-very-secret-9999"})
        body = client.get("/api/settings/ai").text
        assert "sk-very-secret-9999" not in body
        d = json.loads(body)
        assert d["key_configured"] is True
        assert d["source"] == "db"

    def test_requires_key_when_none_configured(self, client):
        res = client.post("/api/settings/ai", json={
            "base_url": "https://api.example.com", "model": "ep-1", "api_key": ""})
        assert res.status_code == 400

    def test_rejects_invalid_base_url(self, client):
        res = client.post("/api/settings/ai", json={
            "base_url": "ftp://api.example.com", "model": "ep-1", "api_key": "k"})
        assert res.status_code == 400

    def test_test_connection_success_and_failure(self, client, monkeypatch):
        import backend.api as api
        monkeypatch.setattr(api, "probe_ai", lambda *a, **k: "OK")
        ok = client.post("/api/settings/ai/test", json={
            "base_url": "https://api.example.com", "model": "ep-1", "api_key": "k"}).json()
        assert ok["ok"] is True
        assert "OK" in ok["message"]

        def _fail(*a, **k):
            raise AIError("401 未授权")
        monkeypatch.setattr(api, "probe_ai", _fail)
        bad = client.post("/api/settings/ai/test", json={
            "base_url": "https://api.example.com", "model": "ep-1", "api_key": "k"}).json()
        assert bad["ok"] is False
        assert "401" in bad["message"]
        # 测试连通不得把半成品配置写入数据库
        assert client.get("/api/settings/ai").json()["source"] == "none"

    def test_saved_config_enables_ai_client(self, conn):
        from backend.pipeline import make_client
        save_ai_overrides(conn, "https://api.example.com", "ep-1", "sk-x")
        cfg = Settings(ai_base_url="", ai_api_key="", ai_model="")
        apply_ai_overrides(cfg, load_ai_overrides(conn))
        assert make_client(cfg) is not None
