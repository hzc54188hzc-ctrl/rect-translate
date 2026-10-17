"""译文浮窗位置记忆自检：放好后不跟随锚点、重置后回到锚点、越界夹回屏幕。

用法：.venv\\Scripts\\python.exe tests\\19-popup-pin.py
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QPoint
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from recttrans.popup import ResultPopup

_APP = None


def main() -> int:
    global _APP
    _APP = QApplication(sys.argv)
    popup = ResultPopup()
    popup.set_content("source", "译文", "")
    failures = 0

    def check(label: str, ok: bool, detail: str) -> None:
        nonlocal failures
        failures += 0 if ok else 1
        print(f"[{'OK' if ok else 'FAIL'}] {label}: {detail}")

    # 1) 已记住位置：锚点再变（移动选框）也不动
    popup.set_saved_position(QPoint(300, 300))
    popup.place_near(QPoint(10, 10))
    check("移动选框后浮窗不动", popup.pos() == QPoint(300, 300), str(popup.pos()))

    # 2) 重置位置：回到锚点下方
    popup.clear_saved_position()
    popup.place_near(QPoint(500, 400))
    check(
        "重置后回到锚点下方",
        popup.y() < 400 and popup.x() <= 500,
        f"({popup.x()}, {popup.y()})",
    )

    # 3) 越界（左上）
    popup.set_saved_position(QPoint(-500, -500))
    popup.place_saved()
    area = QGuiApplication.primaryScreen().availableGeometry()
    check(
        "负坐标夹回屏幕",
        popup.x() >= area.left() and popup.y() >= area.top(),
        f"({popup.x()}, {popup.y()}) 屏幕 {area.getRect()}",
    )

    # 4) 越界（右下）
    popup.set_saved_position(QPoint(9999, 9999))
    popup.place_saved()
    check(
        "超出右下夹回屏幕",
        popup.x() + popup.width() <= area.right() + 1
        and popup.y() + popup.height() <= area.bottom() + 1,
        f"({popup.x()}, {popup.y()}) 尺寸 {popup.width()}x{popup.height()}",
    )

    print(f"结果：{'全部通过' if failures == 0 else f'{failures} 项失败'}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
