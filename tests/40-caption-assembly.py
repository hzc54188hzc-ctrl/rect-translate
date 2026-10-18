"""滚动字幕组装自检：尾部留白、重复词过滤、按停顿/标点切句。

用法：.venv\\Scripts\\python.exe tests\\40-caption-assembly.py
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from recttrans.caption import CaptionAssembler, is_partial


def word(start: float, end: float, text: str) -> dict:
    return {"start": start, "end": end, "text": text}


def main() -> int:
    failures = 0

    def check(label: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        failures += 0 if ok else 1
        print(f"[{'OK' if ok else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")

    first = [
        word(0.0, 0.4, "Hello"),
        word(0.4, 0.9, "world"),
        word(0.9, 1.3, "this"),
        word(1.3, 1.7, "is"),
        word(1.7, 2.2, "a"),
        word(2.2, 2.4, "test"),
        word(2.4, 2.8, "of"),
        word(2.8, 3.0, "speech"),
    ]
    caption = CaptionAssembler(max_words=14)
    changed = caption.add_window(first, 0.0, 3.0)
    current, previous = caption.snapshot()
    check("有词提交", bool(changed))
    check(
        "尾部 0.3 秒留给下一窗",
        current == "Hello world this is a test",
        current,
    )
    check("提交位置停在 2.4 秒", abs(caption.committed_end - 2.4) < 1e-6)
    check("尚未切句", previous == "", previous)

    second = [
        word(0.1, 0.5, "is"),  # 已提交，重复
        word(0.5, 1.0, "a"),
        word(1.0, 1.2, "test"),
        word(1.2, 1.6, "of"),
        word(1.6, 2.0, "speech"),
        word(2.0, 2.3, "with"),
        word(2.3, 2.7, "words"),
    ]
    changed = caption.add_window(second, 1.2, 3.0)
    current, previous = caption.snapshot()
    check("第二个窗口有新词", bool(changed))
    check(
        "重复词不重复提交",
        current == "Hello world this is a test of speech with words",
        current,
    )
    check("第二个窗口提交到 3.9 秒", abs(caption.committed_end - 3.9) < 1e-6)

    third = [
        word(0.1, 0.5, "again."),
    ]
    caption.add_window(third, 3.9, 1.2)
    current, previous = caption.snapshot()
    check(
        "句号触发切句",
        previous.endswith("again.") and current == "",
        f"prev={previous!r} cur={current!r}",
    )

    gap = CaptionAssembler()
    gap.add_window([word(0.0, 0.4, "First")], 0.0, 2.0)
    gap.add_window([word(0.0, 0.4, "sentence")], 0.4, 2.0)
    gap.add_window([word(0.0, 0.4, "Later")], 3.5, 2.0)
    current, previous = gap.snapshot()
    check("停顿 3.1 秒切句", previous == "First sentence" and current == "Later",
          f"prev={previous!r} cur={current!r}")

    limit = CaptionAssembler(max_words=3)
    limit.add_window(
        [word(0.0, 0.4, "a"), word(0.4, 0.8, "b"), word(0.8, 1.2, "c")],
        0.0,
        2.0,
    )
    current, previous = limit.snapshot()
    check("达到词数上限切句", previous == "a b c" and current == "",
          f"prev={previous!r} cur={current!r}")

    overlap = CaptionAssembler()
    overlap.add_window([word(0.0, 1.0, "one")], 0.0, 2.0)
    overlap.add_window([word(0.0, 1.2, "one")], 0.0, 2.0)
    current, _ = overlap.snapshot()
    check("同一窗口重复喂入不重复", current == "one", current)

    paused = CaptionAssembler()
    paused.add_window([word(0.0, 0.4, "Half")], 0.0, 2.0)
    paused.break_current()
    current, previous = paused.snapshot()
    check(
        "暂停时半句收尾",
        current == "" and previous == "Half",
        f"prev={previous!r} cur={current!r}",
    )

    check("省略号识别为半句", is_partial("等她去……") and is_partial("那等她..."))
    check("完整句不算半句", not is_partial("等她走了。"))

    print(f"结果：{'全部通过' if failures == 0 else f'{failures} 项失败'}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
