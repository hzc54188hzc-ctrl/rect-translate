"""第二次启动唤出既有实例：命名事件置位 / 消费 / 自动复位。

用法：.venv\\Scripts\\python.exe tests\\28-activate-event.py
"""

from __future__ import annotations

import ctypes
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from recttrans.main import (
    _consume_activate_event,
    _create_activate_event,
    _signal_existing_instance,
)

NAME = "Local\\RectTranslateActivateTest"


def main() -> int:
    failures = 0

    def check(label: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        failures += 0 if ok else 1
        print(f"[{'OK' if ok else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")

    handle = _create_activate_event(NAME)
    check("创建命名事件", bool(handle), str(handle))
    if not handle:
        print("结果：1 项失败")
        return 1

    try:
        check("触发前没有信号", not _consume_activate_event(handle))
        check("第二次启动可置位", _signal_existing_instance(NAME))
        check("已有实例收到信号", _consume_activate_event(handle))
        check("事件自动复位", not _consume_activate_event(handle))
    finally:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CloseHandle(ctypes.c_void_p(handle))

    print(f"结果：{'全部通过' if failures == 0 else f'{failures} 项失败'}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
