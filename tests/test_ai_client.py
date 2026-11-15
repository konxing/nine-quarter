"""AI 客户端测试：JSON 解析（纯函数）+ 接口失效处理（httpx MockTransport）。

对应测试要求：AI 接口失效时系统不得伪造结论。
"""
import json

import httpx
import pytest

from backend.ai_analysis.client import AIClient, AIError, extract_json


class TestExtractJson:
    def test_plain_object(self):
        assert extract_json('{"a": 1}') == {"a": 1}

    def test_code_fence(self):
        assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}

    def test_surrounding_text(self):
        assert extract_json('好的，结果如下：{"a": 1} 希望有帮助') == {"a": 1}

    def test_array(self):
        assert extract_json('[{"a": 1}]') == [{"a": 1}]

    def test_nested_braces_in_string(self):
        assert extract_json('{"a": "x}y"}') == {"a": "x}y"}

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            extract_json("完全不是 JSON")


def _client_with(handler, **kw):
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    defaults = dict(base_url="https://api.test/v1", api_key="sk-test",
                    model="test-model", http_client=http_client)
    defaults.update(kw)
    return AIClient(**defaults)


def _ok_handler(content):
    def handler(request):
        body = json.loads(request.content)
        assert body["model"] == "test-model"
        assert request.headers["Authorization"] == "Bearer sk-test"
        return httpx.Response(200, json={
            "choices": [{"message": {"content": content}}]})
    return handler


class TestAIClient:
    def test_missing_key_raises(self):
        c = AIClient(base_url="https://api.test/v1", api_key="", model="m")
        with pytest.raises(AIError):
            c.chat("sys", "user")

    def test_chat_json_success(self):
        c = _client_with(_ok_handler('{"picks": []}'))
        assert c.chat_json("sys", "user") == {"picks": []}

    def test_http_error_raises_aierror(self):
        c = _client_with(lambda req: httpx.Response(500, text="server error"))
        with pytest.raises(AIError):
            c.chat("sys", "user")

    def test_timeout_raises_aierror(self):
        def handler(req):
            raise httpx.ReadTimeout("timeout", request=req)
        c = _client_with(handler)
        with pytest.raises(AIError):
            c.chat("sys", "user")

    def test_invalid_json_retries_then_raises(self):
        calls = {"n": 0}
        def handler(req):
            calls["n"] += 1
            return httpx.Response(200, json={
                "choices": [{"message": {"content": "不是JSON"}}]})
        c = _client_with(handler)
        with pytest.raises(AIError):
            c.chat_json("sys", "user", retries=1)
        assert calls["n"] == 2  # 初次 + 1 次重试

    def test_invalid_then_valid_succeeds(self):
        seq = ["坏响应", '{"ok": true}']
        def handler(req):
            return httpx.Response(200, json={
                "choices": [{"message": {"content": seq.pop(0)}}]})
        c = _client_with(handler)
        assert c.chat_json("sys", "user", retries=1) == {"ok": True}