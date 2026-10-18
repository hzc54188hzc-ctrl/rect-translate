"""字幕回看自检：滚轮向上查看历史，3 秒后自动回到底部。

用法：.venv\\Scripts\\python.exe tests\\51-caption-scroll.py
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from PySide6.QtTest import QTest
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
    popup.show_caption()
    popup.set_caption_zh_lines([f"第 {index} 行字幕" for index in range(10)], display_lines=3)
    _APP.processEvents()
    try:
        bar = popup._translation.verticalScrollBar()
        check("历史内容可滚动", bar.maximum() > 0, str(bar.maximum()))
        check("默认停在最新", bar.value() >= bar.maximum() - 4, f"{bar.value()}/{bar.maximum()}")
        bar.setValue(0)
        _APP.processEvents()
        check("向上滚动被识别", popup._user_scrolled)
        QTest.qWait(3200)
        _APP.processEvents()
        check(
            "3 秒后自动回到底部",
            bar.value() >= bar.maximum() - 4 and not popup._user_scrolled,
            f"{bar.value()}/{bar.maximum()}",
        )
    finally:
        popup.hide()

    print(f"结果：{'全部通过' if failures == 0 else f'{failures} 项失败'}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
