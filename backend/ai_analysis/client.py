"""OpenAI 兼容 Chat Completions 客户端（httpx）。

支持自定义 base_url/model/api_key/参数（环境变量配置）。
JSON 输出防御式解析 + 失败重试；任何异常统一为 AIError，绝不返回伪造结果。
"""
from __future__ import annotations

import json
import re

import httpx


class AIError(RuntimeError):
    """AI 接口不可用或响应无法解析。"""


def extract_json(text: str):
    """从 AI 文本响应中提取 JSON 对象/数组（容忍代码围栏与前后缀文字）。"""
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s).strip()
    try:
        return json.loads(s)
    except (json.JSONDecodeError, ValueError):
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        start = s.find(opener)
        if start == -1:
            continue
        depth = 0
        instr = False
        esc = False
        for i in range(start, len(s)):
            ch = s[i]
            if instr:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    instr = False
            else:
                if ch == '"':
                    instr = True
                elif ch == opener:
                    depth += 1
                elif ch == closer:
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(s[start:i + 1])
                        except (json.JSONDecodeError, ValueError):
                            break
    raise ValueError("无法从 AI 响应解析 JSON")


class AIClient:
    def __init__(self, base_url: str, api_key: str, model: str,
                 temperature: float = 0.3, timeout: float = 180,
                 max_tokens: int = 8000, http_client: httpx.Client | None = None,
                 proxy: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        if http_client is not None:
            self._client = http_client
        else:
            # 不读取系统/环境代理（Windows 注册表代理值可能使 httpx 解析崩溃）；
            # 如需代理由 AI_PROXY 显式指定。
            kwargs = {"timeout": timeout, "trust_env": False}
            if proxy:
                kwargs["proxy"] = proxy
            self._client = httpx.Client(**kwargs)

    def chat(self, system: str, user: str) -> str:
        if not self.api_key or not self.base_url or not self.model:
            raise AIError("AI 配置缺失（需 AI_BASE_URL / AI_API_KEY / AI_MODEL）")
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        try:
            resp = self._client.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {self.api_key}",
                         "Content-Type": "application/json"},
            )
        except httpx.HTTPError as e:
            raise AIError(f"AI 请求失败: {e}") from e
        if resp.status_code != 200:
            raise AIError(f"AI 接口返回 {resp.status_code}: {resp.text[:200]}")
        try:
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as e:
            raise AIError(f"AI 响应结构异常: {e}") from e

    def chat_json(self, system: str, user: str, retries: int = 1):
        last_err: Exception | None = None
        prompt = user
        for attempt in range(retries + 1):
            text = self.chat(system, prompt)
            try:
                return extract_json(text)
            except ValueError as e:
                last_err = e
                prompt = (user + "\n\n[系统提醒] 上次响应无法解析为 JSON。"
                          "请只输出一个合法 JSON 对象，不要任何额外文字。")
        raise AIError(f"AI 响应 JSON 解析失败（重试{retries}次）: {last_err}")