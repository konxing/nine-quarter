"""打包相关测试：图标文件结构、无控制台时的自检输出。"""
import json
import struct
import sys
from pathlib import Path

import pytest

from launcher import make_icon


class TestIcon:
    def test_ico_contains_png_images(self, tmp_path):
        out = make_icon.build_icon(tmp_path / "icon.ico")
        data = out.read_bytes()
        reserved, kind, count = struct.unpack("<HHH", data[:6])
        assert (reserved, kind) == (0, 1)
        assert count >= 4
        # 每个条目指向的数据必须是 PNG
        for i in range(count):
            entry = data[6 + i * 16: 6 + (i + 1) * 16]
            size, offset = struct.unpack("<II", entry[8:16])
            assert data[offset:offset + 8] == b"\x89PNG\r\n\x1a\n"
            assert size > 0


class TestSelfcheckWithoutConsole:
    def test_writes_json_file_when_stdout_missing(self, tmp_path, monkeypatch):
        from launcher import __main__ as entry
        (tmp_path / "backend").mkdir()
        (tmp_path / "frontend").mkdir()
        monkeypatch.setattr(sys, "argv", ["nine-quarter", "--selfcheck",
                                          "--root", str(tmp_path)])
        monkeypatch.setattr(sys, "stdout", None)
        entry.main()
        out = tmp_path / "launcher-selfcheck.json"
        assert out.exists()
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["root"] == str(tmp_path)
        assert payload["needs_setup"] is True
