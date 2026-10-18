"""结果浮窗：两套配色（半透明白底黑字 / 半透明黑底白字），可自由拖动与缩放。

配色语言沿用参考应用：纯色卡片 + 12px 圆角 + 不描边靠投影分层，整体 90% 不透明。
右下角有缩放抓手，拖它改宽高；用户一旦手动改过尺寸，就不再自动贴合内容。
"""

from __future__ import annotations

import ctypes
import html

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QDesktopServices,
    QFont,
    QGuiApplication,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from recttrans.terms import build_rich_html

RADIUS = 12
PADDING = 10
SHADOW = 10
MIN_WIDTH = 240
MIN_HEIGHT = 90
GRIP = 16

# 整体半透明。0.9 是实测取的值：再低会让 9pt 文字掉出 WCAG AA。
WINDOW_OPACITY = 0.9

THEMES = {
    "light": {
        "panel": "#FFFFFF",
        "text": "#111111",
        "muted": "#6B7280",
        "danger": "#B91C1C",
        "link": "#2563EB",
    },
    "dark": {
        "panel": "#111111",
        "text": "#FFFFFF",
        "muted": "#E2E8F0",
        "danger": "#F87171",
        "link": "#5D8BE6",
    },
}


def _open_url(url: str) -> None:
    """在系统默认浏览器中打开搜索页。"""
    QDesktopServices.openUrl(QUrl(url))

HWND_TOPMOST = -1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.SetWindowPos.argtypes = [
    ctypes.c_ssize_t, ctypes.c_ssize_t, ctypes.c_int, ctypes.c_int,
    ctypes.c_int, ctypes.c_int, ctypes.c_uint,
]
_user32.SetWindowPos.restype = ctypes.c_int


def _force_topmost(widget) -> None:
    """把窗口压到置顶队列最前面（被翻译的窗口也可能置顶）。"""
    try:
        _user32.SetWindowPos(
            int(widget.winId()), HWND_TOPMOST, 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
        )
    except Exception:  # noqa: BLE001
        pass


