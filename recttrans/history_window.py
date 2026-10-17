"""翻译历史窗口：左侧列表、右侧详情，可复制译文或清空。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
)

BG = "#FFFFFF"
TEXT = "#111111"
MUTED = "#6B7280"
BORDER = "#E2E8F0"
ACCENT = "#FFA800"


class HistoryWindow(QDialog):
    def __init__(self, entries: list[dict], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("翻译历史")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.resize(680, 520)
        self._entries = list(entries)
        self.cleared = False

        self.setStyleSheet(
            f"""
            QDialog {{ background: {BG}; }}
            QLabel {{ color: {TEXT}; }}
            QLabel#hint {{ color: {MUTED}; }}
            QListWidget {{
                background: {BG}; color: {TEXT};
                border: 1px solid {BORDER}; border-radius: 8px;
            }}
            QListWidget::item {{ padding: 6px 8px; }}
            QListWidget::item:selected {{ background: #EFF6FF; color: {TEXT}; }}
            QTextBrowser {{
                background: {BG}; color: {TEXT};
                border: 1px solid {BORDER}; border-radius: 8px;
                padding: 6px;
            }}
            QPushButton#primary {{
                background: {ACCENT}; color: {TEXT}; border: none;
                border-radius: 8px; padding: 7px 16px;
            }}
            QPushButton#ghost {{
                background: transparent; color: {TEXT};
                border: 1px solid {BORDER}; border-radius: 8px; padding: 7px 16px;
            }}
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        title = QLabel("翻译历史")
        title.setStyleSheet("font-size: 13pt; font-weight: 600;")
        layout.addWidget(title)
        hint = QLabel("只记录手动与划词翻译；最新的在最上面，保存在本机 history.json。")
        hint.setObjectName("hint")
        layout.addWidget(hint)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self._list = QListWidget()
        self._detail = QTextBrowser()
        self._detail.setOpenExternalLinks(False)
        splitter.addWidget(self._list)
        splitter.addWidget(self._detail)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)

        footer = QHBoxLayout()
        copy_button = QPushButton("复制译文")
        copy_button.setObjectName("primary")
        copy_button.clicked.connect(self._copy_selected)
        clear_button = QPushButton("清空历史")
        clear_button.setObjectName("ghost")
        clear_button.clicked.connect(self._clear)
        close_button = QPushButton("关闭")
        close_button.setObjectName("ghost")
        close_button.clicked.connect(self.accept)
        footer.addWidget(copy_button)
        footer.addWidget(clear_button)
        footer.addStretch(1)
        footer.addWidget(close_button)
        layout.addLayout(footer)

        self._list.currentRowChanged.connect(self._show_row)
        self._refresh()

    # ---------- 数据 ----------

    def _refresh(self) -> None:
        self._list.clear()
        for index, entry in enumerate(self._entries):
            kind = "划词" if entry.get("kind") == "selection" else "矩形"
            preview = (entry.get("source") or entry.get("translation") or "").replace("\n", " ")
            if len(preview) > 42:
                preview = preview[:42] + "…"
            item = QListWidgetItem(f"{entry.get('time', '')}  ·  {kind}\n{preview}")
            item.setData(Qt.ItemDataRole.UserRole, index)
            self._list.addItem(item)
        if self._entries:
            self._list.setCurrentRow(0)
        else:
            self._detail.setPlainText("还没有历史记录。")

    def _show_row(self, row: int) -> None:
        if row < 0 or row >= len(self._entries):
            return
        entry = self._entries[row]
        kind = "划词翻译" if entry.get("kind") == "selection" else "矩形翻译"
        self._detail.setPlainText(
            f"{entry.get('time', '')} · {kind}\n\n"
            f"原文\n{entry.get('source') or '（无）'}\n\n"
            f"译文\n{entry.get('translation', '')}"
        )

    def _copy_selected(self) -> None:
        row = self._list.currentRow()
        if 0 <= row < len(self._entries):
            QGuiApplication.clipboard().setText(self._entries[row].get("translation", ""))

    def _clear(self) -> None:
        if not self._entries:
            return
        answer = QMessageBox.question(
            self,
            "清空历史",
            "确定清空全部翻译历史吗？此操作不可恢复。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._entries = []
        self.cleared = True
        self._refresh()
