"""滚动窗口字幕组装。

滚动窗口会让同一段语音被识别多次。这里只提交「窗口尾部留白之外」的新词：

- 窗口最后 ``tail_margin`` 秒不提交，等下一个窗口重新识别，避免把半个词写进字幕。
- 已经提交过的词按绝对时间过滤，同一句话不会重复出现。
- 按停顿、标点或词数切句，供字幕窗显示「当前句 + 上一句」。
"""

from __future__ import annotations

from typing import Iterable

END_PUNCTUATION = (".", "!", "?", "…")
# 对话里的换气、背景音停顿很常见；0.9 秒会把一句话切成 "Are you" / "gonna stay in"
# 这种半句，翻译出来又碎又机械。只有明显停顿才另起一句。
WORD_GAP_SECONDS = 2.5
MAX_WORDS_PER_LINE = 16


def is_partial(text: str) -> bool:
    """模型用省略号表示句子还没说完，这类半句不进历史。"""
    return (text or "").rstrip().endswith(("…", "...", "……"))


class CaptionAssembler:
    def __init__(
        self,
        tail_margin: float = 0.3,
        gap_seconds: float = WORD_GAP_SECONDS,
        max_words: int = MAX_WORDS_PER_LINE,
    ) -> None:
        self.tail_margin = tail_margin
        self.gap_seconds = gap_seconds
        self.max_words = max_words
        self.committed_end = 0.0
        self.current_id = 0
        self.previous_id = -1
        self._current: list[str] = []
        self._previous = ""
        self._last_end = 0.0
        self._recent: list[tuple[float, float, str]] = []
        self._history: list[str] = []

    def reset(self) -> None:
        self.committed_end = 0.0
        self.current_id = 0
        self.previous_id = -1
        self._current = []
        self._previous = ""
        self._last_end = 0.0
        self._recent = []
        self._history = []

    def add_window(
        self,
        words: Iterable[dict],
        window_start: float,
        window_seconds: float,
    ) -> list[str]:
        """加入一个窗口的识别结果，返回本次新提交的词。"""
        confirm_before = window_start + window_seconds - self.tail_margin
        accepted: list[tuple[float, float, str]] = []
        for word in words:
            text = str(word.get("text", "")).strip()
            if not text:
                continue
            if text.lower() in ("s", "t", "d", "m"):
                continue  # Whisper 偶尔把词头切成 "s" 这类单字母碎片
            start = window_start + float(word.get("start", 0.0))
            end = window_start + float(word.get("end", 0.0))
            if end > confirm_before + 0.01:
                continue  # 窗口尾部尚未确认
            if end <= self.committed_end + 0.02:
                continue  # 上一个窗口已经提交过
            if start < self.committed_end - 0.02:
                continue  # 与已提交区重叠的残词
            if any(
                text == old_text and abs(start - old_start) < 1.5
                for old_start, _old_end, old_text in self._recent
            ):
                continue  # 同一词被下一个窗口重新识别，时间戳略有漂移
            accepted.append((start, end, text))

        accepted.sort(key=lambda item: item[0])
        committed: list[str] = []
        for start, end, text in accepted:
            if self._current and start - self._last_end >= self.gap_seconds:
                self._flush()
            self._current.append(text)
            committed.append(text)
            self._last_end = end
            self.committed_end = max(self.committed_end, end)
            self._recent.append((start, end, text))
            del self._recent[:-6]
            if len(self._current) >= self.max_words or text.endswith(END_PUNCTUATION):
                self._flush()
        return committed

    def snapshot(self) -> tuple[str, str]:
        return " ".join(self._current).strip(), self._previous

    def context(self, limit: int = 2) -> str:
        """最近几句已完成的英文，供翻译理解对话关系。"""
        return " ".join(self._history[-limit:]).strip()

    def context_before(self, limit: int = 2) -> str:
        """上一句之前的上下文，补译上一句时不会把它自己带进去。"""
        return " ".join(self._history[-(limit + 1) : -1]).strip()

    def break_current(self) -> None:
        """暂停或长时间静音：把当前半句收尾，避免和恢复后的语音拼成一句。"""
        if self._current:
            self._flush()

    def _flush(self) -> None:
        line = " ".join(self._current).strip()
        if not line:
            return
        self.previous_id = self.current_id
        self.current_id += 1
        self._previous = line
        self._current = []
        self._history.append(line)
        del self._history[:-4]
