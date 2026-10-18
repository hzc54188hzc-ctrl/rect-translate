"""系统声音采集：WASAPI 环回 + 能量分段。

只采集扬声器正在播放的声音，不碰麦克风；音频只在内存里处理，不落盘。
"""

from __future__ import annotations

import threading

import numpy as np

try:  # 延迟导入：没装 soundcard 时其它功能仍可正常使用
    import soundcard as _sc
except Exception:  # noqa: BLE001
    _sc = None

SAMPLE_RATE = 16000
BLOCK_SECONDS = 0.1
SILENCE_RMS = 0.0025


class Segmenter:
    """按音量切段：说话开始 → 连续静音 0.7s 或满 6s 切一刀。"""

    def __init__(
        self,
        threshold: float = 0.012,
        silence_seconds: float = 0.4,
        max_seconds: float = 2.9,
        min_seconds: float = 0.6,
        overlap_seconds: float = 0.4,
        block_seconds: float = BLOCK_SECONDS,
    ) -> None:
        self.threshold = threshold
        self.silence_blocks = max(1, round(silence_seconds / block_seconds))
        self.max_blocks = max(1, round(max_seconds / block_seconds))
        self.min_blocks = max(1, round(min_seconds / block_seconds))
        self.overlap_blocks = max(1, round(overlap_seconds / block_seconds))
        self._buffer: list[np.ndarray] = []
        self._preroll: list[np.ndarray] = []
        self._overlap: list[np.ndarray] | None = None
        self._speaking = False
        self._quiet = 0
        self._speech_blocks = 0

    def feed(self, block: np.ndarray) -> np.ndarray | None:
        """喂入一块 16k 单声道 float32，返回切好的整段或 None。"""
        if block.size == 0:
            return None
        rms = float(np.sqrt(np.mean(np.square(block, dtype=np.float32))))
        if rms > self.threshold:
            if not self._speaking:
                # 上一段结尾的重叠 + 说话前的静音预卷，避免切掉边界词
                self._buffer = (
                    list(self._overlap) if self._overlap is not None else []
                ) + list(self._preroll)
                self._overlap = None
                self._preroll = []
            self._speaking = True
            self._quiet = 0
            self._speech_blocks += 1
        elif self._speaking:
            self._quiet += 1
        else:
            self._preroll.append(block)
            if len(self._preroll) > 3:
                self._preroll.pop(0)

        if not self._speaking:
            return None

        self._buffer.append(block)
        finished = self._quiet >= self.silence_blocks or len(self._buffer) >= self.max_blocks
        if not finished:
            return None

        if len(self._buffer) > self.overlap_blocks:
            self._overlap = [
                np.array(block, copy=True)
                for block in self._buffer[-self.overlap_blocks:]
            ]
            audio = np.concatenate(
                self._buffer[: -self.overlap_blocks]
            ).astype(np.float32)
        else:
            self._overlap = None
            audio = np.concatenate(self._buffer).astype(np.float32)
        speech_blocks = self._speech_blocks
        self._buffer = []
        self._speaking = False
        self._quiet = 0
        self._speech_blocks = 0
        if speech_blocks < self.min_blocks:
            return None
        return audio


class LoopbackCapture:
    """后台线程持续录音，切好段后回调 on_segment(audio)。"""

    def __init__(self, on_segment, on_error=None) -> None:
        self._on_segment = on_segment
        self._on_error = on_error
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._segmenter = Segmenter()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        if _sc is None:
            raise RuntimeError("缺少 soundcard 依赖，无法采集系统声音")
        self._stop.clear()
        self._segmenter = Segmenter()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        self._thread = None

    def _run(self) -> None:
        try:
            speaker = _sc.default_speaker()
            mic = _sc.get_microphone(id=speaker.id, include_loopback=True)
            rate = 48000
            try:
                recorder = mic.recorder(samplerate=rate, channels=2)
                with recorder as rec:
                    self._loop(rec, rate)
            except Exception:
                rate = 44100
                with mic.recorder(samplerate=rate, channels=2) as rec:
                    self._loop(rec, rate)
        except Exception as exc:  # noqa: BLE001
            if self._on_error is not None:
                self._on_error(f"{type(exc).__name__}: {exc}")

    def _loop(self, recorder, rate: int) -> None:
        block_frames = max(1, int(rate * BLOCK_SECONDS))
        while not self._stop.is_set():
            data = recorder.record(numframes=block_frames)
            mono = data.mean(axis=1)
            if rate != SAMPLE_RATE:
                count = max(1, int(len(mono) * SAMPLE_RATE / rate))
                mono = np.interp(
                    np.arange(count) * rate / SAMPLE_RATE,
                    np.arange(len(mono)),
                    mono,
                )
            segment = self._segmenter.feed(mono.astype(np.float32))
            if segment is not None:
                self._on_segment(segment)


