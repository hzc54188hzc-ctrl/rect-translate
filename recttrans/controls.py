"""选框旁的迷你控制条：切换「选取 / 自动」与悬浮窗配色「白 / 黑」。

做成一个独立小窗口而不是画进选框里：选框的窗口形状只保留边框与抓手，
把按钮塞进去会破坏「内部完全穿透」这件事。
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget

BG = "#FFFFFF"
BORDER = "#E2E8F0"
TEXT = "#111111"
MUTED = "#6B7280"
ACCENT = "#FFA800"

PADDING = 4
SEGMENT_HEIGHT = 18
GROUP_GAP = 6
RADIUS = 13
FONT_PT = 8.0

_WIDE = 30  # 选取 / 自动
_NARROW = 20  # 白 / 黑
_GEAR = 18  # 设置（齿轮图标）
_QUIT = 18  # 退出


class ModeBar(QWidget):
    mode_changed = Signal(str)  # "manual" | "auto"
    theme_changed = Signal(str)  # "light" | "dark"
    translate_requested = Signal()
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
        self._hover_translate = False

        last = self._segments()[-1][2]
        self.setFixedSize(last.right() + 1 + PADDING, SEGMENT_HEIGHT + PADDING * 2)

    # ---------- 状态 ----------

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        self.update()

    def set_theme(self, theme: str) -> None:
        self._theme = theme
        self.update()

    def _segments(self) -> list[tuple[str, str, QRect]]:
        """(分组, 取值, 矩形)。"""
        top = PADDING
        x = PADDING
        items = [
            ("mode", "manual", QRect(x, top, _WIDE, SEGMENT_HEIGHT)),
        ]
        x += _WIDE + 2
        items.append(("mode", "auto", QRect(x, top, _WIDE, SEGMENT_HEIGHT)))
        x += _WIDE + GROUP_GAP
        items.append(("translate", "translate", QRect(x, top, _WIDE, SEGMENT_HEIGHT)))
        x += _WIDE + GROUP_GAP
        items.append(("theme", "light", QRect(x, top, _NARROW, SEGMENT_HEIGHT)))
        x += _NARROW + 2
        items.append(("theme", "dark", QRect(x, top, _NARROW, SEGMENT_HEIGHT)))
        x += _NARROW + GROUP_GAP
        items.append(("settings", "settings", QRect(x, top, _GEAR, SEGMENT_HEIGHT)))
        x += _GEAR + GROUP_GAP
        items.append(("quit", "quit", QRect(x, top, _QUIT, SEGMENT_HEIGHT)))
        return items

    # ---------- 外观 ----------

    def paintEvent(self, event) -> None:  # noqa: ARG002
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        panel = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setBrush(QColor(BG))
        painter.setPen(QPen(QColor(BORDER), 1))
        painter.drawRoundedRect(panel, RADIUS, RADIUS)

        font = QFont()
        font.setPointSizeF(FONT_PT)
        painter.setFont(font)

        labels = {
            "manual": "选取",
            "auto": "自动",
            "light": "白",
            "dark": "黑",
        }
        for group, value, rect in self._segments():
            if group == "translate":
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(
                    QColor(ACCENT).lighter(106) if self._hover_translate else QColor(ACCENT)
                )
                painter.drawRoundedRect(QRectF(rect), SEGMENT_HEIGHT / 2, SEGMENT_HEIGHT / 2)
                painter.setPen(QColor(TEXT))
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "翻译")
                continue
            if group == "settings":
                # 齿轮：一个圆环 + 8 根短齿（18px 内画清，不用 emoji / 位图）
                center = QRectF(rect).center()
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(QColor(MUTED), 1.5))
                painter.drawEllipse(center, 4.4, 4.4)
                painter.setPen(QPen(QColor(MUTED), 1.7))
                for index in range(8):
                    painter.save()
                    painter.translate(center)
                    painter.rotate(index * 45)
                    painter.drawLine(QPointF(0, -5.0), QPointF(0, -6.6))
                    painter.restore()
                continue
            if group == "quit":
                painter.setPen(QPen(QColor(MUTED), 1.4))
                inset = 5
                painter.drawLine(
                    rect.left() + inset, rect.top() + inset, rect.right() - inset, rect.bottom() - inset
                )
                painter.drawLine(
                    rect.right() - inset, rect.top() + inset, rect.left() + inset, rect.bottom() - inset
                )
                continue
            active = (value == self._mode) if group == "mode" else (value == self._theme)
            if active:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(ACCENT))
                painter.drawRoundedRect(QRectF(rect), SEGMENT_HEIGHT / 2, SEGMENT_HEIGHT / 2)
                painter.setPen(QColor(TEXT))
            else:
                painter.setPen(QColor(MUTED))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, labels[value])

    # ---------- 交互与定位 ----------

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        point = event.position().toPoint()
        for group, value, rect in self._segments():
            if rect.contains(point):
                if group == "quit":
                    self.quit_requested.emit()
                elif group == "translate":
                    self.translate_requested.emit()
                elif group == "settings":
                    self.settings_requested.emit()
                elif group == "mode":
                    self.set_mode(value)
                    self.mode_changed.emit(value)
                else:
                    self.set_theme(value)
                    self.theme_changed.emit(value)
                event.accept()
                return

    def mouseMoveEvent(self, event) -> None:
        point = event.position().toPoint()
        hover = any(
            group == "translate" and rect.contains(point)
            for group, _value, rect in self._segments()
        )
        if hover != self._hover_translate:
            self._hover_translate = hover
            self.update()

    def leaveEvent(self, event) -> None:
        if self._hover_translate:
            self._hover_translate = False
            self.update()

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
