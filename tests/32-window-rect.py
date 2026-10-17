"""抓图坐标自检：window_rect 返回物理像素矩形（100% 缩放下等于几何）。

用法：.venv\\Scripts\\python.exe tests\\32-window-rect.py
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication

from recttrans import capture
from recttrans.frame import RegionFrame

_APP = None


def main() -> int:
    global _APP
    _APP = QApplication(sys.argv)
    failures = 0

    def check(label: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        failures += 0 if ok else 1
        print(f"[{'OK' if ok else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")

    frame = RegionFrame(QRect(100, 120, 300, 200))
    frame.show()
    _APP.processEvents()
    try:
        x, y, width, height = capture.window_rect(frame)
        ratio = frame.devicePixelRatioF()
        if abs(ratio - 1.0) < 1e-6:
            check(
                "100% 缩放下与几何一致",
                (x, y, width, height) == (100, 120, 300, 200),
                f"{(x, y, width, height)}",
            )
        else:
            check(
                "高缩放下返回物理像素",
                width >= 300 and height >= 200,
                f"{(x, y, width, height)} dpr={ratio}",
            )
        check("尺寸为正", width > 0 and height > 0, f"{width}x{height}")
    finally:
        frame.hide()

    print(f"结果：{'全部通过' if failures == 0 else f'{failures} 项失败'}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
