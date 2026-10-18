"""功能浮窗：选取 / 自动 / 翻译 / 同传 / 配色 / 设置 / 关闭。

独立小窗口，不画进选框里：选框内部必须完全穿透，按钮塞进去会挡住内容。
启动时只显示它，点「选取」「自动」或「翻译」才把选框叫出来。
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget

BG = "#FFFFFF"
BORDER = "#E2E8F0"
TEXT = "#111111"
MUTED = "#6B7280"
ACCENT = "#FFA800"
HOVER = "#F8FAFC"

PADDING = 4
HEIGHT = 18
RADIUS = 13
FONT_PT = 8.0
GRIP_WIDTH = 12

_MODE = 26
_ACTION = 34
_THEME = 17
_ICON = 16
_GAP = 2
_GROUP = 7


class ModeBar(QWidget):
    mode_changed = Signal(str)  # "manual" | "auto"
    theme_changed = Signal(str)  # "light" | "dark"
    translate_requested = Signal()
    caption_requested = Signal()
    close_frame_requested = Signal()
    settings_requested = Signal()
    quit_requested = Signal()

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._mode = "auto"
        self._theme = "light"
        self._caption_on = False
        self._hover: str | None = None
        self._drag_from: QPoint | None = None
        self._window_from: QPoint | None = None

        last = self._segments()[-1][2]
        self.setFixedSize(last.right() + 1 + PADDING, HEIGHT + PADDING * 2)

    # ---------- 状态 ----------

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        self.update()

    def set_theme(self, theme: str) -> None:
        self._theme = theme
        self.update()

    def set_caption_active(self, active: bool) -> None:
        self._caption_on = active
        self.update()

    def _grip_rect(self) -> QRect:
        return QRect(PADDING, PADDING, GRIP_WIDTH - 2, HEIGHT)

    def _segments(self) -> list[tuple[str, str, QRect]]:
        """(分组, 取值, 矩形)。"""
        top = PADDING
        x = PADDING + GRIP_WIDTH
        items: list[tuple[str, str, QRect]] = []

        def add(group: str, value: str, width: int, gap: int = _GAP) -> None:
            nonlocal x
            items.append((group, value, QRect(x, top, width, HEIGHT)))
            x += width + gap

        add("frameclose", "frameclose", _ICON, _GROUP)
        add("mode", "manual", _MODE)
        add("mode", "auto", _MODE, _GROUP)
        add("translate", "translate", _ACTION)
        add("caption", "caption", _ACTION, _GROUP)
        add("theme", "light", _THEME)
        add("theme", "dark", _THEME, _GROUP)
        add("settings", "settings", _ICON)
        add("quit", "quit", _ICON, 0)
        return items

    # ---------- 外观 ----------

    def paintEvent(self, event) -> None:  # noqa: ARG002
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 轻投影：三层足够把白面板从浅色视频里托起来，不做大面积模糊。
        painter.setPen(Qt.PenStyle.NoPen)
        for step, alpha in ((3, 8), (2, 10), (1, 12)):
            shadow = QRectF(self.rect()).adjusted(0.5, 0.5 + step, -0.5, -0.5 + step)
            painter.setBrush(QColor(15, 23, 42, alpha))
            painter.drawRoundedRect(shadow, RADIUS + step * 0.4, RADIUS + step * 0.4)

        panel = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -1.5)
        painter.setBrush(QColor(BG))
        painter.setPen(QPen(QColor(BORDER), 1))
        painter.drawRoundedRect(panel, RADIUS, RADIUS)

        # 左侧握把：两条短线，按住可拖动整个浮窗。
        grip = self._grip_rect()
        painter.setPen(QPen(QColor(148, 163, 184), 1.2))
        center = grip.center()
        painter.drawLine(
            QPointF(grip.left() + 3, center.y() - 2.5),
            QPointF(grip.right() - 3, center.y() - 2.5),
        )
        painter.drawLine(
            QPointF(grip.left() + 3, center.y() + 2.5),
            QPointF(grip.right() - 3, center.y() + 2.5),
        )

        font = QFont()
        font.setPointSizeF(FONT_PT)
        painter.setFont(font)

        labels = {
            "manual": "选取",
            "auto": "自动",
            "light": "白",
            "dark": "黑",
            "translate": "翻译",
            "caption": "同传",
        }
        for group, value, rect in self._segments():
            if group == "frameclose":
                self._paint_frame_close(painter, rect, value)
                continue
            if group == "settings":
                self._paint_gear(painter, rect, value)
                continue
            if group == "quit":
                self._paint_close(painter, rect)
                continue

            active = False
            if group == "mode":
                active = value == self._mode
            elif group == "theme":
                active = value == self._theme
            elif group == "caption":
                active = self._caption_on
            primary = group == "translate" or (group == "caption" and self._caption_on)

            if primary or active:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(ACCENT))
                painter.drawRoundedRect(QRectF(rect), HEIGHT / 2, HEIGHT / 2)
                painter.setPen(QColor(TEXT))
            else:
                if self._hover == value:
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor(HOVER))
                    painter.drawRoundedRect(QRectF(rect), HEIGHT / 2, HEIGHT / 2)
                if group == "caption":
                    painter.setPen(QPen(QColor(ACCENT), 1.2))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawRoundedRect(
                        QRectF(rect).adjusted(0.6, 0.6, -0.6, -0.6),
                        HEIGHT / 2,
                        HEIGHT / 2,
                    )
                    painter.setPen(QColor("#B45309"))
                else:
                    painter.setPen(QColor(MUTED))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, labels[value])

    def _paint_gear(self, painter: QPainter, rect: QRect, value: str) -> None:
        if self._hover == value:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(HOVER))
            painter.drawRoundedRect(QRectF(rect), HEIGHT / 2, HEIGHT / 2)
        center = QRectF(rect).center()
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(MUTED), 1.4))
        painter.drawEllipse(center, 4.0, 4.0)
        painter.setPen(QPen(QColor(MUTED), 1.5))
        for index in range(8):
            painter.save()
            painter.translate(center)
            painter.rotate(index * 45)
            painter.drawLine(QPointF(0, -4.8), QPointF(0, -6.2))
            painter.restore()

    def _paint_frame_close(self, painter: QPainter, rect: QRect, value: str) -> None:
        """只关选框的小叉：外面套一个方框，和右侧的全局关闭区分。"""
        if self._hover == value:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(HOVER))
            painter.drawRoundedRect(QRectF(rect), HEIGHT / 2, HEIGHT / 2)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(MUTED), 1.2))
        box = QRectF(rect).adjusted(4.0, 4.0, -4.0, -4.0)
        painter.drawRoundedRect(box, 2.0, 2.0)
        painter.setPen(QPen(QColor(MUTED), 1.2))
        inset = 2.2
        painter.drawLine(
            QPointF(box.left() + inset, box.top() + inset),
            QPointF(box.right() - inset, box.bottom() - inset),
        )
        painter.drawLine(
            QPointF(box.right() - inset, box.top() + inset),
            QPointF(box.left() + inset, box.bottom() - inset),
        )

    def _paint_close(self, painter: QPainter, rect: QRect) -> None:
        if self._hover == "quit":
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(HOVER))
            painter.drawRoundedRect(QRectF(rect), HEIGHT / 2, HEIGHT / 2)
        painter.setPen(QPen(QColor(MUTED), 1.4))
        inset = 5
        painter.drawLine(
            rect.left() + inset,
            rect.top() + inset,
            rect.right() - inset,
            rect.bottom() - inset,
        )
        painter.drawLine(
            rect.right() - inset,
            rect.top() + inset,
            rect.left() + inset,
            rect.bottom() - inset,
        )

    # ---------- 交互与定位 ----------

    def _hit(self, point: QPoint) -> tuple[str, str] | None:
        for group, value, rect in self._segments():
            if rect.contains(point):
                return group, value
        return None

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        point = event.position().toPoint()
        if self._grip_rect().contains(point):
            self._drag_from = event.globalPosition().toPoint()
            self._window_from = self.pos()
            self.setCursor(Qt.CursorShape.SizeAllCursor)
            event.accept()
            return
        hit = self._hit(point)
        if hit is None:
            return
        group, value = hit
        if group == "quit":
            self.quit_requested.emit()
        elif group == "frameclose":
            self.close_frame_requested.emit()
        elif group == "translate":
            self.translate_requested.emit()
        elif group == "caption":
            self.caption_requested.emit()
        elif group == "settings":
            self.settings_requested.emit()
        elif group == "mode":
            self.set_mode(value)
            self.mode_changed.emit(value)
        else:
            self.set_theme(value)
            self.theme_changed.emit(value)
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_from is not None and self._window_from is not None:
            delta = event.globalPosition().toPoint() - self._drag_from
            self.move(self._window_from + delta)
            event.accept()
            return
        hit = self._hit(event.position().toPoint())
        hover = hit[1] if hit is not None else None
        if hover != self._hover:
            self._hover = hover
            self.setCursor(
                Qt.CursorShape.PointingHandCursor
                if hover is not None
                else Qt.CursorShape.ArrowCursor
            )
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_from is not None:
            self._drag_from = None
            self._window_from = None
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            event.accept()

    def leaveEvent(self, event) -> None:
        if self._hover is not None:
            self._hover = None
            self.update()

    def place_default(self) -> None:
        """启动位置：主屏右上角，留出 24px 边距。"""
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        self.move(area.right() - self.width() - 24, area.top() + 24)

    def place_for(self, frame_rect: QRect) -> None:
        """贴在选框右上角外侧；上方放不下就放下面。"""
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        x = frame_rect.right() - self.width() + 1
        y = frame_rect.top() - self.height() - 8
        if y < area.top():
            y = frame_rect.bottom() + 8
        x = max(area.left(), min(x, area.right() - self.width()))
        y = max(area.top(), min(y, area.bottom() - self.height()))
        self.move(x, y)
