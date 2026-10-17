"""首次运行自检：没有配置文件时自动生成免费通道配置，第二次不覆盖。

用法：.venv\\Scripts\\python.exe tests\\29-first-run.py
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from recttrans.config import ensure_config, load_config


def main() -> int:
    path = pathlib.Path(__file__).with_name("_first_run_config.json")
    failures = 0

    def check(label: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        failures += 0 if ok else 1
        print(f"[{'OK' if ok else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")

    try:
        if path.exists():
            path.unlink()
        check("首次创建配置", ensure_config(path) is True)
        config = load_config(path)
        check(
            "默认免费通道且无 key 可加载",
            config["translate"]["provider"] == "free"
            and config["translate"]["api_key"] == "",
            str(config["translate"]["provider"]),
        )
        check("再次调用不覆盖", ensure_config(path) is False)
    finally:
        if path.exists():
            path.unlink()

    print(f"结果：{'全部通过' if failures == 0 else f'{failures} 项失败'}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
