"""热键自检：文本解析 / 规范显示 / 真实注册与注销。

用法：.venv\\Scripts\\python.exe tests\\16-hotkey-check.py

不模拟按键：合成热键不能证明目标程序收得到，真实触发要在浏览器里手按。
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from recttrans.hotkey import HotkeyManager, normalize_sequence, parse_sequence

VALID = {
    "Ctrl+Alt+Q": "Ctrl+Alt+Q",
    "ctrl+alt+q": "Ctrl+Alt+Q",
    "Control+Alt+Q": "Ctrl+Alt+Q",
    "Ctrl+Shift+F9": "Ctrl+Shift+F9",
    "ctrl+alt+space": "Ctrl+Alt+Space",
    "Alt+Shift+Esc": "Alt+Shift+Esc",
    "Ctrl+Alt+1": "Ctrl+Alt+1",
}

INVALID = ["Q", "Ctrl+Alt+Nope", "Ctrl+Alt+", "", "Ctrl", "F25", "Ctrl+Alt+F25"]


def main() -> int:
    failures = 0

    for text, expected in VALID.items():
        actual = normalize_sequence(text)
        ok = actual == expected
        failures += 0 if ok else 1
        print(f"[{'OK' if ok else 'FAIL'}] {text!r} -> {actual!r}（期望 {expected!r}）")

    for text in INVALID:
        parsed = parse_sequence(text)
        ok = parsed is None
        failures += 0 if ok else 1
        print(f"[{'OK' if ok else 'FAIL'}] 非法输入 {text!r} -> {parsed!r}")

    manager = HotkeyManager()
    hotkey_id = 0
    for attempt in ("Ctrl+Alt+F12", "Ctrl+Alt+F11", "Ctrl+Alt+F10"):
        parsed = parse_sequence(attempt)
        assert parsed is not None
        hotkey_id = manager.register(parsed[0], parsed[1], lambda: None)
        if hotkey_id:
            print(f"[OK] 真实注册成功：{attempt}（id={hotkey_id}）")
            manager.unregister(hotkey_id)
            again = manager.register(parsed[0], parsed[1], lambda: None)
            print(f"[{'OK' if again else 'FAIL'}] 注销后可再次注册（id={again}）")
            failures += 0 if again else 1
            manager.unregister(again)
            break
        print(f"[SKIP] {attempt} 已被占用，换下一个")
    else:
        print("[FAIL] 三个候选组合都被占用，无法验证注册/注销")
        failures += 1

    print(f"\n结果：{'全部通过' if failures == 0 else f'{failures} 项失败'}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
