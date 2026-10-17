"""选框外观自检：颜色/粗细/长度生效，越界值被夹紧，绘制不崩。

用法：.venv\\Scripts\\python.exe tests\\25-frame-style.py
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
    frame = RegionFrame(QRect(0, 0, 420, 110))
    failures = 0

    def check(label: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        failures += 0 if ok else 1
        print(f"[{'OK' if ok else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")

    def paint() -> None:
        pixmap = QPixmap(frame.size())
        pixmap.fill(Qt.GlobalColor.transparent)
        frame.render(pixmap)

    # 1) 正常值
    frame.apply_style("#0078FF", 8, 64)
    top = next(rect for name, rect in frame._mid_shapes if name == "t")
    check(
        "应用蓝/8/64",
        frame._accent == "#0078FF" and frame._thick == 8 and frame._arm_base == 64,
        f"{frame._accent} {frame._thick} {frame._arm_base}",
    )
    check(
        "中点胶囊随粗细变高",
        abs(top.boundingRect().height() - 8) <= 1,
        str(top.boundingRect().getRect()),
    )
    paint()

    # 2) 越界值被夹紧
    frame.apply_style("#123456", 99, 999)
    check(
        "非法颜色回退为橙，数值夹紧",
        frame._accent == "#FFA800"
        and frame._thick == 8
        and frame._arm_base == 64,
        f"{frame._accent} {frame._thick} {frame._arm_base}",
    )
    frame.apply_style("#FFFFFF", 1, 1)
    check(
        "下限夹紧",
        frame._thick == 4 and frame._arm_base == 24,
        f"{frame._thick} {frame._arm_base}",
    )
    paint()

    # 3) 小选框仍然画得出来
    small = RegionFrame(QRect(0, 0, 160, 70))
    small.apply_style("#111111", 8, 64)
    pixmap = QPixmap(small.size())
    pixmap.fill(Qt.GlobalColor.transparent)
    small.render(pixmap)
    check("小选框极限参数可绘制", True)

    print(f"结果：{'全部通过' if failures == 0 else f'{failures} 项失败'}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