class RollingBuffer:
    """滚动窗口：每 step 秒吐出最近 window 秒音频（含起点绝对时间）。"""

    def __init__(
        self,
        window_seconds: float = 3.0,
        step_seconds: float = 0.8,
    ) -> None:
        self.window_samples = int(window_seconds * SAMPLE_RATE)
        self.step_samples = int(step_seconds * SAMPLE_RATE)
        self._buffer = np.zeros(0, dtype=np.float32)
        self._total = 0
        self._pending = 0
        self._silent_samples = 0

    def feed(self, block: np.ndarray) -> tuple[np.ndarray, float] | None:
        if block.size == 0:
            return None
        self._total += len(block)
        rms = float(np.sqrt(np.mean(np.square(block, dtype=np.float32))))
        if rms < SILENCE_RMS:
            self._silent_samples += len(block)
            if self._silent_samples >= int(1.5 * SAMPLE_RATE):
                # 暂停/长时间静音后清空窗口，避免恢复播放时把旧音频拼进来。
                self._buffer = np.zeros(0, dtype=np.float32)
                self._pending = 0
                return None
        else:
            self._silent_samples = 0
        self._buffer = np.concatenate([self._buffer, block.astype(np.float32)])
        if len(self._buffer) > self.window_samples:
            self._buffer = self._buffer[-self.window_samples :]
        self._pending += len(block)
        if (
            self._total < self.window_samples
            or self._pending < self.step_samples
            or len(self._buffer) < int(1.0 * SAMPLE_RATE)
        ):
            return None
        # 以本次输出为基准重新计时。首个窗口会一次性积累满 window 秒，
        # 若只减去 step，下一块会立刻再次触发，窗口就退化成逐块输出。
        self._pending = 0
        start_sample = self._total - len(self._buffer)
        return self._buffer.copy(), start_sample / SAMPLE_RATE


class RollingCapture:
    """后台采集系统声音，按滚动窗口回调 on_window(audio, start_seconds)。"""

    def __init__(self, on_window, on_error=None) -> None:
        self._on_window = on_window
        self._on_error = on_error
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._buffer = RollingBuffer()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        if _sc is None:
            raise RuntimeError("缺少 soundcard 依赖，无法采集系统声音")
        self._stop.clear()
        self._buffer = RollingBuffer()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        self._thread = None

    def _run(self) -> None:
        try:
            speaker = _sc.default_speaker()
            mic = _sc.get_microphone(id=speaker.id, include_loopback=True)
            rate = 48000
            try:
                with mic.recorder(samplerate=rate, channels=2) as rec:
                    self._loop(rec, rate)
            except Exception:
                rate = 44100
                with mic.recorder(samplerate=rate, channels=2) as rec:
                    self._loop(rec, rate)
        except Exception as exc:  # noqa: BLE001
            if self._on_error is not None:
                self._on_error(f"{type(exc).__name__}: {exc}")

    def _loop(self, recorder, rate: int) -> None:
        block_frames = max(1, int(rate * BLOCK_SECONDS))
        while not self._stop.is_set():
            data = recorder.record(numframes=block_frames)
            mono = data.mean(axis=1)
            if rate != SAMPLE_RATE:
                count = max(1, int(len(mono) * SAMPLE_RATE / rate))
                mono = np.interp(
                    np.arange(count) * rate / SAMPLE_RATE,
                    np.arange(len(mono)),
                    mono,
                )
            result = self._buffer.feed(mono.astype(np.float32))
            if result is not None:
                window, start_seconds = result
                self._on_window(window, start_seconds)
