"""设置面板「选框外观」自检：默认值回显、点击即时发信号、保存写入配置。

用法：.venv\\Scripts\\python.exe tests\\26-settings-frame.py
"""

from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication

from recttrans.config import ensure_config, load_config, save_config
from recttrans.settings_window import SettingsWindow

_APP = None


def main() -> int:
    global _APP
    _APP = QApplication(sys.argv)
    ensure_config()
    original = json.loads(json.dumps(load_config()))
    failures = 0

    def check(label: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        failures += 0 if ok else 1
        print(f"[{'OK' if ok else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")

    try:
        window = SettingsWindow(original, current_hotkey="Ctrl+Shift+Q")
        check(
            "默认值回显",
            window._frame_style == {"color": "#FFA800", "thickness": 6, "length": 48},
            str(window._frame_style),
        )

        emitted: list[dict] = []
        window.frame_style_changed.connect(lambda style: emitted.append(style))
        window._color_buttons["#0078FF"].click()
        window._thick_buttons[8].click()
        window._length_buttons[64].click()
        expected = {"color": "#0078FF", "thickness": 8, "length": 64}
        check("点击即时发信号", emitted and emitted[-1] == expected, str(emitted[-1:]))

        window._save()
        saved = load_config()
        check("保存写入配置", saved.get("frame") == expected, str(saved.get("frame")))
    finally:
        save_config(original)

    print(f"结果：{'全部通过' if failures == 0 else f'{failures} 项失败'}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
