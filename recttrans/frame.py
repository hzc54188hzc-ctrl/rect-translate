"""常驻矩形选框：由互不相连的胶囊组成，没有连接线。

构成：四角的回旋镖 + 四边中点的胶囊，中间留空，彼此不相接。

交互：
  - 拖四角回旋镖的拐弯处 = 移动
  - 拖回旋镖的臂端 = 对角缩放；拖四边中点胶囊 = 单边缩放
  - 双击 = 翻译一次；右键 = 菜单；Esc = 退出

穿透靠窗口形状实现：掩码只保留这些胶囊形状，其余区域不属于窗口，
鼠标事件自然落到下面的应用上。
"""

from __future__ import annotations

import time

from PySide6.QtCore import QPoint, QPointF, QRect, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QBitmap,
    QColor,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPen,
    QRegion,
)
from PySide6.QtWidgets import QMenu, QWidget

from recttrans.capture import exclude_from_capture

THICK = 6  # 胶囊段的总粗度（含两侧各 1px 白边），与浮窗拖动胶囊一致
# 骨架长度 42 + 两端各 3px 圆头 = 视觉 48，与浮窗拖动胶囊一致
CORNER_ARM = 42  # 四角回旋镖：单条臂的骨架长（小选框会按比例缩短）
MID_CAPSULE_LEN = 42  # 四边中点胶囊的骨架长（按该边剩余空间截断）
CAPSULE_GAP = 10  # 角臂与中点胶囊之间的视觉空隙（骨架间距再加 THICK 的圆头）
MOVE_RADIUS = 14  # 四角回旋镖「拐弯处」的移动命中半径
INSET = 4  # 骨架离矩形边界的距离（保证整根胶囊都在框内）
MIN_WIDTH = 160
MIN_HEIGHT = 70

ACCENT_COLOR = "#FFA800"
STYLE_COLORS = ("#FFA800", "#0078FF", "#111111", "#FFFFFF")
STYLE_THICKNESS = (4, 6, 8)
STYLE_LENGTHS = (32, 48, 64)

DOUBLE_CLICK_SECONDS = 0.45
DOUBLE_CLICK_SLOP = 6

_CURSORS = {
    "tl": Qt.CursorShape.SizeFDiagCursor,
    "br": Qt.CursorShape.SizeFDiagCursor,
    "tr": Qt.CursorShape.SizeBDiagCursor,
    "bl": Qt.CursorShape.SizeBDiagCursor,
    "t": Qt.CursorShape.SizeVerCursor,
    "b": Qt.CursorShape.SizeVerCursor,
    "l": Qt.CursorShape.SizeHorCursor,
    "r": Qt.CursorShape.SizeHorCursor,
    "move": Qt.CursorShape.SizeAllCursor,
}


def _stroke(path: QPainterPath, width: float) -> QPainterPath:
    """把骨架线加粗成圆头圆角的实心胶囊轮廓。"""
    stroker = QPainterPathStroker()
    stroker.setWidth(width)
    stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
    stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return stroker.createStroke(path)


