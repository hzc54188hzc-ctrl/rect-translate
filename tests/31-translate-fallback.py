"""翻译容错自检：瞬时错误重试一次、持续失败回退免费通道、401 不重试。

用法：.venv\\Scripts\\python.exe tests\\31-translate-fallback.py
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import recttrans.translator as translator

CONFIG = {"translate": {"provider": "deepseek"}}


def main() -> int:
    failures = 0

    def check(label: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        failures += 0 if ok else 1
        print(f"[{'OK' if ok else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")

    original_llm = translator._translate_llm
    original_free = translator._translate_free
    original_sleep = translator.time.sleep
    translator.time.sleep = lambda _seconds: None  # 测试里不真等
    try:
        # 1) 第一次失败、第二次成功：重试一次，不走回退
        calls = {"n": 0}

        def flaky(text, config, timeout, system=None):
            calls["n"] += 1
            if calls["n"] == 1:
                raise translator.TranslateError("接口返回 500：boom")
            return '{"translation": "你好", "terms": []}'

        translator._translate_llm = flaky
        translator._translate_free = lambda *a, **k: "免费译文"
        result = translator.translate_rich("hello", CONFIG)
        check("瞬时错误重试成功", result["text"] == "你好", result["text"])
        check("重试只多调用一次", calls["n"] == 2, str(calls))
        check("成功时不标记回退", "fallback" not in result)

        # 2) 持续失败：回退免费通道
        calls["n"] = 0

        def broken(text, config, timeout, system=None):
            calls["n"] += 1
            raise translator.TranslateError("接口返回 500：down")

        translator._translate_llm = broken
        result = translator.translate_rich("hello", CONFIG)
        check("持续失败回退免费通道", result["text"] == "免费译文", result["text"])
        check("回退标记", result.get("fallback") == "free", str(result.get("fallback")))
        check("回退前重试一次", calls["n"] == 2, str(calls))

        # 3) 401 不重试，直接回退
        calls["n"] = 0

        def unauthorized(text, config, timeout, system=None):
            calls["n"] += 1
            raise translator.TranslateError("接口返回 401：bad key")

        translator._translate_llm = unauthorized
        result = translator.translate_rich("hello", CONFIG)
        check("401 不重试", calls["n"] == 1, str(calls))
        check("401 也回退免费", result.get("fallback") == "free")

        # 4) 两边都失败：抛错
        def free_broken(*a, **k):
            raise translator.TranslateError("免费通道不可用")

        translator._translate_free = free_broken
        try:
            translator.translate_rich("hello", CONFIG)
            check("全部失败时抛错", False)
        except translator.TranslateError:
            check("全部失败时抛错", True)
    finally:
        translator._translate_llm = original_llm
        translator._translate_free = original_free
        translator.time.sleep = original_sleep

    print(f"结果：{'全部通过' if failures == 0 else f'{failures} 项失败'}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
