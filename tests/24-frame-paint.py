"""选框绘制冒烟测试：真实跑一次 paintEvent，防止引用已删除变量之类的运行时错误。

用法：.venv\\Scripts\\python.exe tests\\24-frame-paint.py
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

from recttrans.frame import RegionFrame

_APP = None


def main() -> int:
    global _APP
    _APP = QApplication(sys.argv)
    failures = 0

    try:
        for width, height in ((420, 110), (160, 70)):
            frame = RegionFrame(QRect(0, 0, width, height))
            pixmap = QPixmap(frame.size())
            pixmap.fill(Qt.GlobalColor.transparent)
            frame.render(pixmap)
            print(f"[OK] {width}x{height} 绘制通过")
    except Exception as exc:  # noqa: BLE001
        failures += 1
        print(f"[FAIL] 绘制抛异常：{type(exc).__name__}: {exc}")

    print(f"结果：{'全部通过' if failures == 0 else f'{failures} 项失败'}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
