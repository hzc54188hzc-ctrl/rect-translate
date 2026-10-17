"""OCR 工作子进程：只加载 Windows OCR，不导入 Qt。

为什么要单独开进程：实测本机「PySide6 与 winrt 同进程」会以访问违例
（0xC0000005 / 0xC0000409）崩掉整个程序，5/6 次必崩；把 OCR 移到没有 Qt 的
进程后 6/6 稳定。因此界面进程只负责画界面与抓图，OCR 一律走这里。

协议：stdin 每行一个 JSON 请求，stdout 每行一个 JSON 响应。
  请求 {"id":1,"cmd":"ping"}
  请求 {"id":2,"cmd":"ocr","lang":null|"zh-Hans-CN","png_b64":"..."}
  请求 {"id":3,"cmd":"quit"}
  响应 {"id":1,"ok":true,"languages":[...]}
  响应 {"id":2,"ok":true,"text":"..."}
  响应 {"id":2,"ok":false,"error":"..."}
"""

from __future__ import annotations

import base64
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from recttrans.ocr import available_languages, recognize_png  # noqa: E402


def _write(payload: dict) -> None:
    sys.stdout.buffer.write(json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n")
    sys.stdout.buffer.flush()


def main() -> int:
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return 0
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
        except Exception as exc:  # noqa: BLE001
            _write({"id": None, "ok": False, "error": f"请求不是合法 JSON：{exc}"})
            continue

        request_id = request.get("id")
        command = request.get("cmd")

        if command == "quit":
            _write({"id": request_id, "ok": True})
            return 0

        if command == "ping":
            _write({"id": request_id, "ok": True, "languages": available_languages()})
            continue

        if command == "ocr":
            try:
                png = base64.b64decode(request["png_b64"])
                text = recognize_png(png, request.get("lang"))
                _write({"id": request_id, "ok": True, "text": text})
            except Exception as exc:  # noqa: BLE001
                _write({"id": request_id, "ok": False, "error": f"{type(exc).__name__}: {exc}"})
            continue

        _write({"id": request_id, "ok": False, "error": f"未知指令：{command!r}"})


if __name__ == "__main__":
    raise SystemExit(main())
