"""nine-quarter 桌面启动器界面：首次引导 + 运行控制台。

设计目标：双击即用；首次自动引导（环境 → 数据 → AI → 启动），
之后直接进控制台，可起停前后端、看状态与日志。
"""
from __future__ import annotations

import queue
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox

from . import core

BG = "#0e1520"
CARD = "#16202e"
CARD_ALT = "#1b2738"
LINE = "#243349"
TEXT = "#e7eef7"
SUB = "#93a4bb"
ACCENT = "#3b82f6"
OK = "#22c55e"
WARN = "#f59e0b"
BAD = "#ef4444"
FONT = "Microsoft YaHei UI"
MONO = "Consolas"


class App(tk.Tk):
    def __init__(self, root_dir: Path):
        super().__init__()
        self.root_dir = Path(root_dir)
        self.title("nine-quarter 启动器")
        self.geometry("1040x680")
        self.minsize(940, 620)
        self.configure(bg=BG)
        self._log_q: queue.Queue = queue.Queue()
        self._busy = False
        self._stop = threading.Event()
        self._backend = None
        self._frontend = None
        self._status: core.Status | None = None
        self._step = 0
        self._build()
        self.after(80, self._pump)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.refresh_status(initial=True)

    # ---------- 基础组件 ----------

    def _card(self, parent, **kw):
        return tk.Frame(parent, bg=CARD, highlightbackground=LINE,
                        highlightthickness=1, **kw)

    def _label(self, parent, text, size=10, color=TEXT, bold=False, **kw):
        return tk.Label(parent, text=text, bg=parent["bg"], fg=color,
                        font=(FONT, size, "bold" if bold else "normal"), **kw)

    def _button(self, parent, text, command, primary=False, width=16):
        b = tk.Button(parent, text=text, command=command, width=width,
                      bg=ACCENT if primary else CARD_ALT,
                      fg="#ffffff" if primary else TEXT,
                      activebackground="#2f6fd0" if primary else LINE,
                      activeforeground="#ffffff", relief="flat", bd=0,
                      font=(FONT, 10), padx=12, pady=7, cursor="hand2",
                      disabledforeground=SUB)
        return b

    def _build(self):
        head = tk.Frame(self, bg=BG)
        head.pack(fill="x", padx=22, pady=(18, 10))
        self._label(head, "nine-quarter", size=19, bold=True, color=ACCENT).pack(side="left")
        self._label(head, "  AI 股票筛选与模拟投资 · 个人研究 · 非实盘",
                    size=10, color=SUB).pack(side="left", pady=(8, 0))
        self._mode_label = self._label(head, "", size=10, color=SUB)
        self._mode_label.pack(side="right")

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=22)
        self.left = tk.Frame(body, bg=BG, width=430)
        self.left.pack(side="left", fill="both", expand=False)
        self.left.pack_propagate(False)
        right = tk.Frame(body, bg=BG)
        right.pack(side="left", fill="both", expand=True, padx=(16, 0))

        logcard = self._card(right)
        logcard.pack(fill="both", expand=True)
        bar = tk.Frame(logcard, bg=CARD)
        bar.pack(fill="x", padx=14, pady=(12, 6))
        self._label(bar, "运行日志", size=11, bold=True).pack(side="left")
        self._button(bar, "清空", lambda: self.log_text.delete("1.0", "end"),
                     width=6).pack(side="right")
        self.log_text = tk.Text(logcard, bg="#0b121c", fg="#c9d6e6", bd=0,
                                font=(MONO, 9), wrap="word", height=10,
                                insertbackground=TEXT, padx=12, pady=10)
        self.log_text.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.log_text.configure(state="disabled")

        self.panel = tk.Frame(self.left, bg=BG)
        self.panel.pack(fill="both", expand=True)

        foot = tk.Frame(self, bg=BG)
        foot.pack(fill="x", padx=22, pady=12)
        self._label(foot, "后端 8000 · 前端 3100 · 关闭窗口时会询问是否停止服务",
                    size=9, color=SUB).pack(side="left")
        self._button(foot, "刷新状态", self.refresh_status, width=10).pack(side="right")

    # ---------- 日志 ----------

    def log(self, message: str):
        self._log_q.put(str(message))

    def _ui_call(self, fn):
        """从工作线程调度到 UI 线程；窗口已销毁时静默忽略。"""
        try:
            self.after(0, fn)
        except (tk.TclError, RuntimeError):
            pass

    def _pump(self):
        try:
            while True:
                msg = self._log_q.get_nowait()
                self.log_text.configure(state="normal")
                self.log_text.insert("end", msg + "\n")
                if int(self.log_text.index("end-1c").split(".")[0]) > 2000:
                    self.log_text.delete("1.0", "500.0")
                self.log_text.see("end")
                self.log_text.configure(state="disabled")
        except queue.Empty:
            pass
        except tk.TclError:
            return
        try:
            self.after(80, self._pump)
        except tk.TclError:
            pass

    # ---------- 状态 ----------

    def refresh_status(self, initial=False):
        def work():
            st = core.detect(self.root_dir)
            self._ui_call(lambda: self._apply_status(st, initial))
        threading.Thread(target=work, daemon=True).start()

    def _apply_status(self, st: core.Status, initial=False):
        self._status = st
        try:
            if initial:
                self.log(f"项目目录：{st.root}")
                if st.needs_setup:
                    self._step = self._first_incomplete(st)
                    self.log("检测到尚未完成初始化，进入首次引导。")
                else:
                    self.log("环境已就绪。")
            self._render()
        except tk.TclError:
            pass

    @staticmethod
    def _first_incomplete(st: core.Status) -> int:
        """引导直接停在第一个未完成的步骤，已完成的不再重复点。"""
        if not (st.venv_python and st.python_deps and st.node_modules):
            return 0
        if st.bars <= 0:
            return 1
        if not st.ai.get("configured"):
            return 2
        return 3

    def _pill(self, parent, name, ok, detail=""):
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill="x", pady=3)
        dot = tk.Label(row, text="●", bg=CARD, fg=OK if ok else BAD, font=(FONT, 11))
        dot.pack(side="left")
        self._label(row, f" {name}", size=10).pack(side="left")
        self._label(row, detail, size=9, color=SUB).pack(side="right")

    def _render(self):
        for w in self.panel.winfo_children():
            w.destroy()
        st = self._status
        if st is None:
            self._label(self.panel, "正在检测环境…", color=SUB).pack(anchor="w")
            return
        if st.needs_setup:
            self._mode_label.configure(text="首次引导")
            self._render_wizard(st)
        else:
            self._mode_label.configure(text="控制台")
            self._render_console(st)

    # ---------- 首次引导 ----------

    def _render_wizard(self, st: core.Status):
        titles = ["1 环境准备", "2 行情数据", "3 AI 配置", "4 启动"]
        nav = self._card(self.panel)
        nav.pack(fill="x", pady=(0, 12))
        inner = tk.Frame(nav, bg=CARD)
        inner.pack(fill="x", padx=14, pady=12)
        for i, t in enumerate(titles):
            color = ACCENT if i == self._step else (OK if i < self._step else SUB)
            self._label(inner, t, size=10, color=color,
                        bold=(i == self._step)).pack(anchor="w", pady=2)

        card = self._card(self.panel)
        card.pack(fill="both", expand=True)
        box = tk.Frame(card, bg=CARD)
        box.pack(fill="both", expand=True, padx=16, pady=14)

        if self._step == 0:
            self._label(box, "环境准备", size=13, bold=True).pack(anchor="w")
            self._label(box, "检查 Python 虚拟环境、后端依赖与前端依赖。",
                        size=9, color=SUB).pack(anchor="w", pady=(2, 10))
            self._pill(box, "虚拟环境 .venv", st.venv_python is not None)
            self._pill(box, "后端依赖", st.python_deps)
            self._pill(box, "前端依赖 node_modules", st.node_modules)
            btns = tk.Frame(box, bg=CARD)
            btns.pack(fill="x", pady=(14, 0))
            self._button(btns, "一键准备环境", self._task_env, primary=True).pack(side="left")
            self._button(btns, "下一步", lambda: self._goto(1), width=10).pack(side="left", padx=8)
        elif self._step == 1:
            self._label(box, "行情数据", size=13, bold=True).pack(anchor="w")
            self._label(box, "首次回填约 15～20 分钟，可中断，重跑会续传。",
                        size=9, color=SUB).pack(anchor="w", pady=(2, 10))
            self._pill(box, "数据库", st.db_exists)
            self._pill(box, "日线数据", st.bars > 0, f"{st.bars} 条 / {st.stocks} 只")
            btns = tk.Frame(box, bg=CARD)
            btns.pack(fill="x", pady=(14, 0))
            self._button(btns, "初始化并回填", self._task_data, primary=True).pack(side="left")
            self._button(btns, "中止", self._request_stop, width=8).pack(side="left", padx=8)
            self._button(btns, "跳过", lambda: self._goto(2), width=8).pack(side="left")
        elif self._step == 2:
            self._label(box, "AI 配置", size=13, bold=True).pack(anchor="w")
            self._label(box, "未配置也能运行，但不会产生 AI 选股与订单。",
                        size=9, color=SUB).pack(anchor="w", pady=(2, 10))
            ai = st.ai
            self.ai_base = self._entry(box, "接口地址", ai["base_url"] or core.ARK_BASE_URL)
            self.ai_model = self._entry(box, "模型 / 接入点", ai["model"])
            self.ai_key = self._entry(box, "API Key",
                                      "", show="*",
                                      hint=(f"已配置 {ai['key_masked']}，留空保持不变"
                                            if ai["key_configured"] else "填写 API Key"))
            btns = tk.Frame(box, bg=CARD)
            btns.pack(fill="x", pady=(14, 0))
            self._button(btns, "测试连接", self._task_ai_test, width=10).pack(side="left")
            self._button(btns, "保存并继续", self._task_ai_save, primary=True).pack(side="left", padx=8)
            self._button(btns, "暂不配置", lambda: self._goto(3), width=10).pack(side="left")
        else:
            self._label(box, "准备完成", size=13, bold=True).pack(anchor="w")
            self._label(box, "启动后端与前端，并自动打开浏览器。",
                        size=9, color=SUB).pack(anchor="w", pady=(2, 10))
            self._pill(box, "后端依赖", st.python_deps)
            self._pill(box, "前端依赖", st.node_modules)
            self._pill(box, "行情数据", st.bars > 0, f"{st.bars} 条")
            self._pill(box, "AI 配置", bool(st.ai.get("configured")),
                       st.ai.get("model") or "未配置")
            btns = tk.Frame(box, bg=CARD)
            btns.pack(fill="x", pady=(14, 0))
            self._button(btns, "启动并打开页面", self._start_all, primary=True).pack(side="left")
            self._button(btns, "返回修改", lambda: self._goto(0), width=10).pack(side="left", padx=8)

    def _entry(self, parent, label, value, show=None, hint=""):
        wrap = tk.Frame(parent, bg=CARD)
        wrap.pack(fill="x", pady=5)
        self._label(wrap, label, size=9, color=SUB).pack(anchor="w")
        e = tk.Entry(wrap, bg="#0b121c", fg=TEXT, insertbackground=TEXT,
                     relief="flat", font=(FONT, 10), show=show or "")
        e.pack(fill="x", ipady=6, pady=(3, 0))
        e.insert(0, value)
        if hint:
            self._label(wrap, hint, size=8, color=SUB).pack(anchor="w", pady=(2, 0))
        return e

    def _goto(self, step: int):
        self._step = step
        self._render()

    # ---------- 控制台 ----------

    def _render_console(self, st: core.Status):
        card = self._card(self.panel)
        card.pack(fill="x")
        box = tk.Frame(card, bg=CARD)
        box.pack(fill="x", padx=16, pady=14)
        self._label(box, "运行状态", size=13, bold=True).pack(anchor="w", pady=(0, 8))
        self._pill(box, f"后端 :{core.BACKEND_PORT}", st.backend_open,
                   "运行中" if st.backend_open else "未启动")
        self._pill(box, f"前端 :{core.FRONTEND_PORT}", st.frontend_open,
                   "运行中" if st.frontend_open else "未启动")
        self._pill(box, "AI 配置", bool(st.ai.get("configured")),
                   st.ai.get("model") or "未配置")
        self._pill(box, "行情数据", st.bars > 0, f"{st.bars} 条日线 / {st.stocks} 只")

        actions = self._card(self.panel)
        actions.pack(fill="x", pady=(12, 0))
        ab = tk.Frame(actions, bg=CARD)
        ab.pack(fill="x", padx=16, pady=14)
        self._label(ab, "操作", size=13, bold=True).pack(anchor="w", pady=(0, 10))
        row1 = tk.Frame(ab, bg=CARD)
        row1.pack(fill="x")
        self._button(row1, "启动服务", self._start_all, primary=True).pack(side="left")
        self._button(row1, "停止服务", self._stop_all, width=12).pack(side="left", padx=8)
        row2 = tk.Frame(ab, bg=CARD)
        row2.pack(fill="x", pady=(10, 0))
        self._button(row2, "打开页面", self._open_page, width=12).pack(side="left")
        self._button(row2, "AI 设置", self._open_settings, width=12).pack(side="left", padx=8)
        row3 = tk.Frame(ab, bg=CARD)
        row3.pack(fill="x", pady=(10, 0))
        self._button(row3, "立即执行今日流程", self._task_daily, width=18).pack(side="left")
        self._button(row3, "中止任务", self._request_stop, width=10).pack(side="left", padx=8)
        row4 = tk.Frame(ab, bg=CARD)
        row4.pack(fill="x", pady=(10, 0))
        self._button(row4, "重跑首次引导", lambda: self._goto_wizard(), width=18).pack(side="left")
        self._button(row4, "补充行业/市值", self._task_info, width=14).pack(side="left", padx=8)

    def _goto_wizard(self):
        self._step = 0
        st = self._status
        if st:
            self._mode_label.configure(text="首次引导")
            for w in self.panel.winfo_children():
                w.destroy()
            self._render_wizard(st)

    # ---------- 任务 ----------

    def _run(self, name, fn, on_done=None):
        if self._busy:
            self.log("已有任务在执行，请先等待或中止。")
            return
        self._busy = True
        self._stop = threading.Event()
        self.log(f"—— {name} ——")

        def work():
            try:
                rc = fn(self.log, self._stop)
            except Exception as e:  # noqa: BLE001 - 界面需要显示任何失败
                rc = -1
                self.log(f"出错：{e}")
            self._ui_call(lambda: self._done(name, rc, on_done))

        threading.Thread(target=work, daemon=True).start()

    def _done(self, name, rc, on_done):
        self._busy = False
        self.log(f"—— {name} {'完成' if rc == 0 else f'结束（code={rc}）'} ——")
        if on_done:
            on_done(rc)
        self.refresh_status()

    def _request_stop(self):
        self._stop.set()
        self.log("已请求中止…")

    def _task_env(self):
        def job(log, stop):
            if core.venv_python(self.root_dir) is None:
                log("创建虚拟环境 .venv …")
                if core.create_venv(self.root_dir, log, stop) != 0:
                    return -1
            log("安装后端依赖（pip install -r requirements.txt）…")
            if core.install_python_deps(self.root_dir, log, stop) != 0:
                return -1
            log("安装前端依赖（npm install）…")
            return core.install_node_deps(self.root_dir, log, stop)
        self._run("环境准备", job, lambda rc: self._goto(1) if rc == 0 else None)

    def _task_data(self):
        def job(log, stop):
            if core.init_database(self.root_dir, log, stop) != 0:
                return -1
            log("开始回填行情（可中断，重跑续传）…")
            return core.backfill_data(self.root_dir, log, stop)
        self._run("行情初始化与回填", job, lambda rc: self._goto(2) if rc == 0 else None)

    def _task_info(self):
        self._run("补充行业/市值", lambda log, stop: core.refresh_stock_info(
            self.root_dir, log, stop))

    def _task_daily(self):
        self._run("今日流程", lambda log, stop: core.run_daily(self.root_dir, log, stop))

    def _ai_form_values(self):
        return (self.ai_base.get().strip(), self.ai_model.get().strip(),
                self.ai_key.get().strip())

    def _task_ai_test(self):
        base, model, key = self._ai_form_values()
        key = key or self._stored_key()

        def job(log, stop):
            ok, msg = core.probe_ai(base, key, model)
            log(("连接成功：" if ok else "连接失败：") + msg)
            return 0 if ok else -1
        self._run("测试 AI 连接", job)

    def _stored_key(self) -> str:
        import sqlite3
        db = self.root_dir / "data" / "nine-quarter.db"
        if not db.exists():
            import os
            return os.environ.get("AI_API_KEY") or os.environ.get("ARK_API_KEY", "")
        try:
            conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            row = conn.execute(
                "SELECT value FROM app_settings WHERE key='ai_api_key'").fetchone()
            conn.close()
            if row:
                return row[0]
        except sqlite3.Error:
            pass
        import os
        return os.environ.get("AI_API_KEY") or os.environ.get("ARK_API_KEY", "")

    def _task_ai_save(self):
        base, model, key = self._ai_form_values()
        if not base or not model:
            messagebox.showwarning("缺少信息", "接口地址与模型名必填。")
            return
        if not key and not self._stored_key():
            messagebox.showwarning("缺少信息", "请填写 API Key。")
            return

        def job(log, stop):
            core.save_ai_config(self.root_dir, base, model, key)
            log("已保存到本机数据库，后端启动后自动生效。")
            return 0
        self._run("保存 AI 配置", job, lambda rc: self._goto(3) if rc == 0 else None)

    # ---------- 服务起停 ----------

    def _start_all(self):
        st = self._status
        try:
            if not (st and st.backend_open):
                self._backend = core.start_backend(
                    self.root_dir, self.root_dir / "logs" / "launcher-backend.log")
                self.log(f"后端已启动（PID {self._backend.pid}），日志 logs/launcher-backend.log")
            else:
                self.log("后端已在运行，跳过。")
            if not (st and st.frontend_open):
                self._frontend = core.start_frontend(
                    self.root_dir, self.root_dir / "logs" / "launcher-frontend.log")
                self.log(f"前端已启动（PID {self._frontend.pid}），日志 logs/launcher-frontend.log")
            else:
                self.log("前端已在运行，跳过。")
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("启动失败", str(e))
            return
        self.log("前端首次编译需要几十秒，稍候再打开页面。")
        self.after(1500, self.refresh_status)
        self.after(12000, self._open_page)

    def _stop_all(self):
        core.stop_process(self._backend)
        core.stop_process(self._frontend)
        self._backend = self._frontend = None
        self.log("已停止由启动器拉起的服务。")
        self.after(1200, self.refresh_status)

    def _open_page(self):
        webbrowser.open(f"http://127.0.0.1:{core.FRONTEND_PORT}/")

    def _open_settings(self):
        webbrowser.open(f"http://127.0.0.1:{core.FRONTEND_PORT}/settings")

    def _on_close(self):
        running = (self._backend and self._backend.poll() is None) or \
                  (self._frontend and self._frontend.poll() is None)
        if running:
            stop = messagebox.askyesnocancel(
                "退出", "服务仍在运行。\n\n是：停止服务并退出\n否：保留服务，仅关闭启动器")
            if stop is None:
                return
            if stop:
                self._stop_all()
        self.destroy()


def main(root_dir: Path | None = None):
    app = App(core.project_root(root_dir))
    app.mainloop()
