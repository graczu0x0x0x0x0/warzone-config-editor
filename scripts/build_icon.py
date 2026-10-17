"""Render ``src/wzce/data/icons/app.svg`` to ``app.png`` (256 px) and a multi-size ``app.ico``.

Run after changing the SVG:  ``uv run python scripts/build_icon.py``

The ICO is assembled by hand (PNG-compressed entries, supported since Windows Vista)
because Qt's ICO writer stores a single image only. Sizes cover the taskbar, title
bar, Explorer views and the installer/exe properties dialog.
"""

from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ICON_DIR = Path(__file__).resolve().parent.parent / "src" / "wzce" / "data" / "icons"
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def render_png(renderer: QSvgRenderer, size: int) -> bytes:
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(data.data())


def build_ico(images: list[tuple[int, bytes]]) -> bytes:
    header = struct.pack("<HHH", 0, 1, len(images))  # reserved, type=icon, count
    offset = len(header) + 16 * len(images)
    entries, payload = b"", b""
    for size, png in images:
        dim = 0 if size >= 256 else size  # 0 means 256 in the ICO directory
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset + len(payload))
        payload += png
    return header + entries + payload


def main() -> int:
    QGuiApplication(sys.argv)
    renderer = QSvgRenderer(str(ICON_DIR / "app.svg"))
    if not renderer.isValid():
        print("app.svg could not be parsed", file=sys.stderr)
        return 1
    images = [(size, render_png(renderer, size)) for size in SIZES]
    (ICON_DIR / "app.png").write_bytes(images[-1][1])
    (ICON_DIR / "app.ico").write_bytes(build_ico(images))
    print(f"wrote app.png and app.ico ({', '.join(str(s) for s, _ in images)} px)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