class RegionFrame(QWidget):
    translate_requested = Signal()
    quit_requested = Signal()
    geometry_changed = Signal(QRect)
    auto_toggled = Signal(bool)

    def __init__(self, geometry: QRect, capture_excluded: bool = True) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setMinimumSize(MIN_WIDTH, MIN_HEIGHT)
        self.setGeometry(geometry)
        self.setMouseTracking(True)

        self._capture_excluded = capture_excluded
        self._auto_on = True
        self._mode = "move"
        self._accent = ACCENT_COLOR
        self._thick = THICK
        self._arm_base = CORNER_ARM
        self._mid_base = MID_CAPSULE_LEN
        self._press_global = QPoint()
        self._press_geometry = QRect()
        self._last_press_time = 0.0
        self._last_press_pos = QPoint()

        # (名称, 实心胶囊, 含 1px 白边的外轮廓)
        self._corner_shapes: list[tuple[str, QPainterPath]] = []
        self._mid_shapes: list[tuple[str, QPainterPath]] = []
        self._apply_mask()

    def apply_style(self, color: str, thickness: int, length: int) -> None:
        """应用外观参数；先夹紧再重建形状，避免用户填出破图。"""
        self._accent = color if color in STYLE_COLORS else ACCENT_COLOR
        self._thick = max(4, min(8, int(thickness)))
        self._arm_base = max(24, min(64, int(length)))
        self._mid_base = self._arm_base
        self._apply_mask()
        self.update()

    # ---------- 骨架与形状 ----------

    def _arm_length(self) -> int:
        """按最短边缩短臂长，并给中点胶囊预留 12px + 两侧各 10px 空隙。"""
        usable = min(self.width(), self.height()) - 2 * INSET
        reserve = 2 * (CAPSULE_GAP + self._thick)
        return max(12, min(self._arm_base, (usable - 12 - reserve) // 2))

    def _corner_bones(self) -> list[tuple[str, QPainterPath]]:
        width, height = self.width(), self.height()
        arm, inset = self._arm_length(), INSET
        bones: list[tuple[str, QPainterPath]] = []
        for name in ("tl", "tr", "bl", "br"):
            path = QPainterPath()
            if name == "tl":
                path.moveTo(inset, arm)
                path.lineTo(inset, inset)
                path.lineTo(arm, inset)
            elif name == "tr":
                path.moveTo(width - inset, arm)
                path.lineTo(width - inset, inset)
                path.lineTo(width - arm, inset)
            elif name == "bl":
                path.moveTo(inset, height - arm)
                path.lineTo(inset, height - inset)
                path.lineTo(arm, height - inset)
            else:
                path.moveTo(width - inset, height - arm)
                path.lineTo(width - inset, height - inset)
                path.lineTo(width - arm, height - inset)
            bones.append((name, path))
        return bones

    def _mid_bones(self) -> list[tuple[str, QPainterPath]]:
        """四边中点的小胶囊：落在 1px 连接线上，拖它即可缩放对应方向。"""
        width, height = self.width(), self.height()
        arm = self._arm_length()
        # 两侧各留 CAPSULE_GAP，保证中点胶囊与角臂互不相接
        reserve = 2 * (CAPSULE_GAP + self._thick)
        top_len = min(self._mid_base, width - 2 * INSET - 2 * arm - reserve)
        side_len = min(self._mid_base, height - 2 * INSET - 2 * arm - reserve)
        center_x = width / 2
        center_y = height / 2
        # 4px 粗的胶囊用整数中心才清晰（1px 线才需要半像素）
        top_y = INSET
        bottom_y = height - INSET
        left_x = INSET
        right_x = width - INSET

        items: list[tuple[str, QPainterPath]] = []

        if top_len >= 12:
            top = QPainterPath()
            top.moveTo(center_x - top_len / 2, top_y)
            top.lineTo(center_x + top_len / 2, top_y)
            items.append(("t", top))

            bottom = QPainterPath()
            bottom.moveTo(center_x - top_len / 2, bottom_y)
            bottom.lineTo(center_x + top_len / 2, bottom_y)
            items.append(("b", bottom))

        if side_len >= 12:
            left = QPainterPath()
            left.moveTo(left_x, center_y - side_len / 2)
            left.lineTo(left_x, center_y + side_len / 2)
            items.append(("l", left))

            right = QPainterPath()
            right.moveTo(right_x, center_y - side_len / 2)
            right.lineTo(right_x, center_y + side_len / 2)
            items.append(("r", right))
        return items

    def _corner_points(self) -> dict[str, QPointF]:
        width, height = self.width(), self.height()
        return {
            "tl": QPointF(INSET, INSET),
            "tr": QPointF(width - INSET, INSET),
            "bl": QPointF(INSET, height - INSET),
            "br": QPointF(width - INSET, height - INSET),
        }

    def _apply_mask(self) -> None:
        width, height = self.width(), self.height()
        bitmap = QBitmap(width, height)
        bitmap.clear()
        painter = QPainter(bitmap)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(Qt.GlobalColor.color1)

        self._corner_shapes = []
        for name, bone in self._corner_bones():
            outer = _stroke(bone, self._thick)
            painter.drawPath(outer)
            self._corner_shapes.append((name, outer))

        self._mid_shapes = []
        for name, bone in self._mid_bones():
            outer = _stroke(bone, self._thick)
            painter.drawPath(outer)
            self._mid_shapes.append((name, outer))

        painter.end()
        self.setMask(QRegion(bitmap))

    def set_auto_checked(self, checked: bool) -> None:
        self._auto_on = checked

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_mask()
        self.geometry_changed.emit(self.geometry())

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        self.geometry_changed.emit(self.geometry())

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._capture_excluded:
            exclude_from_capture(self)

    def paintEvent(self, event) -> None:  # noqa: ARG002
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self._accent))
        for _name, outer in self._corner_shapes:
            painter.drawPath(outer)
        for _name, outer in self._mid_shapes:
            painter.drawPath(outer)

    # ---------- 命中判定 ----------

    def _zone(self, pos: QPoint) -> str:
        point = QPointF(pos)
        corner_points = self._corner_points()
        for name, outer in self._corner_shapes:
            if outer.contains(point):
                corner = corner_points[name]
                delta = point - corner
                # 拐弯处 = 移动；臂端 = 缩放
                if (delta.x() ** 2 + delta.y() ** 2) ** 0.5 <= MOVE_RADIUS:
                    return "move"
                return name
        for name, outer in self._mid_shapes:
            if outer.contains(point):
                return name
        return "move"

    # ---------- 交互 ----------

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return

        global_pos = event.globalPosition().toPoint()
        now = time.monotonic()
        if (
            now - self._last_press_time <= DOUBLE_CLICK_SECONDS
            and (global_pos - self._last_press_pos).manhattanLength() <= DOUBLE_CLICK_SLOP
        ):
            self._last_press_time = 0.0
            self.translate_requested.emit()
            event.accept()
            return

        self._last_press_time = now
        self._last_press_pos = global_pos
        self._mode = self._zone(event.position().toPoint())
        self._press_global = global_pos
        self._press_geometry = self.geometry()
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        self.setCursor(_CURSORS[self._zone(event.position().toPoint())])
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return

        delta = event.globalPosition().toPoint() - self._press_global
        if self._mode == "move":
            target = self._press_geometry.topLeft() + delta
            if target != self.pos():
                self._last_press_time = 0.0
                self.move(target)
        else:
            rect = self._resized(self._press_geometry, delta)
            if rect != self.geometry():
                self._last_press_time = 0.0
                self.setGeometry(rect)
        event.accept()

    def _resized(self, base: QRect, delta: QPoint) -> QRect:
        """四角自由缩放：横向只改宽、纵向只改高（撤销等比限制）。"""
        rect = QRect(base)
        if "l" in self._mode:
            rect.setLeft(base.left() + delta.x())
        if "r" in self._mode:
            rect.setRight(base.right() + delta.x())
        if "t" in self._mode:
            rect.setTop(base.top() + delta.y())
        if "b" in self._mode:
            rect.setBottom(base.bottom() + delta.y())

        if rect.width() < MIN_WIDTH:
            if "l" in self._mode:
                rect.setLeft(rect.right() - MIN_WIDTH + 1)
            else:
                rect.setRight(rect.left() + MIN_WIDTH - 1)
        if rect.height() < MIN_HEIGHT:
            if "t" in self._mode:
                rect.setTop(rect.bottom() - MIN_HEIGHT + 1)
            else:
                rect.setBottom(rect.top() + MIN_HEIGHT - 1)
        return rect

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.translate_requested.emit()
            event.accept()

    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)
        translate_action = QAction("翻译一次（等同双击选框）", menu)
        auto_action = QAction("自动翻译（内容变化时）", menu)
        auto_action.setCheckable(True)
        auto_action.setChecked(self._auto_on)
        quit_action = QAction("隐藏到托盘", menu)
        menu.addAction(translate_action)
        menu.addAction(auto_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        chosen = menu.exec(event.globalPos())
        if chosen is translate_action:
            self.translate_requested.emit()
        elif chosen is auto_action:
            self._auto_on = auto_action.isChecked()
            self.auto_toggled.emit(self._auto_on)
        elif chosen is quit_action:
            self.quit_requested.emit()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.quit_requested.emit()
            event.accept()
        else:
            super().keyPressEvent(event)
