"""托盘图标与菜单：显示/隐藏选框、设置、自动翻译、退出。"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

ACCENT = "#FFA800"
DARK = "#111111"


def _make_icon() -> QIcon:
    """自绘托盘图标（不用 QImage：本机 QImage 必崩，QPixmap 正常）。"""
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(ACCENT))
    painter.drawRoundedRect(2, 4, 28, 24, 6, 6)
    painter.setBrush(QColor(DARK))
    painter.drawRect(6, 10, 20, 3)
    painter.drawRect(6, 17, 13, 3)
    painter.end()
    return QIcon(pixmap)


class Tray(QSystemTrayIcon):
    toggle_requested = Signal()
    quick_requested = Signal()
    history_requested = Signal()
    settings_requested = Signal()
    auto_toggled = Signal(bool)
    quit_requested = Signal()

    def __init__(self) -> None:
        super().__init__(_make_icon())
        self.setToolTip("矩形翻译")

        menu = QMenu()
        self._toggle = menu.addAction("显示 / 隐藏选框")
        self._quick = menu.addAction("划词翻译")
        self._auto = menu.addAction("自动翻译")
        self._auto.setCheckable(True)
        self._auto.setChecked(True)
        self._history = menu.addAction("历史记录…")
        self._settings = menu.addAction("设置…")
        menu.addSeparator()
        self._quit = menu.addAction("退出")
        self._menu = menu
        self.setContextMenu(menu)

        self._toggle.triggered.connect(self.toggle_requested.emit)
        self._quick.triggered.connect(self.quick_requested.emit)
        self._auto.triggered.connect(lambda checked: self.auto_toggled.emit(checked))
        self._history.triggered.connect(self.history_requested.emit)
        self._settings.triggered.connect(self.settings_requested.emit)
        self._quit.triggered.connect(self.quit_requested.emit)
        self.activated.connect(self._on_activated)

    def set_auto_checked(self, checked: bool) -> None:
        self._auto.setChecked(checked)

    def set_hotkeys(self, quick: str) -> None:
        self._quick.setText(f"划词翻译 ({quick})")

    def notify(self, title: str, message: str, msec: int = 4000) -> None:
        """气球提示：只在用户需要知道「程序还在后台 / 热键换了」时用。"""
        try:
            self.showMessage(
                title, message, QSystemTrayIcon.MessageIcon.Information, msec
            )
        except Exception:  # noqa: BLE001
            pass

    def _on_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.toggle_requested.emit()
