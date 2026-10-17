"""控制条「翻译」按钮自检：存在、可点、不误触、不与其他段重叠。

用法：.venv\\Scripts\\python.exe tests\\23-controls.py
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from recttrans.controls import PADDING, ModeBar

_APP = None


def main() -> int:
    global _APP
    _APP = QApplication(sys.argv)
    bar = ModeBar()
    failures = 0

    def check(label: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        failures += 0 if ok else 1
        print(f"[{'OK' if ok else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")

    segments = bar._segments()
    translate = [rect for group, _v, rect in segments if group == "translate"]
    check("存在翻译按钮", len(translate) == 1, str([r.getRect() for r in translate]))

    rects = [rect for _g, _v, rect in segments]
    overlaps = [
        (a.getRect(), b.getRect())
        for index, a in enumerate(rects)
        for b in rects[index + 1 :]
        if a.intersects(b)
    ]
    check("各段不重叠", not overlaps, str(overlaps))
    check(
        "控制条宽度足够",
        bar.width() >= max(r.right() for r in rects) + PADDING,
        f"bar={bar.width()}",
    )

    fired: list[int] = []
    bar.translate_requested.connect(lambda: fired.append(1))
    QTest.mouseClick(bar, Qt.MouseButton.LeftButton, pos=translate[0].center())
    check("点击翻译触发一次", fired == [1], str(fired))

    manual = next(rect for group, value, rect in segments if value == "manual")
    QTest.mouseClick(bar, Qt.MouseButton.LeftButton, pos=manual.center())
    check("点选取不触发翻译", fired == [1], str(fired))

    print(f"结果：{'全部通过' if failures == 0 else f'{failures} 项失败'}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
