"""自动重译：轮询选区，等内容稳定变化后再触发一次翻译。

为什么要防抖：滚动/视频里内容一直在动，如果一有变化就翻译，请求会刷屏。
这里的策略是「变了先等一会儿，稳定了再翻」，并且限制两次请求的最小间隔。
"""

from __future__ import annotations

import time

from PySide6.QtCore import QObject, QTimer, Signal

from recttrans import capture

POLL_MS = 700  # 轮询间隔
SETTLE_SECONDS = 0.8  # 内容停止变化多久后才翻
MIN_GAP_SECONDS = 1.5  # 两次请求之间的最小间隔
RETRY_BACKOFF_SECONDS = 5.0  # 失败后等多久再试

SAMPLE_STRIDE = 4  # 采样步长：560x140 的选区约 4900 个采样点
LEVEL_SHIFT = 4  # 亮度量化到 16 级，抑制抗锯齿噪声


class AutoTranslator(QObject):
    """只负责「要不要翻」，真正的 OCR + 翻译仍由主流程做。"""

    triggered = Signal(bytes)  # 携带 PNG 字节

    def __init__(
        self,
        frame,
        poll_ms: int = POLL_MS,
        settle_seconds: float = SETTLE_SECONDS,
        min_gap_seconds: float = MIN_GAP_SECONDS,
    ) -> None:
        super().__init__()
        self._frame = frame
        self._settle = settle_seconds
        self._min_gap = min_gap_seconds

        self._timer = QTimer(self)
        self._timer.setInterval(poll_ms)
        self._timer.timeout.connect(self._tick)

        self._enabled = False
        self._busy = False
        self._last_sig: bytes | None = None
        self._translated_sig: bytes | None = None
        self._stable_at = 0.0
        self._next_allowed = 0.0

    # ---------- 外部控制 ----------

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        if enabled == self._enabled:
            return
        self._enabled = enabled
        if enabled:
            # 重新开启时把基线清空：下一次稳定内容会被翻译一次
            self._last_sig = None
            self._translated_sig = None
            self._next_allowed = 0.0
            self._timer.start()
        else:
            self._timer.stop()

    def set_busy(self, busy: bool) -> None:
        self._busy = busy

    def mark_failed(self) -> None:
        """翻译失败：允许稍后重试，但退避一段时间，避免错误循环刷请求。"""
        self._translated_sig = None
        self._next_allowed = time.monotonic() + RETRY_BACKOFF_SECONDS

    def note_manual_translation(self) -> None:
        """手动翻过一次后，把当前内容记为「已翻译」，避免紧接着又自动翻一遍。"""
        try:
            rect = self._frame.geometry()
            width, height, raw = capture.grab_raw(
                rect.x(), rect.y(), rect.width(), rect.height()
            )
            signature = self._signature(width, height, raw)
        except Exception:  # noqa: BLE001
            return
        self._last_sig = signature
        self._translated_sig = signature
        self._stable_at = time.monotonic() + self._settle

    # ---------- 内部 ----------

    @staticmethod
    def _signature(width: int, height: int, bgra: bytes) -> bytes:
        out = bytearray()
        for y in range(0, height, SAMPLE_STRIDE):
            row = y * width * 4
            for x in range(0, width, SAMPLE_STRIDE):
                index = row + x * 4
                blue = bgra[index]
                green = bgra[index + 1]
                red = bgra[index + 2]
                luminance = (red * 77 + green * 151 + blue * 28) >> 8
                out.append(luminance >> LEVEL_SHIFT)
        return bytes(out)

    def _tick(self) -> None:
        if not self._enabled or self._busy:
            return
        # 选框收进托盘后不再抓屏：否则会继续发请求，还会把浮窗重新弹出来。
        if not self._frame.isVisible():
            return

        try:
            rect = self._frame.geometry()
            width, height, raw = capture.grab_raw(
                rect.x(), rect.y(), rect.width(), rect.height()
            )
            signature = self._signature(width, height, raw)
        except Exception:  # noqa: BLE001
            return

        now = time.monotonic()
        if signature != self._last_sig:
            # 还在变化：重置稳定计时，等它停下来
            self._last_sig = signature
            self._stable_at = now + self._settle
            return

        if signature == self._translated_sig:
            return
        if now < self._stable_at:
            return
        if now < self._next_allowed:
            return

        self._next_allowed = now + self._min_gap
        self._translated_sig = signature
        try:
            png = capture.encode_png(width, height, raw)
        except Exception:  # noqa: BLE001
            self._translated_sig = None
            return
        self.triggered.emit(png)
