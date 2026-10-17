"""全局热键：RegisterHotKey + Qt 原生事件过滤。

用系统级热键而不是应用内快捷键：这样在 Photoshop、浏览器、IDE 里都能唤出。
"""

from __future__ import annotations

import ctypes

from PySide6.QtCore import QAbstractNativeEventFilter

WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008

_MODIFIERS = {
    "Ctrl": MOD_CONTROL,
    "Control": MOD_CONTROL,
    "Alt": MOD_ALT,
    "Shift": MOD_SHIFT,
    "Meta": MOD_WIN,
    "Win": MOD_WIN,
}
_MODIFIERS_LOWER = {name.lower(): value for name, value in _MODIFIERS.items()}

_NAMED_KEYS = {
    "Space": 0x20,
    "Tab": 0x09,
    "Return": 0x0D,
    "Enter": 0x0D,
    "Backspace": 0x08,
    "Esc": 0x1B,
    "Escape": 0x1B,
    "Delete": 0x2E,
    "Insert": 0x2D,
    "Home": 0x24,
    "End": 0x23,
    "PageUp": 0x21,
    "PageDown": 0x22,
    "Left": 0x25,
    "Up": 0x26,
    "Right": 0x27,
    "Down": 0x28,
}

# 虚拟键码 → 规范显示名。Return/Enter、Esc/Escape 这类同义键只保留一个。
_VK_LABELS = {
    0x20: "Space",
    0x09: "Tab",
    0x0D: "Enter",
    0x08: "Backspace",
    0x1B: "Esc",
    0x2E: "Delete",
    0x2D: "Insert",
    0x24: "Home",
    0x23: "End",
    0x21: "PageUp",
    0x22: "PageDown",
    0x25: "Left",
    0x26: "Up",
    0x27: "Right",
    0x28: "Down",
}

_NAMED_KEYS_LOWER = {name.lower(): value for name, value in _NAMED_KEYS.items()}
_MODIFIER_LABELS = (
    (MOD_CONTROL, "Ctrl"),
    (MOD_ALT, "Alt"),
    (MOD_SHIFT, "Shift"),
    (MOD_WIN, "Win"),
)


def parse_sequence(text: str) -> tuple[int, int] | None:
    """把 "Ctrl+Alt+Q" 这类文本转成 (修饰键, 虚拟键码)；不合法返回 None。"""
    parts = [part.strip() for part in text.split("+") if part.strip()]
    if len(parts) < 2:
        return None

    modifiers = 0
    for part in parts[:-1]:
        value = _MODIFIERS_LOWER.get(part.lower())
        if value is None:
            return None
        modifiers |= value
    if modifiers == 0:
        return None  # 必须带修饰键，避免抢走普通按键

    key = parts[-1]
    if len(key) == 1 and key.isalpha():
        return modifiers, ord(key.upper())
    if len(key) == 1 and key.isdigit():
        return modifiers, ord(key)
    if key.upper().startswith("F") and key[1:].isdigit():
        index = int(key[1:])
        if 1 <= index <= 24:
            return modifiers, 0x70 + index - 1
        return None
    named = _NAMED_KEYS_LOWER.get(key.lower())
    if named is not None:
        return modifiers, named
    return None


def normalize_sequence(text: str) -> str | None:
    """把用户输入统一成 "Ctrl+Alt+Q" 这种规范写法；不合法返回 None。"""
    parsed = parse_sequence(text)
    if parsed is None:
        return None
    modifiers, vk = parsed
    names = [name for bit, name in _MODIFIER_LABELS if modifiers & bit]
    if 0x41 <= vk <= 0x5A:
        key = chr(vk)
    elif 0x30 <= vk <= 0x39:
        key = chr(vk)
    elif 0x70 <= vk <= 0x87:
        key = f"F{vk - 0x70 + 1}"
    else:
        key = _VK_LABELS.get(vk, "")
    if not key:
        return None
    return "+".join(names + [key])


class _Msg(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("message", ctypes.c_uint),
        ("w_param", ctypes.c_size_t),
        ("l_param", ctypes.c_ssize_t),
        ("time", ctypes.c_uint),
        ("pt_x", ctypes.c_long),
        ("pt_y", ctypes.c_long),
    ]


class HotkeyManager(QAbstractNativeEventFilter):
    def __init__(self) -> None:
        super().__init__()
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._callbacks: dict[int, object] = {}
        self._registered: list[int] = []
        self._next_id = 1

    def register(self, modifiers: int, vk: int, callback) -> int:
        """注册成功返回热键 ID（>0），失败返回 0。"""
        hotkey_id = self._next_id
        if not self._user32.RegisterHotKey(None, hotkey_id, modifiers, vk):
            return 0
        self._next_id += 1
        self._callbacks[hotkey_id] = callback
        self._registered.append(hotkey_id)
        return hotkey_id

    def unregister(self, hotkey_id: int) -> None:
        """注销单个热键：设置里改键时要先放掉旧的，否则新键可能被自己占着。"""
        if not hotkey_id:
            return
        if hotkey_id in self._registered:
            self._user32.UnregisterHotKey(None, hotkey_id)
            self._registered.remove(hotkey_id)
        self._callbacks.pop(hotkey_id, None)

    def unregister_all(self) -> None:
        for hotkey_id in self._registered:
            self._user32.UnregisterHotKey(None, hotkey_id)
        self._registered.clear()
        self._callbacks.clear()

    def nativeEventFilter(self, event_type, message):
        try:
            if event_type in (b"windows_generic_MSG", "windows_generic_MSG"):
                msg = _Msg.from_address(int(message))
                if msg.message == WM_HOTKEY:
                    callback = self._callbacks.get(int(msg.w_param))
                    if callback is not None:
                        callback()
                        return True, 0
        except Exception:  # noqa: BLE001
            pass
        return False, 0
