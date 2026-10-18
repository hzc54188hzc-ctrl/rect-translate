"""同传设置自检：上下文句数、显示行数写入配置。

用法：.venv\\Scripts\\python.exe tests\\50-caption-settings.py
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication

from recttrans import settings_window
from recttrans.config import load_config

_APP = None


def main() -> int:
    global _APP
    _APP = QApplication.instance() or QApplication(sys.argv)
    failures = 0

    def check(label: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        failures += 0 if ok else 1
        print(f"[{'OK' if ok else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")

    captured: dict = {}
    original = settings_window.save_config
    settings_window.save_config = lambda config: captured.update(config)
    window = None
    try:
        window = settings_window.SettingsWindow(load_config())
        check(
            "默认两项存在",
            window._caption_context in (1, 2, 3) and window._caption_lines in (2, 3, 4),
            f"{window._caption_context} 句 / {window._caption_lines} 行",
        )
        window._set_caption_context(3)
        window._set_caption_lines(4)
        window._save()
    finally:
        settings_window.save_config = original
        if window is not None:
            window.hide()

    caption = captured.get("caption") or {}
    check(
        "保存上下文 3 句",
        caption.get("context_lines") == 3,
        str(caption),
    )
    check(
        "保存显示 4 行",
        caption.get("display_lines") == 4,
        str(caption),
    )

    print(f"结果：{'全部通过' if failures == 0 else f'{failures} 项失败'}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
