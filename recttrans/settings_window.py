"""设置窗口：翻译通道、源/目标语言、划词热键、大模型 key 与模型。

保存即写入 config.local.json，主流程随后立即重新注册热键，不需要重启。
"""

from __future__ import annotations

import ctypes
import json

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from recttrans.config import save_config
from recttrans.hotkey import normalize_sequence
from recttrans.version import BUILD

BG = "#FFFFFF"
TEXT = "#111111"
MUTED = "#6B7280"
BORDER = "#E2E8F0"
STRONG_BORDER = "#64748B"
ACCENT = "#FFA800"

SOURCE_LANGUAGES = [("auto", "自动识别"), ("en", "英文"), ("zh-CN", "中文"), ("ja", "日文")]
TARGET_LANGUAGES = [("zh-CN", "中文"), ("en", "英文")]

FRAME_COLORS = [("#FFA800", "橙"), ("#0078FF", "蓝"), ("#111111", "黑"), ("#FFFFFF", "白")]
FRAME_THICKNESS = (4, 6, 8)
FRAME_LENGTHS = (("短", 32), ("中", 48), ("长", 64))


class HotkeyEdit(QLineEdit):
    """点击后直接按键录制组合键，不再要求手动输入文本。

    录制期间按住修饰键只更新预览，按下普通键才定稿；Esc 取消并恢复原值。
    只接受「至少一个修饰键 + 一个普通键」。
    """

    _NAMED_KEYS = {
        Qt.Key.Key_Space: "Space",
        Qt.Key.Key_Tab: "Tab",
        Qt.Key.Key_Return: "Enter",
        Qt.Key.Key_Enter: "Enter",
        Qt.Key.Key_Backspace: "Backspace",
        Qt.Key.Key_Delete: "Delete",
        Qt.Key.Key_Insert: "Insert",
        Qt.Key.Key_Home: "Home",
        Qt.Key.Key_End: "End",
        Qt.Key.Key_PageUp: "PageUp",
        Qt.Key.Key_PageDown: "PageDown",
        Qt.Key.Key_Left: "Left",
        Qt.Key.Key_Up: "Up",
        Qt.Key.Key_Right: "Right",
        Qt.Key.Key_Down: "Down",
    }

    # 这些是各程序里最常用的快捷键，注册成全局热键会直接把功能抢走
    # （例如 Ctrl+Z 会让所有程序无法撤销）。录制时直接拒绝。
    _RESERVED = {
        "Ctrl+C", "Ctrl+V", "Ctrl+X", "Ctrl+Z", "Ctrl+Shift+Z", "Ctrl+Y",
        "Ctrl+A", "Ctrl+S",
        "Ctrl+F", "Ctrl+P", "Ctrl+W", "Ctrl+T", "Ctrl+N", "Ctrl+O",
        "Win+L", "Win+D", "Win+E", "Win+R",
    }

    def __init__(self, value: str, parent=None) -> None:
        normalized = normalize_sequence(value) or value
        super().__init__(normalized, parent)
        self.setReadOnly(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setPlaceholderText("点击这里，然后按下组合键")
        self._recording = False
        self._before = normalized

    # ---------- 录制 ----------

    def mousePressEvent(self, event) -> None:
        super().mousePressEvent(event)
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        self.start_recording()

    def start_recording(self) -> None:
        if self._recording:
            return
        self._recording = True
        self._before = self.text()
        self.setText("请按下组合键…")

    def cancel_recording(self) -> None:
        self._recording = False
        self.setText(self._before)

    def keyPressEvent(self, event) -> None:
        if not self._recording:
            super().keyPressEvent(event)
            return

        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.cancel_recording()
            return
        own_modifier = {
            Qt.Key.Key_Control: Qt.KeyboardModifier.ControlModifier,
            Qt.Key.Key_Shift: Qt.KeyboardModifier.ShiftModifier,
            Qt.Key.Key_Alt: Qt.KeyboardModifier.AltModifier,
            Qt.Key.Key_Meta: Qt.KeyboardModifier.MetaModifier,
        }.get(key)
        if own_modifier is not None:
            # 单独按修饰键时，部分平台的事件里不带该修饰位，这里补上。
            self.setText(self._preview(event.modifiers() | own_modifier))
            return

        name = self._key_name(key)
        if name is None:
            return
        normalized = normalize_sequence(self._preview(event.modifiers(), name))
        if normalized is None:
            self.setText("需要至少一个修饰键，请重按")
            return
        if normalized in self._RESERVED:
            self.setText(f"{normalized} 是常用快捷键，会抢占其它程序，请换一个")
            return
        self._recording = False
        self.setText(normalized)
        self.clearFocus()

    def focusOutEvent(self, event) -> None:
        if self._recording:
            self.cancel_recording()
        super().focusOutEvent(event)

    # ---------- 辅助 ----------

    @staticmethod
    def _preview(modifiers, key: str = "…") -> str:
        parts = []
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            parts.append("Ctrl")
        if modifiers & Qt.KeyboardModifier.AltModifier:
            parts.append("Alt")
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            parts.append("Shift")
        if modifiers & Qt.KeyboardModifier.MetaModifier:
            parts.append("Win")
        parts.append(key)
        return "+".join(parts)

    @classmethod
    def _key_name(cls, key) -> str | None:
        if Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
            return chr(key)
        if Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
            return chr(key)
        if Qt.Key.Key_F1 <= key <= Qt.Key.Key_F24:
            return f"F{key - Qt.Key.Key_F1 + 1}"
        return cls._NAMED_KEYS.get(key)


def _reduce_motion() -> bool:
    """读取系统的「减少动画」设置（对应规范里的无障碍要求）。"""
    try:
        enabled = ctypes.c_int()
        ok = ctypes.windll.user32.SystemParametersInfoW(
            0x1042, 0, ctypes.byref(enabled), 0  # SPI_GETCLIENTAREAANIMATION
        )
        return bool(ok) and not enabled.value
    except Exception:  # noqa: BLE001
        return False


class SettingsWindow(QDialog):
    frame_style_changed = Signal(dict)

    def __init__(self, config: dict, parent=None, current_hotkey: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setMinimumWidth(480)

        self._config = config
        self._provider = str(config["translate"].get("provider", "deepseek"))
        self.saved_config: dict | None = None
        frame_section = config.get("frame") or {}
        self._frame_style = {
            "color": str(frame_section.get("color", "#FFA800")),
            "thickness": int(frame_section.get("thickness", 6)),
            "length": int(frame_section.get("length", 48)),
        }
        if self._frame_style["color"] not in [c for c, _n in FRAME_COLORS]:
            self._frame_style["color"] = "#FFA800"
        if self._frame_style["thickness"] not in FRAME_THICKNESS:
            self._frame_style["thickness"] = 6
        if self._frame_style["length"] not in [v for _n, v in FRAME_LENGTHS]:
            self._frame_style["length"] = 48
        caption_section = config.get("caption") or {}
        self._caption_context = int(caption_section.get("context_lines", 2))
        self._caption_lines = int(caption_section.get("display_lines", 3))
        if self._caption_context not in (1, 2, 3):
            self._caption_context = 2
        if self._caption_lines not in (2, 3, 4):
            self._caption_lines = 3
        self._color_buttons: dict[str, QPushButton] = {}
        self._thick_buttons: dict[int, QPushButton] = {}
        self._length_buttons: dict[int, QPushButton] = {}
        self._context_buttons: dict[int, QPushButton] = {}
        self._lines_buttons: dict[int, QPushButton] = {}

        self.setStyleSheet(
            f"""
            QDialog {{ background: {BG}; }}
            QLabel {{ color: {TEXT}; }}
            QLabel#hint {{ color: {MUTED}; }}
            QComboBox, QLineEdit {{
                background: {BG}; color: {TEXT};
                border: 1px solid {STRONG_BORDER}; border-radius: 8px;
                padding: 6px 8px; min-height: 22px;
            }}
            QPushButton#channel {{
                background: transparent; color: {MUTED};
                border: 1px solid {BORDER}; border-radius: 11px;
                padding: 5px 14px;
            }}
            QPushButton#channel:checked {{
                background: {ACCENT}; color: {TEXT}; border-color: {ACCENT};
            }}
            QPushButton#primary {{
                background: {ACCENT}; color: {TEXT}; border: none;
                border-radius: 8px; padding: 8px 20px;
            }}
            QPushButton#primary:hover {{ background: rgba(255,168,0,0.85); }}
            QPushButton#ghost {{
                background: transparent; color: {TEXT};
                border: 1px solid {BORDER}; border-radius: 8px; padding: 8px 20px;
            }}
            QPushButton#mini {{
                background: transparent; color: {MUTED};
                border: 1px solid {BORDER}; border-radius: 10px;
                padding: 2px 8px; min-height: 18px;
            }}
            QPushButton#mini:checked {{
                background: {ACCENT}; color: {TEXT}; border-color: {ACCENT};
            }}
            """
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")
        scroll.viewport().setAutoFillBackground(False)

        content = QWidget()
        content.setAutoFillBackground(False)
        self._content = content
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(12)
        scroll.setWidget(content)
        outer.addWidget(scroll)

        title = QLabel("翻译设置")
        title.setStyleSheet("font-size: 14pt; font-weight: 600;")
        layout.addWidget(title)

        hint = QLabel("改动会写入 config.local.json，保存后立即生效。")
        hint.setObjectName("hint")
        layout.addWidget(hint)

        # 热键放在最上面：它是排障时最需要一眼看到和修改的项。
        layout.addWidget(self._section("划词热键"))
        self._hotkey = HotkeyEdit(str(config.get("quick_hotkey", "Ctrl+Shift+Q")))
        layout.addWidget(self._hotkey)

        active = current_hotkey or "未绑定"
        hotkey_hint = QLabel(
            f"点击上面的框，直接按下想要的组合键即可（Esc 取消）。"
            f"至少含一个 Ctrl / Alt / Shift / Win。当前生效：{active}"
        )
        hotkey_hint.setObjectName("hint")
        hotkey_hint.setWordWrap(True)
        layout.addWidget(hotkey_hint)

        self._hotkey_error = QLabel("")
        self._hotkey_error.setStyleSheet("color: #B91C1C;")
        self._hotkey_error.setWordWrap(True)
        self._hotkey_error.hide()
        layout.addWidget(self._hotkey_error)
        self._hotkey.textChanged.connect(lambda: self._hotkey_error.hide())

        layout.addWidget(self._section("翻译通道"))
        channel_row = QHBoxLayout()
        channel_row.setSpacing(8)
        self._free_button = QPushButton("免费接口")
        self._llm_button = QPushButton("大模型")
        for button in (self._free_button, self._llm_button):
            button.setObjectName("channel")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            channel_row.addWidget(button)
        channel_row.addStretch(1)
        self._free_button.clicked.connect(lambda: self._set_provider("free"))
        self._llm_button.clicked.connect(lambda: self._set_provider("deepseek"))
        layout.addLayout(channel_row)

        channel_hint = QLabel(
            "免费接口免 key（走 Google 公共端点，可能限流）；大模型质量更稳，按量计费。"
        )
        channel_hint.setObjectName("hint")
        channel_hint.setWordWrap(True)
        layout.addWidget(channel_hint)

        layout.addWidget(self._section("语言"))
        language_row = QHBoxLayout()
        language_row.setSpacing(12)

        source_box = QVBoxLayout()
        source_box.setSpacing(4)
        source_box.addWidget(self._hint("源语言"))
        self._source = QComboBox()
        for code, name in SOURCE_LANGUAGES:
            self._source.addItem(name, code)
        source_box.addWidget(self._source)

        target_box = QVBoxLayout()
        target_box.setSpacing(4)
        target_box.addWidget(self._hint("目标语言"))
        self._target = QComboBox()
        for code, name in TARGET_LANGUAGES:
            self._target.addItem(name, code)
        target_box.addWidget(self._target)

        language_row.addLayout(source_box, 1)
        language_row.addLayout(target_box, 1)
        layout.addLayout(language_row)

        layout.addWidget(self._section("同声传译"))
        caption_row = QHBoxLayout()
        caption_row.setSpacing(16)

        context_box = QVBoxLayout()
        context_box.setSpacing(4)
        context_box.addWidget(self._hint("上下文句数"))
        context_buttons = QHBoxLayout()
        context_buttons.setSpacing(4)
        for value, name in ((1, "1 句"), (2, "2 句"), (3, "3 句")):
            button = QPushButton(name)
            button.setObjectName("mini")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(
                lambda _checked=False, v=value: self._set_caption_context(v)
            )
            context_buttons.addWidget(button)
            self._context_buttons[value] = button
        context_box.addLayout(context_buttons)

        lines_box = QVBoxLayout()
        lines_box.setSpacing(4)
        lines_box.addWidget(self._hint("显示行数"))
        lines_buttons = QHBoxLayout()
        lines_buttons.setSpacing(4)
        for value in (2, 3, 4):
            button = QPushButton(f"{value} 行")
            button.setObjectName("mini")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(
                lambda _checked=False, v=value: self._set_caption_lines(v)
            )
            lines_buttons.addWidget(button)
            self._lines_buttons[value] = button
        lines_box.addLayout(lines_buttons)

        caption_row.addLayout(context_box, 1)
        caption_row.addLayout(lines_box, 1)
        layout.addLayout(caption_row)
        caption_hint = QLabel(
            "上下文越多，代词和称呼越准；显示行数决定浮窗高度。"
            "语速快时建议 2 句上下文 + 3 行。"
        )
        caption_hint.setObjectName("hint")
        caption_hint.setWordWrap(True)
        layout.addWidget(caption_hint)

        layout.addWidget(self._section("选框外观"))
        style_row = QHBoxLayout()
        style_row.setSpacing(6)

        color_group = QButtonGroup(self)
        color_group.setExclusive(True)
        for color, name in FRAME_COLORS:
            button = QPushButton()
            button.setCheckable(True)
            button.setFixedSize(24, 24)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip(name)
            edge = STRONG_BORDER if color in ("#FFFFFF", "#111111") else BORDER
            button.setStyleSheet(
                f"QPushButton {{ background: {color}; border: 1px solid {edge};"
                f" border-radius: 12px; }}"
                f"QPushButton:checked {{ border: 2px solid {TEXT}; }}"
            )
            color_group.addButton(button)
            self._color_buttons[color] = button
            style_row.addWidget(button)

        style_row.addSpacing(10)
        style_row.addWidget(self._hint("粗细"))
        thick_group = QButtonGroup(self)
        thick_group.setExclusive(True)
        for value in FRAME_THICKNESS:
            button = QPushButton(str(value))
            button.setObjectName("mini")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFixedWidth(34)
            thick_group.addButton(button)
            self._thick_buttons[value] = button
            style_row.addWidget(button)

        style_row.addSpacing(10)
        style_row.addWidget(self._hint("长度"))
        length_group = QButtonGroup(self)
        length_group.setExclusive(True)
        for name, value in FRAME_LENGTHS:
            button = QPushButton(name)
            button.setObjectName("mini")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFixedWidth(36)
            length_group.addButton(button)
            self._length_buttons[value] = button
            style_row.addWidget(button)

        style_row.addStretch(1)
        layout.addLayout(style_row)

        style_hint = QLabel("改完立即生效；白色/黑色在相近底色上可能看不清。")
        style_hint.setObjectName("hint")
        layout.addWidget(style_hint)

        for button in self._color_buttons.values():
            button.toggled.connect(lambda checked: checked and self._on_style_changed())
        for button in self._thick_buttons.values():
            button.toggled.connect(lambda checked: checked and self._on_style_changed())
        for button in self._length_buttons.values():
            button.toggled.connect(lambda checked: checked and self._on_style_changed())
        self._sync_style_buttons()

        layout.addWidget(self._section("大模型（OpenAI 兼容）"))
        layout.addWidget(self._hint("接口地址"))
        self._base_url = QLineEdit(
            str(config["translate"].get("base_url", "https://api.deepseek.com"))
        )
        self._base_url.setPlaceholderText("https://api.deepseek.com")
        layout.addWidget(self._base_url)

        layout.addWidget(self._hint("API key"))
        self._key = QLineEdit(str(config["translate"].get("api_key", "")))
        self._key.setEchoMode(QLineEdit.EchoMode.Password)
        self._key.setPlaceholderText("sk-...")
        layout.addWidget(self._key)

        self._key_error = QLabel("")
        self._key_error.setStyleSheet("color: #B91C1C;")
        self._key_error.setWordWrap(True)
        self._key_error.hide()
        layout.addWidget(self._key_error)
        self._key.textChanged.connect(lambda: self._key_error.hide())

        layout.addWidget(self._hint("模型名"))
        self._model = QLineEdit(str(config["translate"].get("model", "deepseek-chat")))
        self._model.setPlaceholderText("deepseek-chat")
        layout.addWidget(self._model)

        key_hint = QLabel("key 只保存在本机 config.local.json，不会上传到别处。")
        key_hint.setObjectName("hint")
        layout.addWidget(key_hint)

        version_label = QLabel(f"版本 {BUILD}")
        version_label.setObjectName("hint")
        layout.addWidget(version_label)

        layout.addStretch(1)

        footer = QHBoxLayout()
        footer.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setObjectName("ghost")
        cancel.clicked.connect(self.reject)
        save = QPushButton("保存")
        save.setObjectName("primary")
        save.clicked.connect(self._save)
        footer.addWidget(cancel)
        footer.addWidget(save)
        layout.addLayout(footer)

        self._load_values()
        self._set_provider(self._provider)
        # QScrollArea 的 sizeHint 不会带上内容高度：先按内容定一次窗口大小，
        # 屏幕放不下时由 showEvent 夹到 90% 并允许滚动。
        self._content.adjustSize()
        hint = self._content.sizeHint()
        self.resize(max(self.minimumWidth(), hint.width()), hint.height())

    # ---------- 构建辅助 ----------

    @staticmethod
    def _section(title: str) -> QLabel:
        label = QLabel(title)
        label.setStyleSheet("font-size: 11pt; font-weight: 600;")
        return label

    @staticmethod
    def _hint(title: str) -> QLabel:
        label = QLabel(title)
        label.setObjectName("hint")
        return label

    def _load_values(self) -> None:
        source = str(self._config.get("source_language", "auto"))
        target = str(self._config.get("target_language", "zh-CN"))
        index = self._source.findData(source)
        self._source.setCurrentIndex(index if index >= 0 else 0)
        index = self._target.findData(target)
        self._target.setCurrentIndex(index if index >= 0 else 0)
        self._sync_caption_buttons()

    def _set_provider(self, provider: str) -> None:
        self._provider = provider
        self._free_button.setChecked(provider == "free")
        self._llm_button.setChecked(provider == "deepseek")
        is_llm = provider == "deepseek"
        self._base_url.setEnabled(is_llm)
        self._key.setEnabled(is_llm)
        self._model.setEnabled(is_llm)

    def _set_caption_context(self, value: int) -> None:
        self._caption_context = value if value in (1, 2, 3) else 2
        for option, button in self._context_buttons.items():
            button.setChecked(option == self._caption_context)

    def _set_caption_lines(self, value: int) -> None:
        self._caption_lines = value if value in (2, 3, 4) else 3
        for option, button in self._lines_buttons.items():
            button.setChecked(option == self._caption_lines)

    def _sync_caption_buttons(self) -> None:
        self._set_caption_context(self._caption_context)
        self._set_caption_lines(self._caption_lines)

    # ---------- 选框外观 ----------

    def _sync_style_buttons(self) -> None:
        for color, button in self._color_buttons.items():
            button.blockSignals(True)
            button.setChecked(color == self._frame_style["color"])
            button.blockSignals(False)
        for value, button in self._thick_buttons.items():
            button.blockSignals(True)
            button.setChecked(value == self._frame_style["thickness"])
            button.blockSignals(False)
        for value, button in self._length_buttons.items():
            button.blockSignals(True)
            button.setChecked(value == self._frame_style["length"])
            button.blockSignals(False)

    def _on_style_changed(self) -> None:
        self._frame_style = {
            "color": next(
                (c for c, b in self._color_buttons.items() if b.isChecked()),
                self._frame_style["color"],
            ),
            "thickness": next(
                (v for v, b in self._thick_buttons.items() if b.isChecked()),
                self._frame_style["thickness"],
            ),
            "length": next(
                (v for v, b in self._length_buttons.items() if b.isChecked()),
                self._frame_style["length"],
            ),
        }
        self.frame_style_changed.emit(dict(self._frame_style))

    # ---------- 保存 ----------

    def _save(self) -> None:
        hotkey = normalize_sequence(self._hotkey.text().strip())
        if hotkey is None:
            self._hotkey_error.setText(
                "热键格式不对：至少要有一个修饰键（Ctrl / Alt / Shift / Win）加一个按键，"
                "例如 Ctrl+Alt+Q。"
            )
            self._hotkey_error.show()
            self._hotkey.setFocus()
            return

        key = self._key.text().strip()
        base_url = (
            self._base_url.text().strip().rstrip("/")
            or "https://api.deepseek.com"
        )
        if (
            self._provider == "deepseek"
            and "deepseek.com" in base_url
            and not key.startswith("sk-")
        ):
            self._key_error.setText(
                "DeepSeek 需要以 sk- 开头的 API key；其他兼容接口按服务要求填写。"
            )
            self._key_error.show()
            self._key.setFocus()
            return

        config = json.loads(json.dumps(self._config))
        config["translate"]["provider"] = self._provider
        config["translate"]["base_url"] = base_url
        config["translate"]["api_key"] = key
        model = self._model.text().strip()
        config["translate"]["model"] = model or "deepseek-chat"
        config["source_language"] = self._source.currentData()
        config["target_language"] = self._target.currentData()
        config["quick_hotkey"] = hotkey
        config["frame"] = dict(self._frame_style)
        config["caption"] = {
            "context_lines": self._caption_context,
            "display_lines": self._caption_lines,
        }
        save_config(config)
        self.saved_config = config
        self.accept()

    # ---------- 动效（尊重系统「减少动画」） ----------

    def showEvent(self, event) -> None:
        super().showEvent(event)
        screen = self.screen()
        if screen is not None:
            max_height = int(screen.availableGeometry().height() * 0.9)
            if self.height() > max_height:
                self.resize(self.width(), max_height)
        if _reduce_motion():
            self.setWindowOpacity(1.0)
            return
        self.setWindowOpacity(0.0)
        animation = QPropertyAnimation(self, b"windowOpacity", self)
        animation.setDuration(150)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
