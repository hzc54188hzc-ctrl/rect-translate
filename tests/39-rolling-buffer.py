"""滚动音频窗口自检：满 3 秒才吐出、每 1.5 秒一次、起点与内容正确。

用法：.venv\\Scripts\\python.exe tests\\39-rolling-buffer.py
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import numpy as np

from recttrans.audio import RollingBuffer


def block(value: float, seconds: float = 0.1) -> np.ndarray:
    return np.full(int(16000 * seconds), value, dtype=np.float32)


def main() -> int:
    failures = 0

    def check(label: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        failures += 0 if ok else 1
        print(f"[{'OK' if ok else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")

    buffer = RollingBuffer(window_seconds=3.0, step_seconds=1.5)
    results = []
    for index in range(60):
        piece = buffer.feed(block(float(index)))
        if piece is not None:
            results.append((index + 1, piece))

    check("2.9 秒内不输出", results[0][0] == 30, f"首个窗口在第 {results[0][0]} 块")
    window, start = results[0][1]
    check("首个窗口 3 秒", len(window) == 48000, str(len(window)))
    check("首个窗口起点 0", abs(start) < 1e-6, f"{start:.3f}s")
    check(
        "首个窗口内容是最新 3 秒",
        float(window[0]) == 0.0 and float(window[-1]) == 29.0,
        f"{float(window[0]):.0f}..{float(window[-1]):.0f}",
    )

    check("窗口间隔 1.5 秒", results[1][0] == 45, f"第二个窗口在第 {results[1][0]} 块")
    window, start = results[1][1]
    check("第二个窗口起点 1.5 秒", abs(start - 1.5) < 1e-6, f"{start:.3f}s")
    check(
        "第二个窗口内容是最新 3 秒",
        float(window[0]) == 15.0 and float(window[-1]) == 44.0,
        f"{float(window[0]):.0f}..{float(window[-1]):.0f}",
    )
    check("共输出 3 个窗口", len(results) == 3, str(len(results)))

    short = RollingBuffer(window_seconds=1.0, step_seconds=1.0)
    check("窗口未满时不输出", short.feed(block(1.0, 0.5)) is None)

    default = RollingBuffer()
    check(
        "默认步进 0.8 秒",
        default.step_samples == int(0.8 * 16000),
        str(default.step_samples),
    )

    paused = RollingBuffer(window_seconds=3.0, step_seconds=0.8)
    for _ in range(30):
        paused.feed(block(1.0))
    for _ in range(16):
        paused.feed(block(0.0))
    check("长静音清空旧窗口", len(paused._buffer) == 0, str(len(paused._buffer)))
    resumed = None
    for _ in range(12):
        piece = paused.feed(block(1.0))
        if piece is not None:
            resumed = piece
            break
    check(
        "恢复后只输出新音频",
        resumed is not None and len(resumed[0]) <= 16000,
        f"{0 if resumed is None else len(resumed[0])}",
    )

    print(f"结果：{'全部通过' if failures == 0 else f'{failures} 项失败'}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
