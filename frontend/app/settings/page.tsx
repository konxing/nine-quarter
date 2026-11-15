"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  ApiError,
  getAISettings,
  saveAISettings,
  testAISettings,
  type AISettingsState,
} from "@/lib/api";
import { ErrorBox, Loading } from "@/components/States";

function sourceText(source: string): string {
  switch (source) {
    case "db":
      return "本机页面保存（优先于环境变量）";
    case "env":
      return "来自环境变量";
    default:
      return "未配置";
  }
}

export default function SettingsPage() {
  const [state, setState] = useState<AISettingsState | null>(null);
  const [baseUrl, setBaseUrl] = useState("");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"save" | "test" | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(
    null
  );

  useEffect(() => {
    let alive = true;
    getAISettings()
      .then((s) => {
        if (!alive) return;
        setState(s);
        setBaseUrl(s.base_url);
        setModel(s.model);
        setLoading(false);
      })
      .catch((e: unknown) => {
        if (!alive) return;
        setError(e instanceof Error ? e.message : String(e));
        setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  const input = { base_url: baseUrl.trim(), model: model.trim(), api_key: apiKey.trim() };

  async function handleSave() {
    setBusy("save");
    setError(null);
    setNotice(null);
    setTestResult(null);
    try {
      const s = await saveAISettings(input);
      setState(s);
      setApiKey("");
      setNotice("已保存并立即生效，无需重启后端。");
    } catch (e: unknown) {
      setError(
        e instanceof ApiError || e instanceof Error ? e.message : String(e)
      );
    } finally {
      setBusy(null);
    }
  }

  async function handleTest() {
    setBusy("test");
    setError(null);
    setNotice(null);
    try {
      setTestResult(await testAISettings(input));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div>
      <h1 className="page-title">设置</h1>
      <p className="page-desc">
        AI 接口配置。保存后立即生效（无需重启后端）；配置存在本机数据库，
        优先于 .env 中的 AI_BASE_URL / AI_API_KEY / AI_MODEL。
      </p>

      {loading ? <Loading /> : null}
      {error ? <ErrorBox message={error} /> : null}

      {!loading && state ? (
        <>
          <div className="card">
            <div className="info-row">
              <strong>当前配置</strong>
              <span
                className={
                  state.key_configured
                    ? "badge badge-ok"
                    : "badge badge-failed"
                }
              >
                {state.key_configured ? "已配置" : "未配置"}
              </span>
              <span className="hint">{sourceText(state.source)}</span>
              {state.key_configured ? (
                <span className="hint">Key：{state.key_masked}</span>
              ) : null}
            </div>
            {state.base_url ? (
              <p className="hint">
                当前地址：{state.base_url}　模型：{state.model || "未填写"}
              </p>
            ) : null}
          </div>

          <div className="card">
            <h2>AI 接口</h2>
            <div className="form-grid">
              <label className="form-field">
                <span className="field-label">接口地址（OpenAI 兼容）</span>
                <input
                  className="text-input"
                  value={baseUrl}
                  onChange={(e) => setBaseUrl(e.target.value)}
                  placeholder="https://ark.cn-beijing.volces.com/api/v3"
                  autoComplete="off"
                  spellCheck={false}
                />
              </label>
              <label className="form-field">
                <span className="field-label">模型名 / 推理接入点</span>
                <input
                  className="text-input"
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                  placeholder="ep-xxxxxxxx 或已开通的模型名"
                  autoComplete="off"
                  spellCheck={false}
                />
              </label>
              <label className="form-field">
                <span className="field-label">API Key</span>
                <input
                  className="text-input"
                  type="password"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder={
                    state.key_configured
                      ? `已配置 ${state.key_masked}；留空则保持不变`
                      : "填写 API Key"
                  }
                  autoComplete="new-password"
                />
              </label>
            </div>

            <div className="form-actions">
              <button
                className="btn btn-secondary"
                onClick={handleTest}
                disabled={busy !== null}
              >
                {busy === "test" ? "测试中…" : "测试连接"}
              </button>
              <button
                className="btn btn-primary"
                onClick={handleSave}
                disabled={busy !== null}
              >
                {busy === "save" ? "保存中…" : "保存并生效"}
              </button>
              <Link href="/" className="hint">
                去每日选股
              </Link>
            </div>

            {testResult ? (
              <div
                className={
                  testResult.ok
                    ? "state-box loading"
                    : "state-box error"
                }
              >
                {testResult.ok ? "连接成功" : "连接失败"}
                <p>{testResult.message}</p>
              </div>
            ) : null}
            {notice ? <div className="state-box loading">{notice}</div> : null}

            <p className="hint">
              说明：测试连接只发送一次极小的请求，不会保存配置；Key
              以明文存入本机 SQLite，页面只显示掩码。请勿在多人共用的机器上使用。
            </p>
          </div>
        </>
      ) : null}
    </div>
  );
}