class _CloseGlyph(QWidget):
    """自绘关闭图标（两条交叉线，线性风格）。"""

    clicked = Signal()

    def __init__(self, parent: QWidget | None = None, color: str = "#6B7280") -> None:
        super().__init__(parent)
        self.setFixedSize(22, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("关闭")
        self._color = color

    def set_color(self, color: str) -> None:
        self._color = color
        self.update()

    def paintEvent(self, event) -> None:  # noqa: ARG002
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(self._color))
        pen.setWidthF(1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        inset = self.width() * 0.34
        painter.drawLine(QPointF(inset, inset), QPointF(self.width() - inset, self.height() - inset))
        painter.drawLine(QPointF(self.width() - inset, inset), QPointF(inset, self.height() - inset))

    def mousePressEvent(self, event) -> None:
        self.clicked.emit()
        event.accept()


class _GripHandle(QWidget):
    """浮窗顶部的「灵动岛」胶囊：只有拖它才能移动浮窗。"""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setFixedSize(58, 16)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setToolTip("拖动浮窗")
        self._color = "#6B7280"
        self._manual = False
        self._press_global = QPoint()
        self._press_pos = QPoint()

    def set_color(self, color: str) -> None:
        self._color = color
        self.update()

    def paintEvent(self, event) -> None:  # noqa: ARG002
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        color = QColor(self._color)
        color.setAlphaF(0.6)
        painter.setBrush(color)
        bar = QRectF((self.width() - 48) / 2, (self.height() - 6) / 2, 48, 6)
        painter.drawRoundedRect(bar, 3, 3)

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        window = self.window()
        handle = window.windowHandle() if window is not None else None
        # 原生窗口移动：由系统接管，比逐帧 move() 跟手得多。
        if handle is not None and handle.startSystemMove():
            event.accept()
            return
        self._manual = True
        self._press_global = event.globalPosition().toPoint()
        self._press_pos = window.pos() if window is not None else QPoint()
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if not self._manual or not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        window = self.window()
        if window is None:
            return
        delta = event.globalPosition().toPoint() - self._press_global
        window.move(self._press_pos + delta)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if self._manual:
            self._manual = False
            window = self.window()
            if window is not None and hasattr(window, "save_position"):
                window.save_position()
                window.position_changed.emit()
            event.accept()


class _ResizeHandle(QWidget):
    """右下角缩放手柄：独立子控件，避免被文字区域吞掉鼠标事件。"""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setFixedSize(20, 20)
        self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        self.setToolTip("拖动缩放")
        self._press_global = QPoint()
        self._press_size = (0, 0)

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._press_global = event.globalPosition().toPoint()
        self._press_size = (self.parent().width(), self.parent().height())
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        delta = event.globalPosition().toPoint() - self._press_global
        width, height = self.parent()._clamped_size(
            self._press_size[0] + delta.x(),
            self._press_size[1] + delta.y(),
        )
        self.parent()._user_sized = True
        self.parent().setFixedSize(width, height)
        event.accept()


class ResultPopup(QWidget):
    hide_requested = Signal()
    position_changed = Signal()
    reset_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowOpacity(WINDOW_OPACITY)
        self.setMouseTracking(True)

        self._theme = "light"
        self._resizing = False
        # 一旦放好就记住位置：移动选框、重新翻译都不再自动挪动浮窗。
        self._saved_pos: QPoint | None = None
        self._press_global = QPoint()
        self._press_pos = QPoint()
        self._press_size = (0, 0)
        self._width = 380
        self._user_sized = False
        self._caption_mode = False
        self._caption_html = ""
        self._caption_display_lines = 3
        self._user_scrolled = False
        self._rebuilding = False
        self._terms: list[dict] = []
        self._translation_plain = ""

        self._handle = _GripHandle(self)
        self._resize_handle = _ResizeHandle(self)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(400)
        self._save_timer.timeout.connect(self._persist_position)

        self._status = QLabel("", self)
        self._source = QLabel("", self)
        self._source.setWordWrap(True)
        self._translation = QTextBrowser(self)
        self._translation.setFrameShape(QFrame.Shape.NoFrame)
        self._translation.setOpenExternalLinks(False)
        self._translation.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._translation.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._translation.setStyleSheet(
            "QTextBrowser { background: transparent; border: none; }"
        )
        self._translation.document().setDocumentMargin(0)
        self._translation.setMinimumHeight(20)
        self._translation.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._translation.anchorClicked.connect(self._open_link)
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.setInterval(3000)
        self._scroll_timer.timeout.connect(self._caption_scroll_home)
        self._translation.verticalScrollBar().valueChanged.connect(
            self._on_caption_scroll
        )

        self._close = _CloseGlyph(self)
        self._close.clicked.connect(self.hide_requested.emit)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(self._status)
        header.addStretch(1)
        header.addWidget(self._close)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            PADDING + SHADOW, PADDING + SHADOW, PADDING + SHADOW, PADDING + SHADOW
        )
        layout.setSpacing(6)
        layout.addLayout(header)
        layout.addWidget(self._source)
        layout.addWidget(self._translation, 1)

        self._apply_fonts()
        self._apply_theme()
        self._place_handle()

    # ---------- 主题 ----------

    def set_theme(self, theme: str) -> None:
        if theme not in THEMES:
            return
        self._theme = theme
        self._apply_theme()

    def _palette(self) -> dict:
        return THEMES[self._theme]

    def _apply_theme(self) -> None:
        palette = self._palette()
        color = palette["danger"] if self._status.property("is_error") else palette["text"]
        self._status.setStyleSheet(f"color: {color};")
        source_color = palette["muted"] if self._caption_mode else palette["text"]
        self._source.setStyleSheet(f"color: {source_color};")
        self._translation.setStyleSheet(
            f"QTextBrowser {{ color: {palette['text']}; background: transparent;"
            " border: none; }}"
        )
        self._close.set_color(palette["muted"])
        self._handle.set_color(palette["muted"])
        self._render_translation()
        self.update()

    # ---------- 字体 ----------

    def _apply_fonts(self) -> None:
        if self._caption_mode:
            source_font = QFont()
            source_font.setPointSizeF(11.0)
            self._source.setFont(source_font)

            translation_font = QFont()
            translation_font.setPointSizeF(17.0)
            translation_font.setLetterSpacing(
                QFont.SpacingType.AbsoluteSpacing, 0.3
            )
            self._translation.setFont(translation_font)

            status_font = QFont()
            status_font.setPointSizeF(9.0)
            self._status.setFont(status_font)
            return

        source_font = QFont()
        source_font.setPointSizeF(9.0)
        self._source.setFont(source_font)

        translation_font = QFont()
        translation_font.setPointSizeF(12.0)
        translation_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.4)
        self._translation.setFont(translation_font)

        status_font = QFont()
        status_font.setPointSizeF(9.0)
        self._status.setFont(status_font)

    # ---------- 外观 ----------

    def _panel_rect(self) -> QRectF:
        return QRectF(self.rect()).adjusted(SHADOW, SHADOW, -SHADOW, -SHADOW + 2)

    def _grip_rect(self) -> QRect:
        panel = self._panel_rect()
        return QRect(
            int(panel.right()) - GRIP - 4, int(panel.bottom()) - GRIP - 4, GRIP, GRIP
        )

    def paintEvent(self, event) -> None:  # noqa: ARG002
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)

        for step in range(SHADOW, 0, -1):
            rect = QRectF(self.rect()).adjusted(step, step + 1, -step, -step + 3)
            alpha = int(6.0 * (1.0 - step / SHADOW) ** 1.6) + 2
            painter.setBrush(QColor(0, 0, 0, alpha))
            painter.drawRoundedRect(rect, RADIUS + step * 0.6, RADIUS + step * 0.6)

        painter.setBrush(QColor(self._palette()["panel"]))
        painter.drawRoundedRect(self._panel_rect(), RADIUS, RADIUS)

        # 右下角缩放抓手：三条斜线
        pen = QPen(QColor(self._palette()["muted"]))
        pen.setWidthF(1.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        grip = self._grip_rect()
        for offset in (3, 8, 13):
            painter.drawLine(
                QPointF(grip.right() - offset, grip.bottom()),
                QPointF(grip.right(), grip.bottom() - offset),
            )

    def _available_geometry(self) -> QRect:
        screen = self.screen() or QGuiApplication.primaryScreen()
        return screen.availableGeometry()

    def _clamped_size(self, width: int, height: int) -> tuple[int, int]:
        area = self._available_geometry()
        max_width = max(MIN_WIDTH, int(area.width() * 0.8))
        max_height = max(MIN_HEIGHT, int(area.height() * 0.75))
        return (
            max(MIN_WIDTH, min(width, max_width)),
            max(MIN_HEIGHT, min(height, max_height)),
        )

    # ---------- 内容 ----------

    def set_content(
        self,
        source: str,
        translation: str,
        status: str = "",
        is_error: bool = False,
        terms: list[dict] | None = None,
    ) -> None:
        self._caption_mode = False
        self._apply_fonts()
        self._status.setText(status)
        self._status.setProperty("is_error", is_error)
        self._source.setText(source[:400])
        self._source.setVisible(bool(source))
        self._translation_plain = translation
        self._terms = terms or []
        self._apply_theme()  # 内含 _render_translation()
        self._resize_to_content()

    # ---------- 同声传译字幕 ----------

    def set_caption(
        self,
        current: str,
        previous: str = "",
        status: str = "同声传译 · 本地识别",
    ) -> None:
        if not (current or "").strip() and (previous or "").strip():
            # 刚切完句、下一批词还没到：把上一句顶到当前行，避免字幕整块消失。
            current, previous = previous, ""
        self._caption_mode = True
        self._apply_fonts()
        self._status.setText(status)
        self._status.setProperty("is_error", False)
        self._source.setText((previous or "")[:200])
        self._source.setVisible(bool(previous))
        self._translation_plain = (current or "").strip()
        self._terms = []
        self._apply_theme()
        self._resize_to_content()
        self._keep_on_screen()

    def set_caption_status(self, text: str) -> None:
        self._caption_mode = True
        self._apply_fonts()
        self._status.setText(text)
        self._resize_to_content()

    def set_caption_bilingual(
        self,
        chinese: str,
        english: str,
        status: str = "同声传译 · 本地识别 + 翻译",
    ) -> None:
        """中文译文大字，英文原文小字；还没译出来时先大字显示英文。"""
        zh = (chinese or "").strip()
        en = (english or "").strip()
        main_text, sub_text = (zh, en) if zh else (en, "")
        self._caption_mode = True
        self._apply_fonts()
        self._status.setText(status)
        self._status.setProperty("is_error", False)
        self._source.setText(sub_text[:400])
        self._source.setVisible(bool(sub_text))
        self._translation_plain = main_text
        self._terms = []
        self._apply_theme()
        self._resize_to_content()
        self._keep_on_screen()

    def set_caption_zh(
        self,
        chinese: str,
        previous: str = "",
        status: str = "同声传译 · 中文",
    ) -> None:
        """只显示中文：当前句大字，上一句小字；英文不占浮窗。"""
        self.set_caption_zh_lines([chinese, previous], status=status)

    def set_caption_zh_lines(
        self,
        lines: list[str],
        display_lines: int = 3,
        status: str = "同声传译 · 中文",
    ) -> None:
        """所有行放进可滚动区域：第一行大字，历史小字；滚轮可向上回看。"""
        cleaned = [str(item).strip() for item in lines if str(item).strip()]
        if not cleaned:
            return
        self._caption_mode = True
        self._caption_display_lines = max(2, min(4, display_lines))
        palette = self._palette()
        parts = []
        ordered = list(reversed(cleaned))  # 旧行在上，最新一行在最底部
        for index, line in enumerate(ordered):
            is_current = index == len(ordered) - 1
            size = 17 if is_current else 11
            color = palette["text"] if is_current else palette["muted"]
            parts.append(
                f'<div style="font-size:{size}pt; color:{color};'
                f' margin-bottom:4px;">{html.escape(line)}</div>'
            )
        self._caption_html = "".join(parts)
        self._translation_plain = cleaned[0]
        self._source.hide()
        self._apply_fonts()
        self._status.setText(status)
        self._status.setProperty("is_error", False)
        self._terms = []
        self._apply_theme()
        self._resize_caption_height()
        if not self._user_scrolled:
            bar = self._translation.verticalScrollBar()
            bar.setValue(bar.maximum())
        self._keep_on_screen()

    def clear_caption(self) -> None:
        self._caption_mode = True
        self._source.setText("")
        self._source.setVisible(False)
        self._translation_plain = ""
        self._render_translation()
        self._resize_to_content()

    def show_caption(self, anchor: QRect | None = None) -> None:
        """第一次显示字幕：没有记住位置就贴在锚点（功能浮窗）下方。"""
        if not self._user_sized and self._width < 420:
            self._width = 420
        self._caption_mode = True
        self._apply_fonts()
        self._resize_to_content()
        if self._saved_pos is not None:
            self.place_saved()
        elif anchor is not None:
            self.place_below_rect(anchor)
        else:
            area = self._available_geometry()
            x = area.center().x() - self.width() // 2
            y = area.bottom() - self.height() - 56
            self.move(
                max(area.left(), x),
                max(area.top(), y),
            )
        self.show()
        self.raise_()

    def caption_text(self) -> str:
        return self._translation.toPlainText()

    def caption_previous(self) -> str:
        return self._source.text()

    def status_text(self) -> str:
        return self._status.text()

    def _keep_on_screen(self) -> None:
        area = self._available_geometry()
        x = max(area.left(), min(self.x(), area.right() - self.width() + 1))
        y = max(area.top(), min(self.y(), area.bottom() - self.height() + 1))
        if (x, y) != (self.x(), self.y()):
            self.move(x, y)

    def translation_text(self) -> str:
        try:
            return self._translation.toPlainText()
        except Exception:  # noqa: BLE001
            return self._translation_plain

    # ---------- 术语链接 ----------

    def _render_translation(self) -> None:
        if self._caption_mode and self._caption_html:
            bar = self._translation.verticalScrollBar()
            keep = bar.value()
            was_scrolled = self._user_scrolled
            self._rebuilding = True
            self._translation.setHtml(self._caption_html)
            self._rebuilding = False
            if was_scrolled:
                bar.setValue(min(keep, bar.maximum()))
            else:
                bar.setValue(bar.maximum())
            return
        palette = self._palette()
        if self._terms:
            self._translation.setHtml(
                build_rich_html(self._translation_plain, self._terms, palette["link"])
            )
        else:
            self._translation.setPlainText(self._translation_plain)

    def _open_link(self, url: str) -> None:
        _open_url(url.toString() if hasattr(url, "toString") else str(url))

    def _resize_to_content(self) -> None:
        if self._user_sized:
            return
        if self._caption_mode:
            self._resize_caption_height()
            return
        inner_width = self._width - 2 * PADDING
        height = 2 * SHADOW + 2 * PADDING + max(22, self._status.sizeHint().height())
        # 注意：父窗口还没 show() 时 isVisible() 恒为 False，用 isHidden() 判断。
        if not self._source.isHidden():
            height += self._source.heightForWidth(inner_width) + 6
        document = self._translation.document()
        document.setTextWidth(inner_width)
        height += int(document.size().height()) + 8
        if self._caption_mode:
            # 字幕窗口保持稳定高度，短句时也不缩成一条，减少上下跳动。
            height = max(height, 120)
        width, height = self._clamped_size(self._width + 2 * SHADOW, height)
        self.setFixedSize(width, height)

    def _resize_caption_height(self) -> None:
        width = self._width + 2 * SHADOW
        width, _height = self._clamped_size(width, 120)
        main_height = 36
        sub_height = 20
        height = (
            2 * SHADOW
            + 2 * PADDING
            + 22
            + main_height
            + (self._caption_display_lines - 1) * sub_height
            + 10
        )
        self.setFixedSize(width, height)

    def _on_caption_scroll(self, value: int) -> None:
        if not self._caption_mode or self._rebuilding:
            return
        bar = self._translation.verticalScrollBar()
        if value < bar.maximum() - 4:
            self._user_scrolled = True
            self._scroll_timer.start()
        else:
            self._user_scrolled = False

    def _caption_scroll_home(self) -> None:
        if not self._caption_mode:
            return
        self._user_scrolled = False
        bar = self._translation.verticalScrollBar()
        bar.setValue(bar.maximum())

    def place_below(self, anchor: QPoint) -> None:
        geometry = self._available_geometry()
        height = self.height()
        x = max(geometry.left(), min(anchor.x() - SHADOW, geometry.right() - self.width()))
        y = anchor.y() - SHADOW
        if y + height > geometry.bottom():
            y = max(geometry.top(), anchor.y() - height + SHADOW)
        self.move(x, y)

    def place_below_rect(self, anchor: QRect, gap: int = 8) -> None:
        """贴在矩形下方，并与矩形右边缘对齐。"""
        area = self._available_geometry()
        x = anchor.right() - self.width() + 1
        y = anchor.bottom() + gap
        if y + self.height() > area.bottom():
            y = anchor.top() - self.height() - gap
        x = max(area.left(), min(x, area.right() - self.width() + 1))
        y = max(area.top(), min(y, area.bottom() - self.height() + 1))
        self.move(x, y)

    # ---------- 位置记忆 ----------

    def has_saved_position(self) -> bool:
        return self._saved_pos is not None

    def set_saved_position(self, pos: QPoint) -> None:
        self._saved_pos = QPoint(pos)

    def clear_saved_position(self) -> None:
        self._saved_pos = None

    def save_position(self) -> None:
        self._saved_pos = self.pos()

    def place_saved(self) -> None:
        """回到记住的位置；屏幕变小或坐标失效时夹回可见范围。"""
        if self._saved_pos is None:
            return
        geometry = self._available_geometry()
        x = max(
            geometry.left(),
            min(self._saved_pos.x(), geometry.right() - self.width() + 1),
        )
        y = max(
            geometry.top(),
            min(self._saved_pos.y(), geometry.bottom() - self.height() + 1),
        )
        self.move(x, y)

    def place_near(self, anchor: QPoint) -> None:
        """首次出现：贴在 anchor 下方；已有位置则原地不动。"""
        if self._saved_pos is not None:
            self.place_saved()
        else:
            self.place_below(anchor)

    # ---------- 顶部拖动胶囊 ----------

    def _place_handle(self) -> None:
        self._handle.move((self.width() - self._handle.width()) // 2, SHADOW - 6)
        self._handle.raise_()
        grip = self._grip_rect()
        self._resize_handle.move(
            grip.center().x() - self._resize_handle.width() // 2,
            grip.center().y() - self._resize_handle.height() // 2,
        )
        self._resize_handle.raise_()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_handle"):
            self._place_handle()

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        # 原生拖动结束后不会额外发信号：用防抖把最终位置写回配置。
        if hasattr(self, "_save_timer") and self.isVisible():
            self._save_timer.start()

    def _persist_position(self) -> None:
        self.save_position()
        self.position_changed.emit()

    # ---------- 拖动与缩放 ----------

    def wheelEvent(self, event) -> None:
        bar = self._translation.verticalScrollBar()
        if bar.maximum() > 0:
            step = int(event.angleDelta().y() / 2)
            bar.setValue(bar.value() - step)
            event.accept()
            return
        super().wheelEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        point = event.position().toPoint()
        self._press_global = event.globalPosition().toPoint()
        if self._grip_rect().contains(point):
            self._resizing = True
            self._press_size = (self.width(), self.height())
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if not self._resizing:
            return
        delta = event.globalPosition().toPoint() - self._press_global
        width, height = self._clamped_size(
            self._press_size[0] + delta.x(), self._press_size[1] + delta.y()
        )
        self._user_sized = True
        self.setFixedSize(width, height)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: ARG002
        if self._resizing:
            self._resizing = False
            self.save_position()
            self.position_changed.emit()

    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)
        copy_action = QAction("复制译文", menu)
        theme_action = QAction("切换深浅配色", menu)
        reset_action = QAction("回到选框下方", menu)
        autosize_action = QAction("恢复自动大小", menu)
        close_action = QAction("关闭", menu)
        menu.addAction(copy_action)
        menu.addAction(theme_action)
        menu.addAction(reset_action)
        menu.addAction(autosize_action)
        menu.addSeparator()
        menu.addAction(close_action)
        chosen = menu.exec(event.globalPos())
        if chosen is copy_action:
            QGuiApplication.clipboard().setText(self.translation_text())
        elif chosen is theme_action:
            self.set_theme("dark" if self._theme == "light" else "light")
        elif chosen is reset_action:
            self.clear_saved_position()
            self.reset_requested.emit()
        elif chosen is autosize_action:
            self._user_sized = False
            self._resize_to_content()
        elif chosen is close_action:
            self.hide_requested.emit()
