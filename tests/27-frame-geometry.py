"""选框几何记忆自检：保存只改 frame.geometry、启动恢复、离屏回退、--rect 优先。

用法：.venv\\Scripts\\python.exe tests\\27-frame-geometry.py
"""

from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication

from recttrans.main import _parse_rect, save_frame_geometry

_APP = None


def main() -> int:
    global _APP
    _APP = QApplication(sys.argv)
    failures = 0

    def check(label: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        failures += 0 if ok else 1
        print(f"[{'OK' if ok else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")

    base = {
        "translate": {"provider": "deepseek", "api_key": "sk-test"},
        "quick_hotkey": "Ctrl+Shift+Q",
        "frame": {"color": "#FFA800", "thickness": 6, "length": 48},
    }
    path = pathlib.Path(__file__).with_name("_frame_geometry.json")
    try:
        path.write_text(json.dumps(base, ensure_ascii=False), encoding="utf-8")

        config = json.loads(json.dumps(base))
        save_frame_geometry(config, QRect(100, 120, 300, 90), path)
        saved = json.loads(path.read_text(encoding="utf-8"))
        check(
            "写入 frame.geometry",
            saved["frame"]["geometry"] == {"x": 100, "y": 120, "w": 300, "h": 90},
            str(saved["frame"]["geometry"]),
        )
        check(
            "保留其它字段",
            saved["translate"]["api_key"] == "sk-test"
            and saved["frame"]["color"] == "#FFA800",
            str(saved["translate"]),
        )
    finally:
        if path.exists():
            path.unlink()

    restored = _parse_rect([], {"frame": {"geometry": {"x": 100, "y": 120, "w": 300, "h": 90}}})
    check("启动恢复几何", restored == QRect(100, 120, 300, 90), str(restored.getRect()))

    offscreen = _parse_rect(
        [], {"frame": {"geometry": {"x": 99999, "y": 99999, "w": 300, "h": 90}}}
    )
    check(
        "离屏坐标回退到主屏中央",
        offscreen.x() < 1900 and offscreen.y() < 1000,
        str(offscreen.getRect()),
    )

    forced = _parse_rect(
        ["--rect", "10,20,300,90"],
        {"frame": {"geometry": {"x": 100, "y": 120, "w": 300, "h": 90}}},
    )
    check("--rect 优先", forced == QRect(10, 20, 300, 90), str(forced.getRect()))

    print(f"结果：{'全部通过' if failures == 0 else f'{failures} 项失败'}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
