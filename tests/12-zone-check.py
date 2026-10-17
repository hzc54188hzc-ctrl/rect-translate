"""命中分区与缩放自检：直接问 RegionFrame「这个点算移动还是缩放」，不需要真实鼠标。

用法：.venv\\Scripts\\python.exe tests\\12-zone-check.py
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QApplication

from recttrans.frame import RegionFrame

_APP = None


def main() -> int:
    global _APP
    _APP = QApplication(sys.argv)
    frame = RegionFrame(QRect(0, 0, 560, 140))

    cases = [
        ("左上拐弯（应移动）", QPoint(4, 4), "move"),
        ("左上臂端（上边）", QPoint(26, 4), "tl"),
        ("左上臂端（左边）", QPoint(4, 26), "tl"),
        ("上边中点胶囊", QPoint(280, 4), "t"),
        ("下边中点胶囊", QPoint(280, 136), "b"),
        ("左边中点胶囊", QPoint(4, 70), "l"),
        ("右边中点胶囊", QPoint(556, 70), "r"),
        ("上边胶囊之间（窗口外）", QPoint(150, 4), "move"),
        ("右下拐弯（应移动）", QPoint(556, 136), "move"),
    ]

    failed = 0
    for label, point, expected in cases:
        actual = frame._zone(point)
        ok = actual == expected
        failed += 0 if ok else 1
        print(f"  {'OK ' if ok else 'FAIL'} {label:22} ({point.x()},{point.y()}) -> {actual}  期望 {expected}")

    # 胶囊之间不再有连接线：空隙不在窗口掩码里，鼠标会穿透
    gap_ok = not frame.mask().contains(QPoint(150, 4))
    mid_ok = frame.mask().contains(QPoint(280, 4))
    failed += 0 if gap_ok else 1
    failed += 0 if mid_ok else 1
    print(f"  {'OK ' if gap_ok else 'FAIL'} 胶囊之间留空（窗口外）")
    print(f"  {'OK ' if mid_ok else 'FAIL'} 中点胶囊仍在窗口内")

    print("\n--- 自由缩放自检（撤销等比限制）---")
    base = QRect(0, 0, 560, 140)
    scaling = [
        ("右下角横拖 +56（只改宽）", "br", QPoint(56, 0), (616, 140)),
        ("右下角纵拖 +14（只改高）", "br", QPoint(0, 14), (560, 154)),
        ("右下角斜拖 +56,+14（宽高各改）", "br", QPoint(56, 14), (616, 154)),
        ("左上角横拖 -56（右边不动）", "tl", QPoint(-56, 0), (616, 140)),
    ]
    for label, mode, delta, expected in scaling:
        frame._mode = mode
        rect = frame._resized(base, delta)
        ok = (rect.width(), rect.height()) == expected
        failed += 0 if ok else 1
        print(f"  {'OK ' if ok else 'FAIL'} {label:34} -> {rect.width()}x{rect.height()}  期望 {expected[0]}x{expected[1]}")

    total = len(cases) + len(scaling) + 2
    print(f"\n结果：{total - failed}/{total} 通过")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
