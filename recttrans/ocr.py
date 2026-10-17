"""Windows 内置 OCR（Windows.Media.Ocr）封装：输入 PNG 字节，输出识别文本。

用系统自带引擎，离线、免模型下载、免 API key。
"""

from __future__ import annotations

import asyncio

from winrt.windows.globalization import Language
from winrt.windows.graphics.imaging import BitmapDecoder
from winrt.windows.media.ocr import OcrEngine
from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream


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


async def _recognize_async(png_bytes: bytes, language_tag: str | None) -> str:
    decoder = await BitmapDecoder.create_async(await _stream_from_bytes(png_bytes))
    bitmap = await decoder.get_software_bitmap_async()

    engine = None
    if language_tag:
        engine = OcrEngine.try_create_from_language(Language(language_tag))
    if engine is None:
        engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        raise RuntimeError("系统里没有可用的 OCR 语言包")

    result = await engine.recognize_async(bitmap)
    return result.text


def recognize_png(png_bytes: bytes, language_tag: str | None = None) -> str:
    """识别 PNG 图片中的文字。必须在同一线程内独立调用（内部自建事件循环）。"""
    return asyncio.run(_recognize_async(png_bytes, language_tag))
