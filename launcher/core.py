"""启动器核心：环境检测、依赖安装、数据初始化、AI 配置、子进程起停。

只用标准库，保证打包成 EXE 后即使 .venv 尚未创建也能运行。
所有长任务通过 run_step 流式输出日志，并支持中止。
"""
from __future__ import annotations

import json
import os
import queue
import shutil
import socket
import sqlite3
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_PORT = 8000
FRONTEND_PORT = 3100
ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
_REQUIRED_MODULES = ("fastapi", "uvicorn", "baostock", "akshare", "apscheduler",
                     "httpx", "pandas", "dotenv")
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def project_root(explicit: str | Path | None = None) -> Path:
    """EXE 放在项目根目录；源码运行时取 launcher 的上一级。"""
    if explicit:
        return Path(explicit).resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def venv_python(root: Path) -> Path | None:
    p = Path(root) / ".venv" / "Scripts" / "python.exe"
    return p if p.exists() else None


def npm_executable() -> str | None:
    return shutil.which("npm.cmd") or shutil.which("npm")


def port_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        return s.connect_ex((host, port)) == 0


def mask_key(key: str) -> str:
    if not key:
        return ""
    return "****" + key[-4:] if len(key) > 8 else "****"


def _db_path(root: Path) -> Path:
    custom = os.environ.get("DB_PATH", "")
    return Path(custom) if custom else Path(root) / "data" / "nine-quarter.db"


def _read_settings(db: Path) -> dict[str, str]:
    if not db.exists():
        return {}
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    except sqlite3.Error:
        return {}
    try:
        rows = conn.execute(
            "SELECT key,value FROM app_settings "
            "WHERE key IN ('ai_base_url','ai_api_key','ai_model')").fetchall()
        return {k: v for k, v in rows}
    except sqlite3.Error:
        return {}
    finally:
        conn.close()


def read_ai_config(root: Path) -> dict:
    """页面保存的值优先于环境变量；Key 只回传掩码。"""
    stored = _read_settings(_db_path(Path(root)))
    env_key = os.environ.get("AI_API_KEY") or os.environ.get("ARK_API_KEY", "")
    env_base = os.environ.get("AI_BASE_URL") or (ARK_BASE_URL if env_key else "")
    base = stored.get("ai_base_url") or env_base
    key = stored.get("ai_api_key") or env_key
    model = stored.get("ai_model") or os.environ.get("AI_MODEL", "")
    configured = bool(base and key and model)
    return {
        "base_url": base, "model": model,
        "key_configured": bool(key), "key_masked": mask_key(key),
        "configured": configured,
        "source": "db" if stored else ("env" if configured else "none"),
    }


def save_ai_config(root: Path, base_url: str, model: str, api_key: str = "") -> None:
    db = _db_path(Path(root))
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS app_settings "
                     "(key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)")
        values = {"ai_base_url": base_url.strip().rstrip("/"), "ai_model": model.strip()}
        if api_key and api_key.strip():
            values["ai_api_key"] = api_key.strip()
        for k, v in values.items():
            conn.execute(
                "INSERT INTO app_settings(key,value,updated_at) VALUES (?,?,datetime('now')) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
                "updated_at=excluded.updated_at", (k, v))
        conn.commit()
    finally:
        conn.close()


def probe_ai(base_url: str, api_key: str, model: str,
             timeout: float = 20) -> tuple[bool, str]:
    """极小请求验证地址/模型/Key；不落库、不打印 Key。"""
    if not (base_url and api_key and model):
        return False, "地址、模型、Key 均不能为空"
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 16,
    }).encode("utf-8")
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions", data=payload,
        headers={"Authorization": f"Bearer {api_key}",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        text = data["choices"][0]["message"]["content"]
        return True, str(text)[:80]
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:160]
        except Exception:
            pass
        return False, f"HTTP {e.code}：{body or e.reason}"
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return False, f"连接失败：{e}"
    except (KeyError, IndexError, ValueError) as e:
        return False, f"响应结构异常：{e}"


def python_deps_ok(py: Path) -> bool:
    code = ("import importlib.util as u,sys;"
            f"sys.exit(0 if all(u.find_spec(m) for m in {_REQUIRED_MODULES!r}) else 1)")
    try:
        r = subprocess.run([str(py), "-c", code], capture_output=True,
                           timeout=60, creationflags=_NO_WINDOW)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


@dataclass
class Status:
    root: Path
    venv_python: Path | None = None
    python_deps: bool = False
    node_modules: bool = False
    db_exists: bool = False
    bars: int = 0
    stocks: int = 0
    ai: dict = field(default_factory=dict)
    backend_open: bool = False
    frontend_open: bool = False

    @property
    def needs_setup(self) -> bool:
        return not (self.python_deps and self.node_modules and self.bars > 0
                    and self.ai.get("configured"))


