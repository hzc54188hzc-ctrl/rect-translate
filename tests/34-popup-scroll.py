"""长译文自检：浮窗封顶 75% 屏高，超出部分通过滚动条查看。

用法：.venv\\Scripts\\python.exe tests\\34-popup-scroll.py
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from recttrans.popup import ResultPopup

_APP = None


def main() -> int:
    global _APP
    _APP = QApplication(sys.argv)
    popup = ResultPopup()
    failures = 0

    def check(label: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        failures += 0 if ok else 1
        print(f"[{'OK' if ok else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")

    long_text = "这是一段用于验证长译文滚动的文字。" * 300
    popup.set_content("source", long_text, "")
    popup.show()
    _APP.processEvents()
    try:
        area = QGuiApplication.primaryScreen().availableGeometry()
        check(
            "浮窗不超过屏幕 75%",
            popup.height() <= int(area.height() * 0.75) + 1,
            f"高={popup.height()} 屏幕={area.height()}",
        )
        bar = popup._translation.verticalScrollBar()
        check(
            "出现垂直滚动条",
            bar.maximum() > 0,
            f"max={bar.maximum()}",
        )
        popup._translation.verticalScrollBar().setValue(bar.maximum())
        check(
            "可以滚到底",
            popup._translation.verticalScrollBar().value() == bar.maximum(),
        )
    finally:
        popup.hide()

    print(f"结果：{'全部通过' if failures == 0 else f'{failures} 项失败'}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
