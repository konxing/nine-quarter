"""生成启动器图标（纯标准库，不依赖 Pillow）。

深色圆角底 + 三根上涨 K 线柱，输出多尺寸 ICO（内含 PNG）。
运行：python -m launcher.make_icon
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

BG = (14, 21, 32, 255)
CARD = (22, 32, 46, 255)
BLUE = (59, 130, 246, 255)
GREEN = (34, 197, 94, 255)
RED = (239, 68, 68, 255)


def _png(width: int, height: int, pixels: bytearray) -> bytes:
    raw = bytearray()
    stride = width * 4
    for y in range(height):
        raw.append(0)
        raw.extend(pixels[y * stride:(y + 1) * stride])

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))


def _draw(size: int) -> bytes:
    px = bytearray(size * size * 4)
    r = size * 0.22
    bars = [(0.20, 0.42, RED), (0.44, 0.62, BLUE), (0.68, 0.82, GREEN)]
    for y in range(size):
        for x in range(size):
            # 圆角矩形底
            dx = min(x, size - 1 - x)
            dy = min(y, size - 1 - y)
            inside = True
            if dx < r and dy < r:
                inside = (r - dx) ** 2 + (r - dy) ** 2 <= r * r
            if not inside:
                continue
            color = BG
            if size * 0.08 < x < size * 0.92 and size * 0.08 < y < size * 0.92:
                color = CARD
            for left, top, c in bars:
                w = size * 0.13
                x0 = size * left
                if x0 <= x <= x0 + w and size * (1 - top) <= y <= size * 0.86:
                    color = c
                    break
            i = (y * size + x) * 4
            px[i:i + 4] = bytes(color)
    return _png(size, size, px)


def build_icon(path: Path) -> Path:
    sizes = [16, 32, 48, 64, 128, 256]
    images = [(s, _draw(s)) for s in sizes]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries = b""
    blob = b""
    for s, data in images:
        entries += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32,
                               len(data), offset)
        blob += data
        offset += len(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + entries + blob)
    return path


if __name__ == "__main__":
    out = build_icon(Path(__file__).resolve().parent / "icon.ico")
    print(f"图标已生成: {out}")
