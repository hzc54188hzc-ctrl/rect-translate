"""阶段 3 自检：免费通道是否可用、设置保存是否写盘、划词热键校验、跑完恢复原配置。

用法：.venv\\Scripts\\python.exe tests\\14-settings-check.py
"""

from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication

from recttrans.config import ensure_config, load_config, save_config
from recttrans.settings_window import SettingsWindow
from recttrans.translator import translate

_APP = None


def main() -> int:
    global _APP
    ensure_config()
    original = load_config()
    backup = json.loads(json.dumps(original))
    try:
        config = json.loads(json.dumps(original))
        config["translate"]["provider"] = "free"
        text = translate("Hello world, this is a test.", config)
        print(f"免费通道译文: {text!r}")
        free_ok = bool(text.strip()) and any("\u4e00" <= ch <= "\u9fff" for ch in text)

        _APP = QApplication(sys.argv)
        window = SettingsWindow(config)
        index = window._target.findData("en")
        window._target.setCurrentIndex(index)
        window._hotkey.setText("ctrl+alt+g")
        window._save()

        saved = load_config()
        saved_ok = (
            saved["translate"]["provider"] == "free"
            and saved["target_language"] == "en"
            and saved["quick_hotkey"] == "Ctrl+Alt+G"
        )
        print(
            f"保存回读: provider={saved['translate']['provider']} "
            f"target={saved['target_language']} "
            f"hotkey={saved['quick_hotkey']} → {'OK' if saved_ok else 'FAIL'}"
        )

        bad = SettingsWindow(saved)
        bad._hotkey.setText("Q")
        bad._save()
        # isVisible() 在未 show 的对话框上恒为 False，改用错误文本判断
        reject_ok = bad.saved_config is None and bool(bad._hotkey_error.text())
        print(f"非法热键被拒绝: {'OK' if reject_ok else 'FAIL'}")

        # 大模型通道没有有效 key 时不允许保存（否则下次启动会静默失败）
        bad_key = SettingsWindow(saved)
        bad_key._set_provider("deepseek")
        bad_key._key.setText("")
        bad_key._save()
        key_reject_ok = (
            bad_key.saved_config is None and bool(bad_key._key_error.text())
        )
        print(f"空 API key 被拒绝: {'OK' if key_reject_ok else 'FAIL'}")

        return 0 if (free_ok and saved_ok and reject_ok and key_reject_ok) else 1
    finally:
        save_config(backup)
        print(
            f"已恢复原配置: provider={backup['translate']['provider']} "
            f"target={backup['target_language']}"
        )


if __name__ == "__main__":
    raise SystemExit(main())
