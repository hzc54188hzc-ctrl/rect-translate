"""浮窗最小尺寸自检：缩放手柄可拖、滚轮可滚译文。

用法：.venv\\Scripts\\python.exe tests\\52-popup-resize-scroll.py
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QApplication

from recttrans.popup import ResultPopup

_APP = None


def main() -> int:
    global _APP
    _APP = QApplication.instance() or QApplication(sys.argv)
    failures = 0

    def check(label: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        failures += 0 if ok else 1
        print(f"[{'OK' if ok else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")

    popup = ResultPopup()
    popup.set_content("source", "很长的译文内容。" * 60)
    popup._user_sized = True
    popup.setFixedSize(240, 90)
    popup.show()
    _APP.processEvents()
    try:
        handle = popup._resize_handle
        check("缩放手柄在窗口内", popup.rect().contains(handle.geometry()), str(handle.geometry()))
        center = handle.geometry().center()
        check(
            "缩放手柄在文字区域之上",
            popup.childAt(center) is handle,
            str(type(popup.childAt(center))),
        )

        start = handle.mapToGlobal(QPoint(5, 5))
        press = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(5, 5),
            QPointF(start),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        handle.mousePressEvent(press)
        end = start + QPoint(120, 60)
        move = QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(125, 65),
            QPointF(end),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        handle.mouseMoveEvent(move)
        _APP.processEvents()
        check(
            "最小尺寸下仍能放大",
            popup.width() > 240 and popup.height() > 90,
            f"{popup.width()}x{popup.height()}",
        )

        bar = popup._translation.verticalScrollBar()
        bar.setValue(0)
        wheel = QWheelEvent(
            QPointF(20, 20),
            QPointF(popup.mapToGlobal(QPoint(20, 20))),
            QPoint(0, 0),
            QPoint(0, -120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
        popup.wheelEvent(wheel)
        check("滚轮能滚动译文", bar.value() > 0, f"{bar.value()}/{bar.maximum()}")
    finally:
        popup.hide()

    print(f"结果：{'全部通过' if failures == 0 else f'{failures} 项失败'}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
