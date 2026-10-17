"""与 OCR 工作子进程通信的客户端（界面上唯一允许调 OCR 的入口）。"""

from __future__ import annotations

import base64
import json
import pathlib
import queue
import subprocess
import sys
import threading

APP_DIR = pathlib.Path(__file__).resolve().parent.parent
WORKER_SCRIPT = pathlib.Path(__file__).resolve().parent / "ocr_worker.py"


class OcrError(RuntimeError):
    """OCR 调用失败。"""


class OcrWorker:
    """常驻的 OCR 子进程，线程安全。"""

    def __init__(self, language: str | None = None, start_timeout: float = 90.0) -> None:
        self.language = language
        self.languages: list[str] = []
        self._lock = threading.Lock()
        self._process: subprocess.Popen | None = None
        self._responses: queue.Queue[dict] = queue.Queue()
        self._next_id = 0
        self._start_timeout = start_timeout
        self._start()

    def _start(self) -> None:
        self._responses = queue.Queue()
        if getattr(sys, "frozen", False):
            command = [sys.executable, "--ocr-worker"]
        else:
            command = [sys.executable, "-u", str(WORKER_SCRIPT)]
        self._process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=str(APP_DIR),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        threading.Thread(target=self._read_loop, args=(self._process,), daemon=True).start()
        handshake = self._request({"cmd": "ping"}, timeout=self._start_timeout)
        self.languages = list(handshake.get("languages", []))

    def _read_loop(self, process: subprocess.Popen) -> None:
        assert process.stdout is not None
        for raw in process.stdout:
            try:
                self._responses.put(json.loads(raw.decode("utf-8")))
            except Exception:  # noqa: BLE001
                continue
        self._responses.put({"__eof__": True})

    def _send(self, payload: dict) -> int:
        self._next_id += 1
        request_id = self._next_id
        payload["id"] = request_id
        assert self._process is not None and self._process.stdin is not None
        self._process.stdin.write(json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n")
        self._process.stdin.flush()
        return request_id

    def _request(self, payload: dict, timeout: float) -> dict:
        request_id = self._send(payload)
        while True:
            try:
                message = self._responses.get(timeout=timeout)
            except queue.Empty:
                raise OcrError(f"OCR 子进程 {timeout:.0f} 秒未响应") from None
            if message.get("__eof__"):
                raise OcrError("OCR 子进程已退出")
            if message.get("id") != request_id:
                continue
            if not message.get("ok"):
                raise OcrError(str(message.get("error", "未知错误")))
            return message

    def _alive(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def close(self) -> None:
        process = self._process
        if process is None:
            return
        try:
            if process.poll() is None:
                self._send({"cmd": "quit"})
                process.wait(timeout=5)
        except Exception:  # noqa: BLE001
            pass
        finally:
            if process.poll() is None:
                process.kill()
            self._process = None

    def recognize(self, png_bytes: bytes, lang: str | None = None, timeout: float = 30.0) -> str:
        """识别 PNG 中的文字；子进程异常退出时自动重启并重试一次。"""
        payload = {
            "cmd": "ocr",
            "lang": lang or self.language,
            "png_b64": base64.b64encode(png_bytes).decode("ascii"),
        }
        with self._lock:
            if not self._alive():
                self._start()
            try:
                return str(self._request(payload, timeout).get("text", ""))
            except OcrError:
                # 子进程崩溃或卡死：杀掉重开一次。否则一次异常会让之后每次
                # 翻译都报「OCR 子进程已退出」，只能重启整个程序。
                try:
                    self.close()
                except Exception:  # noqa: BLE001
                    pass
                self._start()
                return str(self._request(payload, timeout).get("text", ""))
