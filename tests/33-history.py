"""历史记录自检：新增、去重、上限、落盘回读、坏文件容错。

用法：.venv\\Scripts\\python.exe tests\\33-history.py
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from recttrans.history import MAX_ENTRIES, add_entry, load_history, save_history


def main() -> int:
    failures = 0

    def check(label: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        failures += 0 if ok else 1
        print(f"[{'OK' if ok else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")

    entries: list[dict] = []
    entries = add_entry(entries, "hello", "你好", "selection", now="2026-10-17 21:00")
    check("新增一条", len(entries) == 1 and entries[0]["kind"] == "selection", str(entries))

    entries = add_entry(entries, "hello", "你好", "selection", now="2026-10-17 21:01")
    check("连续重复不重复记录", len(entries) == 1, str(len(entries)))

    entries = add_entry(entries, "world", "世界", "ocr", now="2026-10-17 21:02")
    check(
        "最新在最前",
        len(entries) == 2 and entries[0]["translation"] == "世界",
        str([e["translation"] for e in entries]),
    )

    entries = add_entry(entries, "", "   ", "ocr")
    check("空译文不记录", len(entries) == 2)

    for index in range(MAX_ENTRIES + 10):
        entries = add_entry(entries, f"src{index}", f"译文{index}", "ocr", now="t")
    check("上限截断", len(entries) == MAX_ENTRIES, str(len(entries)))

    path = pathlib.Path(__file__).with_name("_history_test.json")
    try:
        save_history(entries, path)
        restored = load_history(path)
        check(
            "落盘回读",
            len(restored) == MAX_ENTRIES and restored[0]["translation"] == entries[0]["translation"],
            str(len(restored)),
        )
        path.write_text("not json", encoding="utf-8")
        check("坏文件返回空列表", load_history(path) == [])
    finally:
        if path.exists():
            path.unlink()

    print(f"结果：{'全部通过' if failures == 0 else f'{failures} 项失败'}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
