"""运行适合 CI 的回归测试（不含联网、真实 OCR、手动鼠标项）。

用法：.venv\\Scripts\\python.exe tests\\run_all.py
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys

TESTS = [
    "12-zone-check.py",
    "16-hotkey-check.py",
    "17-quick-grab.py",
    "18-hotkey-recorder.py",
    "19-popup-pin.py",
    "20-popup-size.py",
    "21-terms.py",
    "22-popup-links.py",
    "23-controls.py",
    "24-frame-paint.py",
    "25-frame-style.py",
    "26-settings-frame.py",
    "27-frame-geometry.py",
    "28-activate-event.py",
    "29-first-run.py",
    "30-ocr-auto.py",
    "31-translate-fallback.py",
    "32-window-rect.py",
]


def main() -> int:
    root = pathlib.Path(__file__).resolve().parents[1]
    failed: list[str] = []
    for name in TESTS:
        path = root / "tests" / name
        print(f"\n=== {name} ===", flush=True)
        if not path.exists():
            print(f"[MISSING] {path}")
            failed.append(name)
            continue
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        result = subprocess.run([sys.executable, str(path)], cwd=str(root), env=env)
        if result.returncode != 0:
            failed.append(name)

    print("\n" + "=" * 40)
    if failed:
        print(f"失败 {len(failed)} 项：{', '.join(failed)}")
        return 1
    print(f"全部通过（{len(TESTS)} 个脚本）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
