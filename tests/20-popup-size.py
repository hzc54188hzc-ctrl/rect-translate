"""译文浮窗尺寸自检：长译文要自动变高并换行，不能被裁在 90px。

用法：.venv\\Scripts\\python.exe tests\\20-popup-size.py
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

    def check(label: str, ok: bool, detail: str) -> None:
        nonlocal failures
        failures += 0 if ok else 1
        print(f"[{'OK' if ok else 'FAIL'}] {label}: {detail}")

    popup.set_content("source", "短译文。", "")
    short_height = popup.height()

    medium = "这是一段用来验证自动换行与高度的译文。" * 12  # 约 240 字
    popup.set_content("source text", medium, "")
    medium_height = popup.height()
    check(
        "长译文自动变高",
        medium_height > short_height + 40,
        f"短={short_height} 中={medium_height}",
    )

    popup.show()
    _APP.processEvents()
    label = popup._translation
    document = label.document()
    document.setTextWidth(label.viewport().width())
    needed = int(document.size().height())
    visible = label.viewport().height()
    check(
        "按宽度换行且不裁切",
        label.viewport().width() > 250 and visible + 2 >= needed,
        f"视口 {label.viewport().width()}x{visible} 需要高 {needed}",
    )

    huge = "超长译文" * 1500
    popup.set_content("source text", huge, "")
    area = QGuiApplication.primaryScreen().availableGeometry()
    check(
        "超长文本不超过屏幕 75%",
        popup.height() <= int(area.height() * 0.75) + 1,
        f"高={popup.height()} 屏幕高={area.height()}",
    )

    popup.set_content("source text", medium, "")
    popup._user_sized = True
    popup.setFixedSize(400, 120)
    popup.set_content("source text", medium, "")  # 手动定过尺寸，不再自动变高
    locked = popup.height()
    popup._user_sized = False
    popup._resize_to_content()
    check(
        "恢复自动大小可用",
        locked == 120 and popup.height() > locked,
        f"手动锁定高={locked}，恢复后={popup.height()}",
    )

    popup.hide()
    print(f"结果：{'全部通过' if failures == 0 else f'{failures} 项失败'}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
