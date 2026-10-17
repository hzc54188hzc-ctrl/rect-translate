"""屏幕区域抓图，以及把自家窗口排除出屏幕捕获。

为什么整条抓图链路都不碰 Qt：本机实测 PySide6 6.12 + Python 3.14 下 QImage 必崩
（连 QImage.fill + save 都 6/6 访问违例，见 tests/06-qt-probe.py），而 QWidget 自绘
与纯标准库编 PNG 都 6/6 稳定。所以抓屏用 Windows GDI BitBlt，编码用标准库 zlib
自己写 PNG，完全不经过 QImage；界面仍用 Qt。
"""

from __future__ import annotations

import ctypes
import struct
import zlib

WDA_EXCLUDEFROMCAPTURE = 0x00000011
SRCCOPY = 0x00CC0020
DIB_RGB_COLORS = 0
HALFTONE = 4

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

# 句柄都是指针宽度，必须显式声明，否则 64 位上会被截断成 32 位而崩溃。
_user32.GetDC.restype = ctypes.c_void_p
_user32.GetDC.argtypes = [ctypes.c_void_p]
_user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_user32.SetWindowDisplayAffinity.argtypes = [ctypes.c_void_p, ctypes.c_uint]
_user32.SetWindowDisplayAffinity.restype = ctypes.c_int

_gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
_gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
_gdi32.CreateCompatibleBitmap.restype = ctypes.c_void_p
_gdi32.CreateCompatibleBitmap.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
_gdi32.SelectObject.restype = ctypes.c_void_p
_gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_gdi32.BitBlt.argtypes = [
    ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_uint,
]
_gdi32.BitBlt.restype = ctypes.c_int
_gdi32.SetStretchBltMode.argtypes = [ctypes.c_void_p, ctypes.c_int]
_gdi32.SetStretchBltMode.restype = ctypes.c_int
_gdi32.SetBrushOrgEx.argtypes = [
    ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_void_p,
]
_gdi32.SetBrushOrgEx.restype = ctypes.c_int
_gdi32.StretchBlt.argtypes = [
    ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    ctypes.c_uint,
]
_gdi32.StretchBlt.restype = ctypes.c_int
_gdi32.GetDIBits.argtypes = [
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint,
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint,
]
_gdi32.GetDIBits.restype = ctypes.c_int
_gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
_gdi32.DeleteDC.argtypes = [ctypes.c_void_p]


class _BitmapInfoHeader(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.c_uint32),
        ("biWidth", ctypes.c_int32),
        ("biHeight", ctypes.c_int32),
        ("biPlanes", ctypes.c_uint16),
        ("biBitCount", ctypes.c_uint16),
        ("biCompression", ctypes.c_uint32),
        ("biSizeImage", ctypes.c_uint32),
        ("biXPelsPerMeter", ctypes.c_int32),
        ("biYPelsPerMeter", ctypes.c_int32),
        ("biClrUsed", ctypes.c_uint32),
        ("biClrImportant", ctypes.c_uint32),
    ]


class _BitmapInfo(ctypes.Structure):
    _fields_ = [("bmiHeader", _BitmapInfoHeader), ("bmiColors", ctypes.c_uint32 * 3)]


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def encode_png(width: int, height: int, bgra: bytes) -> bytes:
    """把 GDI 给的 BGRA 原始像素编成 PNG（标准库实现，不经过 Qt）。"""
    pixels = bytearray(bgra)
    pixels[0::4], pixels[2::4] = pixels[2::4], pixels[0::4]  # BGRA -> RGBA
    pixels[3::4] = bytes([255]) * (width * height)  # GDI 不填 alpha，补齐为不透明

    stride = width * 4
    raw = bytearray((stride + 1) * height)
    for row in range(height):
        offset = row * (stride + 1)
        raw[offset] = 0  # 每行的过滤器类型：None
        raw[offset + 1 : offset + 1 + stride] = pixels[row * stride : (row + 1) * stride]

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)  # 8bit RGBA
    return (
        _PNG_SIGNATURE
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(bytes(raw), 6))
        + _png_chunk(b"IEND", b"")
    )


