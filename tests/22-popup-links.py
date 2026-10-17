"""浮窗术语链接自检：蓝字渲染、点击打开搜索、拖动不误触链接。

用法：.venv\\Scripts\\python.exe tests\\22-popup-links.py
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

import recttrans.popup as popup_module
from recttrans.popup import ResultPopup

_APP = None


def _mouse(kind, local: QPointF, global_pos: QPointF, button, buttons) -> QMouseEvent:
    return QMouseEvent(kind, local, global_pos, button, buttons, Qt.KeyboardModifier.NoModifier)


def main() -> int:
    global _APP
    _APP = QApplication(sys.argv)
    failures = 0

    def check(label: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        failures += 0 if ok else 1
        print(f"[{'OK' if ok else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")

    opened: list[str] = []
    original_open = popup_module._open_url
    popup_module._open_url = opened.append
    popup = ResultPopup()
    try:
        popup.set_content(
            "source",
            "使用 Transformer 的注意力机制。",
            "",
            terms=[
                {"text": "Transformer", "query": "Transformer 论文", "kind": "术语"},
                {"text": "注意力机制", "query": "注意力机制 解释", "kind": "术语"},
            ],
        )
        popup.show()
        _APP.processEvents()
        label = popup._translation
        html = label.toHtml()
        check(
            "译文渲染成链接",
            html.count("href=") >= 2 and "Transformer" in html,
            f"links={html.count('href=')}",
        )
        check("链接交给程序打开", label.openExternalLinks() is False)

        popup._open_link("https://example.com/search?q=x")
        check("点击打开搜索", opened == ["https://example.com/search?q=x"], str(opened))

        # 文字区域不再拖动：按下 → 移动 30/20 → 松开，窗口必须不动
        start = popup.pos()
        local = QPointF(6, 6)
        QApplication.sendEvent(
            label,
            _mouse(QEvent.Type.MouseButtonPress, local, QPointF(100, 100),
                   Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton),
        )
        QApplication.sendEvent(
            label,
            _mouse(QEvent.Type.MouseMove, local, QPointF(130, 120),
                   Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton),
        )
        QApplication.sendEvent(
            label,
            _mouse(QEvent.Type.MouseButtonRelease, local, QPointF(130, 120),
                   Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton),
        )
        check(
            "文字上拖动不再移动窗口",
            popup.pos() == start,
            f"{start} -> {popup.pos()}",
        )
        check("文字拖动不算点击", opened == ["https://example.com/search?q=x"], str(opened))

        # 小抖动同样不移动
        before = popup.pos()
        QApplication.sendEvent(
            label,
            _mouse(QEvent.Type.MouseButtonPress, local, QPointF(200, 200),
                   Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton),
        )
        QApplication.sendEvent(
            label,
            _mouse(QEvent.Type.MouseMove, local, QPointF(202, 201),
                   Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton),
        )
        QApplication.sendEvent(
            label,
            _mouse(QEvent.Type.MouseButtonRelease, local, QPointF(202, 201),
                   Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton),
        )
        check("小抖动不移动窗口", popup.pos() == before, f"{before} -> {popup.pos()}")

        # 顶部胶囊存在、居中、位置在内容之上
        handle = popup._handle
        center = handle.geometry().center()
        check(
            "顶部拖动胶囊居中",
            abs(center.x() - popup.rect().center().x()) <= 1 and handle.geometry().top() < 20,
            f"胶囊 {handle.geometry().getRect()} 窗口 {popup.rect().getRect()}",
        )
        check("胶囊有拖动提示", handle.toolTip() == "拖动浮窗", handle.toolTip())
    finally:
        popup_module._open_url = original_open
        popup.hide()

    print(f"结果：{'全部通过' if failures == 0 else f'{failures} 项失败'}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
