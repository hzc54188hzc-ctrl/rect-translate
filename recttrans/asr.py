"""本地英文语音识别：faster-whisper tiny.en（int8，CPU，优先速度）。"""

from __future__ import annotations

import pathlib
import os

APP_DIR = pathlib.Path(__file__).resolve().parent.parent
MODEL_DIR = APP_DIR / "models" / "faster-whisper-tiny.en"


def model_available() -> bool:
    return (MODEL_DIR / "model.bin").exists() and (MODEL_DIR / "config.json").exists()


class WhisperEngine:
    def __init__(self) -> None:
        self._model = None

    def load(self) -> None:
        if self._model is not None:
            return
        if not model_available():
            raise RuntimeError(
                "没有找到语音模型，请先运行 tools\\download-model.ps1 下载 tiny.en 模型"
            )
        from faster_whisper import WhisperModel

        threads = min(8, max(1, os.cpu_count() or 4))
        self._model = WhisperModel(
            str(MODEL_DIR),
            device="cpu",
            compute_type="int8",
            cpu_threads=threads,
            num_workers=1,
        )

    def transcribe(self, audio) -> str:
        self.load()
        segments, _info = self._model.transcribe(
            audio,
            language="en",
            beam_size=1,
            vad_filter=False,
            condition_on_previous_text=False,
            without_timestamps=True,
        )
        return " ".join(segment.text.strip() for segment in segments).strip()

    def transcribe_words(self, audio) -> list[dict]:
        """返回带时间戳的词，时间相对于传入音频的起点。"""
        self.load()
        segments, _info = self._model.transcribe(
            audio,
            language="en",
            beam_size=1,
            vad_filter=False,
            condition_on_previous_text=False,
            word_timestamps=True,
        )
        words: list[dict] = []
        for segment in segments:
            for word in segment.words or []:
                text = (word.word or "").strip()
                if not text:
                    continue
                words.append(
                    {
                        "start": float(word.start),
                        "end": float(word.end),
                        "text": text,
                    }
                )
        return words

    def close(self) -> None:
        self._model = None