def exclude_from_capture(widget) -> bool:
    """让窗口出现在屏幕上、但不出现在任何截图里（Win10 2004+ 支持）。"""
    try:
        ok = _user32.SetWindowDisplayAffinity(ctypes.c_void_p(int(widget.winId())), WDA_EXCLUDEFROMCAPTURE)
        return bool(ok)
    except Exception:  # noqa: BLE001
        return False


def grab_raw(
    x: int, y: int, width: int, height: int, scale: int = 1
) -> tuple[int, int, bytes]:
    """抓取屏幕区域，返回 (宽, 高, BGRA 原始像素)。

    变化检测只关心像素，不需要编码 PNG，所以单独留了这个出口。
    scale > 1 时用 GDI StretchBlt 直接放大（HALFTONE），供小字号 OCR 使用。
    """
    width, height = int(width), int(height)
    scale = max(1, int(scale))
    if width <= 0 or height <= 0:
        raise ValueError(f"区域尺寸非法：{width}x{height}")
    out_width, out_height = width * scale, height * scale

    screen_dc = _user32.GetDC(None)
    if not screen_dc:
        raise RuntimeError(f"取不到屏幕 DC（Win32 错误 {ctypes.get_last_error()}）")

    memory_dc = None
    bitmap = None
    try:
        memory_dc = _gdi32.CreateCompatibleDC(screen_dc)
        bitmap = _gdi32.CreateCompatibleBitmap(screen_dc, out_width, out_height)
        if not memory_dc or not bitmap:
            raise RuntimeError(f"创建兼容位图失败（Win32 错误 {ctypes.get_last_error()}）")

        _gdi32.SelectObject(memory_dc, bitmap)
        if scale == 1:
            ok = _gdi32.BitBlt(
                memory_dc, 0, 0, width, height, screen_dc, int(x), int(y), SRCCOPY
            )
        else:
            _gdi32.SetStretchBltMode(memory_dc, HALFTONE)
            _gdi32.SetBrushOrgEx(memory_dc, 0, 0, None)
            ok = _gdi32.StretchBlt(
                memory_dc,
                0,
                0,
                out_width,
                out_height,
                screen_dc,
                int(x),
                int(y),
                width,
                height,
                SRCCOPY,
            )
        if not ok:
            raise RuntimeError(f"抓图失败（Win32 错误 {ctypes.get_last_error()}）")

        buffer = ctypes.create_string_buffer(out_width * out_height * 4)
        info = _BitmapInfo()
        info.bmiHeader.biSize = ctypes.sizeof(_BitmapInfoHeader)
        info.bmiHeader.biWidth = out_width
        info.bmiHeader.biHeight = -out_height  # 负数 = 自顶向下，省去翻行
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        info.bmiHeader.biCompression = 0  # BI_RGB
        if not _gdi32.GetDIBits(
            memory_dc,
            bitmap,
            0,
            out_height,
            buffer,
            ctypes.byref(info),
            DIB_RGB_COLORS,
        ):
            raise RuntimeError(f"GetDIBits 失败（Win32 错误 {ctypes.get_last_error()}）")

        pixels = bytes(buffer)
    finally:
        if bitmap:
            _gdi32.DeleteObject(ctypes.c_void_p(bitmap))
        if memory_dc:
            _gdi32.DeleteDC(ctypes.c_void_p(memory_dc))
        _user32.ReleaseDC(None, ctypes.c_void_p(screen_dc))

    return out_width, out_height, pixels


def grab_region(x: int, y: int, width: int, height: int, scale: int = 1) -> bytes:
    """抓取屏幕上一块矩形区域，返回 PNG 字节。"""
    pixel_width, pixel_height, pixels = grab_raw(x, y, width, height, scale)
    return encode_png(pixel_width, pixel_height, pixels)
