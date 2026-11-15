"""启动器界面测试：只构建窗口并立即隐藏，不启动任何服务。

无显示环境（Tk 不可用）时自动跳过。
"""
import tkinter as tk

import pytest

from launcher import core

try:
    tk.Tk().destroy()
    _TK_OK = True
except Exception:  # noqa: BLE001 - 无显示环境
    _TK_OK = False

pytestmark = pytest.mark.skipif(not _TK_OK, reason="无可用显示环境")


@pytest.fixture
def app(tmp_path, monkeypatch):
    from launcher.app import App
    (tmp_path / "backend").mkdir()
    (tmp_path / "frontend" / "node_modules" / "next").mkdir(parents=True)
    for k in ("AI_BASE_URL", "AI_API_KEY", "AI_MODEL", "ARK_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    a = App(tmp_path)
    a.withdraw()
    yield a
    a.destroy()


def _status(root, **kw):
    st = core.Status(root=root, venv_python=root / ".venv" / "Scripts" / "python.exe",
                     python_deps=True, node_modules=True, db_exists=True,
                     bars=100, stocks=10,
                     ai={"configured": True, "model": "ep-1", "key_configured": True,
                         "key_masked": "****1234", "base_url": "https://x", "source": "db"})
    for k, v in kw.items():
        setattr(st, k, v)
    return st


class TestWizard:
    def test_lands_on_first_incomplete_step(self, app, tmp_path):
        """环境与数据都就绪、只差 AI 时，引导应直接停在 AI 配置这一步。"""
        app._apply_status(_status(tmp_path, ai={"configured": False, "model": "",
                                                "key_configured": False,
                                                "key_masked": "", "base_url": "",
                                                "source": "none"}), initial=True)
        app.update()
        assert app._step == 2

    def test_lands_on_data_step_when_no_bars(self, app, tmp_path):
        app._apply_status(_status(tmp_path, bars=0), initial=True)
        app.update()
        assert app._step == 1

    def test_console_when_everything_ready(self, app, tmp_path):
        app._apply_status(_status(tmp_path), initial=True)
        app.update()
        assert app._mode_label.cget("text") == "控制台"

    def test_wizard_renders_all_steps(self, app, tmp_path):
        st = _status(tmp_path)
        for step in range(4):
            app._step = step
            app._status = st
            app._render()
            app.update()
            assert app.panel.winfo_children()
