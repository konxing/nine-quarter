"""打包启动器为根目录 nine-quarter.exe。

用法：.venv\\Scripts\\python.exe build_exe.py
需要 .venv 中已安装 pyinstaller。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = ROOT / ".venv" / "Scripts" / "python.exe"


def main() -> int:
    python = str(PY if PY.exists() else Path(sys.executable))
    subprocess.run([python, "-m", "launcher.make_icon"], cwd=ROOT, check=True)
    cmd = [
        python, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--onefile", "--windowed",
        "--name", "nine-quarter",
        "--icon", str(ROOT / "launcher" / "icon.ico"),
        "--distpath", str(ROOT),
        "--workpath", str(ROOT / "build" / "launcher"),
        "--specpath", str(ROOT / "build"),
        str(ROOT / "launcher_entry.py"),
    ]
    subprocess.run(cmd, cwd=ROOT, check=True)
    exe = ROOT / "nine-quarter.exe"
    print(f"完成: {exe} ({exe.stat().st_size / 1024 / 1024:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