def detect(root: Path) -> Status:
    root = Path(root)
    py = venv_python(root)
    db = _db_path(root)
    bars = stocks = 0
    db_exists = db.exists()
    if db_exists:
        try:
            conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            try:
                bars = conn.execute("SELECT COUNT(*) FROM daily_bars").fetchone()[0]
                stocks = conn.execute("SELECT COUNT(*) FROM stocks").fetchone()[0]
            finally:
                conn.close()
        except sqlite3.Error:
            bars = stocks = 0
    return Status(
        root=root, venv_python=py,
        python_deps=python_deps_ok(py) if py else False,
        node_modules=(root / "frontend" / "node_modules" / "next").exists(),
        db_exists=db_exists, bars=bars, stocks=stocks,
        ai=read_ai_config(root),
        backend_open=port_open(BACKEND_PORT),
        frontend_open=port_open(FRONTEND_PORT),
    )


def _kill_tree(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       capture_output=True, creationflags=_NO_WINDOW)
    else:
        try:
            os.kill(pid, 9)
        except OSError:
            pass


def run_step(cmd: list[str], cwd: Path, log, stop: threading.Event | None = None,
             env: dict | None = None) -> int:
    """执行命令并把输出逐行回调；stop 置位时终止整棵进程树。返回退出码。"""
    try:
        proc = subprocess.Popen(
            [str(c) for c in cmd], cwd=str(cwd), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            creationflags=_NO_WINDOW)
    except OSError as e:
        log(f"无法启动命令：{e}")
        return -1

    q: queue.Queue = queue.Queue()

    def _reader():
        try:
            for line in proc.stdout:
                q.put(line.rstrip("\n"))
        finally:
            q.put(None)

    threading.Thread(target=_reader, daemon=True).start()
    while True:
        if stop is not None and stop.is_set():
            log("已中止。")
            _kill_tree(proc.pid)
            proc.wait(timeout=10)
            return -1
        try:
            item = q.get(timeout=0.2)
        except queue.Empty:
            if proc.poll() is not None and q.empty():
                break
            continue
        if item is None:
            break
        log(item)
    return proc.wait()


def create_venv(root: Path, log, stop=None) -> int:
    py = shutil.which("python") or shutil.which("py")
    if not py:
        log("未找到系统 Python，请先安装 Python 3.12。")
        return -1
    return run_step([py, "-m", "venv", ".venv"], Path(root), log, stop)


def install_python_deps(root: Path, log, stop=None) -> int:
    py = venv_python(Path(root))
    if py is None:
        log("虚拟环境不存在。")
        return -1
    return run_step([str(py), "-m", "pip", "install", "-r", "requirements.txt"],
                    Path(root), log, stop)


def install_node_deps(root: Path, log, stop=None) -> int:
    npm = npm_executable()
    if not npm:
        log("未找到 npm，请先安装 Node.js。")
        return -1
    return run_step([npm, "install"], Path(root) / "frontend", log, stop)


def init_database(root: Path, log, stop=None) -> int:
    py = venv_python(Path(root))
    if py is None:
        return -1
    return run_step([str(py), "-m", "backend.cli", "init"], Path(root), log, stop)


def backfill_data(root: Path, log, stop=None) -> int:
    py = venv_python(Path(root))
    if py is None:
        return -1
    return run_step([str(py), "-m", "backend.cli", "backfill"], Path(root), log, stop)


def refresh_stock_info(root: Path, log, stop=None) -> int:
    py = venv_python(Path(root))
    if py is None:
        return -1
    return run_step([str(py), "-m", "backend.cli", "info"], Path(root), log, stop)


def run_daily(root: Path, log, stop=None) -> int:
    py = venv_python(Path(root))
    if py is None:
        return -1
    return run_step([str(py), "-m", "backend.cli", "daily"], Path(root), log, stop)


def _spawn(cmd: list[str], cwd: Path, log_path: Path):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(log_path, "a", encoding="utf-8")
    return subprocess.Popen(
        [str(c) for c in cmd], cwd=str(cwd), stdout=fh, stderr=subprocess.STDOUT,
        creationflags=_NO_WINDOW)


def start_backend(root: Path, log_path: Path):
    py = venv_python(Path(root))
    if py is None:
        raise RuntimeError("虚拟环境不存在，请先完成环境准备")
    return _spawn([str(py), "-m", "backend.cli", "serve", "--port", str(BACKEND_PORT)],
                  Path(root), log_path)


def start_frontend(root: Path, log_path: Path):
    npm = npm_executable()
    if not npm:
        raise RuntimeError("未找到 npm，请先安装 Node.js")
    return _spawn([npm, "run", "dev"], Path(root) / "frontend", log_path)


def stop_process(proc) -> None:
    if proc is None or proc.poll() is not None:
        return
    _kill_tree(proc.pid)
