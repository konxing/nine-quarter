"""入口：python -m launcher [--root PATH] [--selfcheck]

--selfcheck 不打开界面，只打印环境检测结果（JSON），用于打包后验证。
"""
from __future__ import annotations

import argparse
import json
import sys

from . import core


def main():
    p = argparse.ArgumentParser(prog="nine-quarter")
    p.add_argument("--root", default=None, help="项目根目录（默认 EXE 所在目录）")
    p.add_argument("--selfcheck", action="store_true", help="只检测环境并输出 JSON")
    args = p.parse_args()
    root = core.project_root(args.root)
    if args.selfcheck:
        st = core.detect(root)
        payload = {
            "root": str(st.root),
            "venv_python": str(st.venv_python) if st.venv_python else None,
            "python_deps": st.python_deps,
            "node_modules": st.node_modules,
            "db_exists": st.db_exists,
            "bars": st.bars, "stocks": st.stocks,
            "ai": st.ai,
            "backend_open": st.backend_open,
            "frontend_open": st.frontend_open,
            "needs_setup": st.needs_setup,
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        if sys.stdout is None:
            # 打包成无控制台 EXE 时没有 stdout，落盘便于验证
            (root / "launcher-selfcheck.json").write_text(text, encoding="utf-8")
        else:
            print(text)
        return
    from .app import main as gui_main
    gui_main(root)


if __name__ == "__main__":
    main()
