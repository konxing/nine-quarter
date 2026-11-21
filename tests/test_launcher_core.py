"""启动器核心逻辑测试：环境检测、AI 配置读写、连通测试、命令流式执行。

不触网、不真装依赖：子进程用当前解释器执行无害命令，网络用假响应替换。
"""
import json
import socket
import sqlite3
import sys
import threading
import time
from pathlib import Path

import pytest

from launcher import core


@pytest.fixture
def root(tmp_path):
    (tmp_path / "backend").mkdir()
    (tmp_path / "frontend").mkdir()
    return tmp_path


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class TestDetect:
    def test_empty_project_reports_missing_everything(self, root, monkeypatch):
        for k in ("AI_BASE_URL", "AI_API_KEY", "AI_MODEL", "ARK_API_KEY"):
            monkeypatch.delenv(k, raising=False)
        st = core.detect(root)
        assert st.venv_python is None
        assert st.python_deps is False
        assert st.node_modules is False
        assert st.db_exists is False
        assert st.bars == 0
        assert st.ai["key_configured"] is False
        assert st.needs_setup is True

    def test_node_modules_detected(self, root):
        (root / "frontend" / "node_modules" / "next").mkdir(parents=True)
        assert core.detect(root).node_modules is True

    def test_npm_missing_is_reported(self, root, monkeypatch):
        monkeypatch.setattr(core, "npm_executable", lambda: None)
        assert core.detect(root).npm_ok is False

    def test_npm_present_is_reported(self, root, monkeypatch):
        monkeypatch.setattr(core, "npm_executable", lambda: "C:/node/npm.cmd")
        assert core.detect(root).npm_ok is True

    def test_db_counts_read(self, root):
        db = root / "data" / "nine-quarter.db"
        db.parent.mkdir()
        c = sqlite3.connect(db)
        c.executescript(
            "CREATE TABLE daily_bars(code TEXT, date TEXT);"
            "CREATE TABLE stocks(code TEXT);"
            "CREATE TABLE app_settings(key TEXT PRIMARY KEY, value TEXT, updated_at TEXT);")
        c.executemany("INSERT INTO daily_bars VALUES (?,?)",
                      [("sh.600000", "2026-11-09"), ("sh.600001", "2026-11-09")])
        c.execute("INSERT INTO stocks VALUES ('sh.600000')")
        c.commit()
        c.close()
        st = core.detect(root)
        assert st.db_exists is True
        assert st.bars == 2
        assert st.stocks == 1

    def test_port_open_false_when_nothing_listening(self):
        assert core.port_open(_free_port()) is False


class TestAIConfig:
    def test_save_then_read_masked(self, root, monkeypatch):
        for k in ("AI_BASE_URL", "AI_API_KEY", "AI_MODEL", "ARK_API_KEY"):
            monkeypatch.delenv(k, raising=False)
        core.save_ai_config(root, "https://api.example.com/v1/", "ep-1", "sk-1234567890")
        ai = core.read_ai_config(root)
        assert ai["base_url"] == "https://api.example.com/v1"
        assert ai["model"] == "ep-1"
        assert ai["key_configured"] is True
        assert ai["key_masked"] == "****7890"
        assert ai["source"] == "db"

    def test_blank_key_keeps_previous(self, root, monkeypatch):
        for k in ("AI_BASE_URL", "AI_API_KEY", "AI_MODEL", "ARK_API_KEY"):
            monkeypatch.delenv(k, raising=False)
        core.save_ai_config(root, "https://api.example.com", "ep-1", "sk-firstkey123")
        core.save_ai_config(root, "https://api.example.com", "ep-2", "")
        ai = core.read_ai_config(root)
        assert ai["model"] == "ep-2"
        assert ai["key_configured"] is True

    def test_env_fallback_when_no_db_value(self, root, monkeypatch):
        monkeypatch.delenv("AI_BASE_URL", raising=False)
        monkeypatch.delenv("AI_API_KEY", raising=False)
        monkeypatch.setenv("AI_MODEL", "ep-env")
        monkeypatch.setenv("ARK_API_KEY", "sk-envkey9999")
        ai = core.read_ai_config(root)
        assert ai["base_url"] == "https://ark.cn-beijing.volces.com/api/v3"
        assert ai["model"] == "ep-env"
        assert ai["key_configured"] is True
        assert ai["source"] == "env"

    def test_probe_success(self, monkeypatch):
        class FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return json.dumps(
                    {"choices": [{"message": {"content": "OK"}}]}).encode()

        monkeypatch.setattr(core.urllib.request, "urlopen", lambda *a, **k: FakeResp())
        ok, msg = core.probe_ai("https://api.example.com", "sk-x", "ep-1")
        assert ok is True
        assert "OK" in msg

    def test_probe_http_error_reported(self, monkeypatch):
        import urllib.error

        def _raise(*a, **k):
            raise urllib.error.HTTPError(
                "https://api.example.com", 401, "Unauthorized", {}, None)

        monkeypatch.setattr(core.urllib.request, "urlopen", _raise)
        ok, msg = core.probe_ai("https://api.example.com", "sk-x", "ep-1")
        assert ok is False
        assert "401" in msg

    def test_probe_requires_complete_config(self):
        ok, msg = core.probe_ai("", "", "")
        assert ok is False
        assert msg


