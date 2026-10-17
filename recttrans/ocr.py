"""Windows 内置 OCR（Windows.Media.Ocr）封装：输入 PNG 字节，输出识别文本。

用系统自带引擎，离线、免模型下载、免 API key。

两个实测要点：
- 小字号（约 13px）直接识别很糟；抓图侧用 GDI StretchBlt 先放大 2 倍再传进来；
- 中文模型读小号英文会拆成「Entre p s 皂」这类碎片，所以 auto 模式同时跑
  中英两套引擎，按结果结构选更合理的那个。
"""

from __future__ import annotations

import asyncio
import re

from winrt.windows.globalization import Language
from winrt.windows.graphics.imaging import BitmapDecoder
from winrt.windows.media.ocr import OcrEngine
from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream

_CJK_CHAR = re.compile(r"[\u4e00-\u9fff]")
_LATIN_WORD = re.compile(r"[A-Za-z]+")


def available_languages() -> list[str]:
    """返回系统已安装的 OCR 语言标签。"""
    return sorted(lang.language_tag for lang in OcrEngine.available_recognizer_languages)


async def _stream_from_bytes(data: bytes) -> InMemoryRandomAccessStream:
    stream = InMemoryRandomAccessStream()
    writer = DataWriter(stream)
    writer.write_bytes(data)
    await writer.store_async()
    await writer.flush_async()
    writer.detach_stream()
    stream.seek(0)
    return stream


async def _bitmap_async(png_bytes: bytes):
    decoder = await BitmapDecoder.create_async(await _stream_from_bytes(png_bytes))
    return await decoder.get_software_bitmap_async()


async def _recognize_with(bitmap, language_tag: str) -> str | None:
    engine = OcrEngine.try_create_from_language(Language(language_tag))
    if engine is None:
        return None
    result = await engine.recognize_async(bitmap)
    return result.text


def _resolve_tag(preferred: str | None) -> str | None:
    """把 auto/zh/en 解析成已安装的语言标签；auto 返回 None 表示双引擎。"""
    value = (preferred or "auto").lower()
    if value in ("auto", ""):
        return None
    want = "zh" if value.startswith("zh") else "en" if value.startswith("en") else None
    if want is None:
        return None
    for tag in available_languages():
        if tag.lower().startswith(want):
            return tag
    return None


def _auto_tags() -> list[str]:
    langs = available_languages()
    zh = next((tag for tag in langs if tag.lower().startswith("zh")), None)
    en = next((tag for tag in langs if tag.lower().startswith("en")), None)
    tags = [tag for tag in (zh, en) if tag]
    return tags or langs[:1]


def score_text(text: str) -> float:
    """给 OCR 结果打分：长英文单词、连续汉字加分，孤立单字符扣分。"""
    words = _LATIN_WORD.findall(text)
    long_words = [word for word in words if len(word) >= 3]
    single = [word for word in words if len(word) == 1]
    cjk = _CJK_CHAR.findall(text)
    runs = re.findall(r"[\u4e00-\u9fff]{2,}", text)
    return (
        len(long_words) * 2
        + len(cjk) * 0.6
        + len(runs) * 1.5
        - len(single) * 0.8
    )


async def _recognize_async(png_bytes: bytes, language_tag: str | None) -> str:
    bitmap = await _bitmap_async(png_bytes)
    tag = _resolve_tag(language_tag)
    if tag:
        text = await _recognize_with(bitmap, tag)
        if text is not None:
            return text

    results = []
    for candidate in _auto_tags():
        text = await _recognize_with(bitmap, candidate)
        if text is not None:
            results.append(text)
    if not results:
        raise RuntimeError("系统里没有可用的 OCR 语言包")
    return max(results, key=score_text)


def recognize_png(png_bytes: bytes, language_tag: str | None = None) -> str:
    """识别 PNG 图片中的文字。必须在同一线程内独立调用（内部自建事件循环）。"""
    return asyncio.run(_recognize_async(png_bytes, language_tag))
