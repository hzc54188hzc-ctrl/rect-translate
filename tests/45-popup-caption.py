"""统一浮窗自检：同传字幕复用译文浮窗，字体、换行、主题与模式切换。

用法：.venv\\Scripts\\python.exe tests\\45-popup-caption.py
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication

from recttrans.popup import ResultPopup

_APP = None


def main() -> int:
    global _APP
    _APP = QApplication.instance() or QApplication(sys.argv)
    failures = 0

    def check(label: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        failures += 0 if ok else 1
        print(f"[{'OK' if ok else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")

    popup = ResultPopup()
    popup.show_caption()
    popup.set_caption(
        "Are you seriously gonna stay in here all day?",
        "I can't face mom if I see her.",
    )
    _APP.processEvents()
    try:
        check("当前句进入浮窗", popup.caption_text().startswith("Are you seriously"))
        check("上一句显示在原文行", popup.caption_previous().startswith("I can't"))
        check("字幕字号 17pt", abs(popup._translation.font().pointSizeF() - 17.0) < 0.2,
              str(popup._translation.font().pointSizeF()))
        check("状态行", popup.status_text() == "同声传译 · 本地识别", popup.status_text())
        check("字幕宽度收紧到 440 左右", 420 <= popup.width() <= 460, str(popup.width()))
        check("字幕最小高度 120", popup.height() >= 120, str(popup.height()))

        popup.set_caption("", "Previous sentence stays visible.")
        _APP.processEvents()
        check(
            "空当前句时保留上一句",
            popup.caption_text() == "Previous sentence stays visible.",
            popup.caption_text(),
        )

        long_line = "This is a long subtitle line that should wrap inside the popup instead of being cut off at the edge."
        popup.set_caption(long_line, "")
        _APP.processEvents()
        document = popup._translation.document()
        document.setTextWidth(popup.width() - 2 * 10)
        check("长句会换行", document.size().height() > 30,
              f"height={document.size().height():.0f}")

        popup.set_theme("dark")
        _APP.processEvents()
        check("深色主题保留字幕", popup.caption_text() == long_line)

        popup.set_content("source", "译文内容")
        _APP.processEvents()
        check("切回翻译模式字号 12pt",
              abs(popup._translation.font().pointSizeF() - 12.0) < 0.2,
              str(popup._translation.font().pointSizeF()))
        check("翻译内容不变", popup.translation_text() == "译文内容")

        popup.set_caption_bilingual("你打算在这里待一整天吗？", "Are you gonna stay here all day?")
        _APP.processEvents()
        check("中文作为大字", popup.caption_text().startswith("你打算"), popup.caption_text())
        check("英文作为小字", popup.caption_previous().startswith("Are you"), popup.caption_previous())
        popup.set_caption_bilingual("", "No Chinese yet.")
        _APP.processEvents()
        check("没有译文时英文顶到大字", popup.caption_text() == "No Chinese yet.", popup.caption_text())

        popup.set_caption_zh("这是纯中文字幕。", "这是上一句中文。")
        _APP.processEvents()
        check("纯中文模式主文本", popup.caption_text().endswith("这是纯中文字幕。"), popup.caption_text())
        check("纯中文模式包含上一句", "这是上一句中文。" in popup.caption_text(), popup.caption_text())
        popup.set_caption_zh("", "只有上一句中文。")
        _APP.processEvents()
        check("当前句为空时保留上一句", popup.caption_text() == "只有上一句中文。", popup.caption_text())

        popup.set_caption_zh_lines(["第一行字幕", "第二行字幕", "第三行字幕", "第四行字幕"])
        _APP.processEvents()
        check("最新一行在底部", popup.caption_text().endswith("第一行字幕"), popup.caption_text())
        check(
            "历史行都在滚动区",
            "第二行字幕" in popup.caption_text() and "第四行字幕" in popup.caption_text(),
            repr(popup.caption_text()),
        )
        check("三行模式高度固定", popup.height() >= 140, str(popup.height()))
        popup.set_caption_zh_lines(
            ["1", "2", "3", "4", "5"], display_lines=4
        )
        _APP.processEvents()
        check("四行模式更高", popup.height() >= 160, str(popup.height()))
    finally:
        popup.hide()

    print(f"结果：{'全部通过' if failures == 0 else f'{failures} 项失败'}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