class TestRunStep:
    def test_streams_output_and_returns_code(self, tmp_path):
        lines = []
        code = core.run_step(
            [sys.executable, "-c", "print('hello'); print('world')"],
            cwd=tmp_path, log=lines.append)
        assert code == 0
        assert "hello" in lines and "world" in lines

    def test_nonzero_exit_propagates(self, tmp_path):
        code = core.run_step([sys.executable, "-c", "raise SystemExit(3)"],
                             cwd=tmp_path, log=lambda s: None)
        assert code == 3

    def test_stop_event_terminates_long_task(self, tmp_path):
        stop = threading.Event()
        lines = []

        def _log(s):
            lines.append(s)
            stop.set()

        t0 = time.time()
        code = core.run_step(
            [sys.executable, "-u", "-c",
             "import time; print('start', flush=True); time.sleep(30)"],
            cwd=tmp_path, log=_log, stop=stop)
        assert time.time() - t0 < 15
        assert code != 0
        assert "start" in lines

    def test_missing_executable_returns_error(self, tmp_path):
        lines = []
        code = core.run_step([str(tmp_path / "nope.exe")], cwd=tmp_path,
                             log=lines.append)
        assert code != 0
        assert lines


class TestProcessWiring:
    def test_backend_command_uses_venv_python(self, root, monkeypatch):
        captured = {}

        class FakePopen:
            def __init__(self, cmd, **kw):
                captured["cmd"] = cmd
                captured["kw"] = kw
                self.pid = 4321

            def poll(self):
                return None

        monkeypatch.setattr(core.subprocess, "Popen", FakePopen)
        py = root / ".venv" / "Scripts" / "python.exe"
        py.parent.mkdir(parents=True)
        py.write_text("")
        core.start_backend(root, log_path=root / "b.log")
        assert captured["cmd"][0] == str(py)
        assert captured["cmd"][1:4] == ["-m", "backend.cli", "serve"]
        assert captured["kw"]["cwd"] == str(root)

    def test_frontend_command_runs_npm_in_frontend(self, root, monkeypatch):
        captured = {}

        class FakePopen:
            def __init__(self, cmd, **kw):
                captured["cmd"] = cmd
                captured["kw"] = kw
                self.pid = 5678

            def poll(self):
                return None

        monkeypatch.setattr(core.subprocess, "Popen", FakePopen)
        monkeypatch.setattr(core.shutil, "which", lambda name: "C:/node/npm.cmd")
        core.start_frontend(root, log_path=root / "f.log")
        assert captured["cmd"][0].endswith("npm.cmd")
        assert captured["cmd"][1:] == ["run", "dev"]
        assert captured["kw"]["cwd"] == str(root / "frontend")
