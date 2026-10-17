"""热键录制自检：点击后按键 → 自动读出组合，Esc 取消，缺修饰键被拒。

用法：.venv\\Scripts\\python.exe tests\\18-hotkey-recorder.py
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from recttrans.config import ensure_config, load_config
from recttrans.settings_window import SettingsWindow

_APP = None


def main() -> int:
    global _APP
    _APP = QApplication(sys.argv)
    ensure_config()
    window = SettingsWindow(load_config(), current_hotkey="Ctrl+Shift+Q")
    edit = window._hotkey
    failures = 0

    def check(label: str, actual: str, expected: str) -> None:
        nonlocal failures
        ok = actual == expected
        failures += 0 if ok else 1
        print(f"[{'OK' if ok else 'FAIL'}] {label}: {actual!r}")

    # 1) 录制 Ctrl+Shift+Q
    edit.start_recording()
    QTest.keyPress(
        edit,
        Qt.Key.Key_Q,
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
    )
    check("录制 Ctrl+Shift+Q", edit.text(), "Ctrl+Shift+Q")

    # 2) 录制功能键 Ctrl+Alt+F9
    edit.start_recording()
    QTest.keyPress(
        edit,
        Qt.Key.Key_F9,
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier,
    )
    check("录制 Ctrl+Alt+F9", edit.text(), "Ctrl+Alt+F9")

    # 3) 只按修饰键时显示预览，不误判为完成
    edit.start_recording()
    QTest.keyPress(edit, Qt.Key.Key_Control, Qt.KeyboardModifier.ControlModifier)
    check("只按 Ctrl 的预览", edit.text(), "Ctrl+…")

    # 4) Esc 取消，恢复录制前的值
    QTest.keyPress(edit, Qt.Key.Key_Escape, Qt.KeyboardModifier.ControlModifier)
    check("Esc 取消后恢复", edit.text(), "Ctrl+Alt+F9")

    # 5) 不带修饰键被拒绝
    edit.start_recording()
    QTest.keyPress(edit, Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier)
    check("无修饰键被拒", edit.text(), "需要至少一个修饰键，请重按")

    # 6) 常用系统快捷键被拒绝（Ctrl+Z 会抢走所有程序的撤销）
    edit.start_recording()
    QTest.keyPress(edit, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    check(
        "Ctrl+Z 被拒绝",
        edit.text(),
        "Ctrl+Z 是常用快捷键，会抢占其它程序，请换一个",
    )

    print(f"结果：{'全部通过' if failures == 0 else f'{failures} 项失败'}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
