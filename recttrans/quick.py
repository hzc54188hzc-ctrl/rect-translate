"""划词翻译：取当前选中的文本（模拟 Ctrl+C），不经过 OCR。

关键点：热键触发的瞬间，用户的手指通常还压在 Ctrl/Shift/Alt 上。
此时直接发 Ctrl+C，系统收到的是「Ctrl+Shift+C」这类组合——在 Chrome 里
刚好是「检查元素」，会弹出 DevTools 而不是复制。所以必须先等修饰键松开。
"""

from __future__ import annotations

import ctypes
import time

from PySide6.QtCore import QByteArray, QMimeData
from PySide6.QtGui import QGuiApplication

VK_CONTROL = 0x11
VK_SHIFT = 0x10
VK_MENU = 0x12
VK_LWIN = 0x5B
VK_RWIN = 0x5C
VK_C = 0x43
KEYEVENTF_KEYUP = 0x0002
MODIFIER_WAIT = 0.8
CLIPBOARD_WAIT = 0.9


def _modifiers_down(user32) -> bool:
    keys = (VK_CONTROL, VK_SHIFT, VK_MENU, VK_LWIN, VK_RWIN)
    return any(user32.GetAsyncKeyState(vk) & 0x8000 for vk in keys)


def _wait_modifiers_released(user32, timeout: float = MODIFIER_WAIT) -> None:
    """等用户松开热键的修饰键，超时也继续（总不能让热键完全失效）。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _modifiers_down(user32):
            return
        time.sleep(0.02)


def _send_ctrl_c(user32) -> None:
    user32.keybd_event(VK_CONTROL, 0, 0, 0)
    user32.keybd_event(VK_C, 0, 0, 0)
    user32.keybd_event(VK_C, 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)


def _snapshot_clipboard(clipboard) -> QMimeData | None:
    """把剪贴板所有格式（文本、图片、文件、HTML）整体存一份。"""
    source = clipboard.mimeData()
    if source is None:
        return None
    snapshot = QMimeData()
    for fmt in source.formats():
        try:
            snapshot.setData(fmt, QByteArray(source.data(fmt)))
        except Exception:  # noqa: BLE001
            continue
    return snapshot


def _restore_clipboard(clipboard, snapshot: QMimeData | None) -> None:
    try:
        if snapshot is None:
            clipboard.clear()
        else:
            clipboard.setMimeData(snapshot)  # 所有权交给剪贴板
    except Exception:  # noqa: BLE001
        pass


def grab_selected_text() -> str:
    """复制当前选中内容并还原剪贴板。没有取到文本时返回空串。

    用剪贴板序列号判断「是否真的发生了复制」：比对比文本内容更可靠，
    用户连续两次复制同一段文字也能正常工作。
    """
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    _wait_modifiers_released(user32)

    clipboard = QGuiApplication.clipboard()
    previous = _snapshot_clipboard(clipboard)
    sequence_before = user32.GetClipboardSequenceNumber()
    _send_ctrl_c(user32)

    deadline = time.monotonic() + CLIPBOARD_WAIT
    copied = False
    while time.monotonic() < deadline:
        if user32.GetClipboardSequenceNumber() != sequence_before:
            copied = True
            if clipboard.text().strip():
                break
        time.sleep(0.03)

    text = clipboard.text()
    if copied:
        _restore_clipboard(clipboard, previous)  # 原样还原（含图片/文件/HTML）
    if not copied or not text.strip():
        return ""
    return text
