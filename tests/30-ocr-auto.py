"""OCR 自检：中英双引擎评分、语言解析、放大抓图签名、空白图冒烟。

用法：.venv\\Scripts\\python.exe tests\\30-ocr-auto.py
"""

from __future__ import annotations

import inspect
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication

from recttrans import capture
from recttrans.frame import RegionFrame
from recttrans.ocr import _auto_tags, _resolve_tag, recognize_png, score_text

_APP = None


def main() -> int:
    global _APP
    _APP = QApplication(sys.argv)
    failures = 0

    def check(label: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        failures += 0 if ok else 1
        print(f"[{'OK' if ok else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")

    en_text = (
        "Free, Pro, & Team Enterprise Cloud Enterprise Server 3.22 "
        "Enterprise Server 3.21 All Enterprise Server releases"
    )
    zh_garbage = (
        "F 皂 》 Pro, & Team Entre p s 皂 Cloud Entre p s 皂 S 皂 、皂 r 3 、22 "
        "Entre p s 皂 S 皂 、皂 r 3 、21"
    )
    check(
        "英文结果优先于中文模型碎片",
        score_text(en_text) > score_text(zh_garbage),
        f"{score_text(en_text):.1f} vs {score_text(zh_garbage):.1f}",
    )

    tags = _auto_tags()
    check(
        "自动模式包含中英两套引擎",
        any(t.lower().startswith("zh") for t in tags)
        and any(t.lower().startswith("en") for t in tags),
        str(tags),
    )
    check("zh 解析到中文标签", (_resolve_tag("zh") or "").startswith("zh"))
    check("en 解析到英文标签", (_resolve_tag("en") or "").startswith("en"))
    check("auto 返回 None（双引擎）", _resolve_tag("auto") is None)

    blank = capture.encode_png(300, 80, bytes([255, 255, 255, 255]) * 300 * 80)
    ok = all(recognize_png(blank, tag) == "" for tag in ("auto", "zh", "en"))
    check("空白图三种模式不报错", ok)

    params = inspect.signature(capture.grab_raw).parameters
    check("抓图支持 scale 参数", "scale" in params, str(list(params)))

    frame = RegionFrame(QRect(0, 0, 420, 110))
    frame.set_ocr_language("en")
    check("选框记录 OCR 语言", frame._ocr_language == "en", frame._ocr_language)
    frame.set_ocr_language("bogus")
    check("非法值回退 auto", frame._ocr_language == "auto", frame._ocr_language)

    print(f"结果：{'全部通过' if failures == 0 else f'{failures} 项失败'}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
