"""翻译历史：本地 JSON，最多 50 条，只记录手动/划词翻译。

自动重译不写入历史，否则滚动页面会瞬间刷满。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
HISTORY_PATH = APP_DIR / "history.json"
MAX_ENTRIES = 50


def load_history(path: Path | None = None) -> list[dict]:
    history_path = Path(path) if path else HISTORY_PATH
    try:
        data = json.loads(history_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []
    if not isinstance(data, list):
        return []
    result = []
    for item in data:
        if isinstance(item, dict) and str(item.get("translation", "")).strip():
            result.append(
                {
                    "time": str(item.get("time", "")),
                    "source": str(item.get("source", "")),
                    "translation": str(item.get("translation", "")),
                    "kind": str(item.get("kind", "ocr")),
                }
            )
        if len(result) >= MAX_ENTRIES:
            break
    return result


def save_history(entries: list[dict], path: Path | None = None) -> None:
    history_path = Path(path) if path else HISTORY_PATH
    temp = history_path.with_name(history_path.name + ".tmp")
    temp.write_text(
        json.dumps(entries[:MAX_ENTRIES], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temp, history_path)


def add_entry(
    entries: list[dict],
    source: str,
    translation: str,
    kind: str = "ocr",
    now: str | None = None,
) -> list[dict]:
    translation = (translation or "").strip()
    if not translation:
        return entries
    source = (source or "").strip()
    if (
        entries
        and entries[0].get("translation") == translation
        and entries[0].get("source") == source
    ):
        return entries
    entry = {
        "time": now or time.strftime("%Y-%m-%d %H:%M"),
        "source": source,
        "translation": translation,
        "kind": kind if kind in ("ocr", "selection") else "ocr",
    }
    return ([entry] + entries)[:MAX_ENTRIES]
