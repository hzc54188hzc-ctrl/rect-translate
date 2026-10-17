"""划词取文本自检：验证「检测到复制 → 取文本 → 还原剪贴板」这条逻辑。

用法：.venv\\Scripts\\python.exe tests\\17-quick-grab.py

说明：沙箱桌面收不到 `keybd_event` 注入的按键（实测窗口有焦点也不触发复制），
所以这里替换掉「发送 Ctrl+C」这一步，只验证剪贴板序列号判断与还原逻辑；
真实按键路径必须由使用者在交互桌面手按热键验证。
"""

from __future__ import annotations

import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import base64

from PySide6.QtCore import QByteArray, QMimeData
from PySide6.QtWidgets import QApplication

from recttrans import quick
from recttrans.quick import grab_selected_text

CONTENT = "Hello world from the selection test 2026."
PREVIOUS = "previous clipboard content"
PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

_APP = None


def main() -> int:
    global _APP
    _APP = QApplication(sys.argv)
    clipboard = _APP.clipboard()
    failures = 0

    original_send = quick._send_ctrl_c

    def fake_copy_text(user32=None) -> None:
        # 模拟目标程序写入剪贴板；真实场景里这段是别的进程完成的，
        # 这里让事件循环跑一下，Windows 才会发布新内容。
        clipboard.setText(CONTENT)
        _APP.processEvents()
    try:
        # 1) 复制成功：应返回文本并还原原剪贴板
        clipboard.setText(PREVIOUS)
        quick._send_ctrl_c = fake_copy_text
        text = grab_selected_text()
        restored = clipboard.text()
        ok = text.strip() == CONTENT and restored == PREVIOUS
        failures += 0 if ok else 1
        print(f"[{'OK' if ok else 'FAIL'}] 取到 {text!r}，剪贴板还原为 {restored!r}")

        # 2) 没有发生复制：返回空串，剪贴板原样保留
        clipboard.setText("something else")
        quick._send_ctrl_c = lambda user32: None
        text = grab_selected_text()
        kept = clipboard.text()
        ok = text == "" and kept == "something else"
        failures += 0 if ok else 1
        print(f"[{'OK' if ok else 'FAIL'}] 未复制时返回空串，剪贴板保持 {kept!r}")

        # 3) 复制到空内容：返回空串
        clipboard.setText(PREVIOUS)
        quick._send_ctrl_c = lambda user32: clipboard.setText("   ")
        text = grab_selected_text()
        ok = text == ""
        failures += 0 if ok else 1
        print(f"[{'OK' if ok else 'FAIL'}] 复制到空白内容时返回空串")

        # 4) 剪贴板原本是图片/文件等非文本内容：取词后必须原样还原
        demo = QMimeData()
        demo.setData("image/png", QByteArray(PNG_1PX))
        clipboard.clear()
        _APP.processEvents()
        clipboard.setMimeData(demo)
        for _ in range(10):
            _APP.processEvents()
            time.sleep(0.02)
        quick._send_ctrl_c = fake_copy_text
        text = grab_selected_text()
        # 剪贴板是通过 Windows 消息异步发布的，读之前让事件循环跑一会儿
        for _ in range(10):
            _APP.processEvents()
            time.sleep(0.02)
        formats = clipboard.mimeData().formats()
        ok = text.strip() == CONTENT and "image/png" in formats
        failures += 0 if ok else 1
        print(f"[{'OK' if ok else 'FAIL'}] 非文本剪贴板被还原：{formats}")
    finally:
        quick._send_ctrl_c = original_send

    print(f"结果：{'全部通过' if failures == 0 else f'{failures} 项失败'}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
