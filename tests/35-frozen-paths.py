"""打包路径自检：frozen 模式下配置/历史指向 exe 所在目录。

用法：.venv\\Scripts\\python.exe tests\\35-frozen-paths.py
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from recttrans import config, history


def main() -> int:
    failures = 0

    def check(label: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        failures += 0 if ok else 1
        print(f"[{'OK' if ok else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")

    original_frozen = getattr(sys, "frozen", None)
    original_exec = sys.executable
    try:
        sys.frozen = True
        sys.executable = r"D:\fake\RectTranslate\RectTranslate.exe"
        expected = pathlib.Path(r"D:\fake\RectTranslate")
        check("config 目录", config._app_dir() == expected, str(config._app_dir()))
        check("history 目录", history._app_dir() == expected, str(history._app_dir()))
    finally:
        sys.executable = original_exec
        if original_frozen is None:
            del sys.frozen
        else:
            sys.frozen = original_frozen

    check(
        "非打包模式回到源码目录",
        config._app_dir() == pathlib.Path(config.__file__).resolve().parent.parent,
        str(config._app_dir()),
    )

    print(f"结果：{'全部通过' if failures == 0 else f'{failures} 项失败'}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
