"""读取本地配置。config.local.json 内含 API key，禁止外发或提交。"""

from __future__ import annotations

import json
import os
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = APP_DIR / "config.local.json"

DEFAULTS: dict = {
    "ocr": {"engine": "windows", "language": "auto"},
    "translate": {
        # 首次运行走免费通道，免 key 即可跑；要更稳定的质量再切大模型
        "provider": "free",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "api_key": "",
    },
    "source_language": "auto",
    "target_language": "zh-CN",
    "quick_hotkey": "Ctrl+Shift+Q",
    "popup": {"x": 760, "y": 600, "placed": False},
    "hint_shown": False,
    "frame": {"color": "#FFA800", "thickness": 6, "length": 48},
}


def _merge(base: dict, override: dict) -> dict:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(path: Path | None = None) -> dict:
    config_path = Path(path) if path else CONFIG_PATH
    if not config_path.exists():
        raise FileNotFoundError(f"找不到配置文件：{config_path}")

    config = _merge(DEFAULTS, json.loads(config_path.read_text(encoding="utf-8")))
    provider = str(config["translate"].get("provider", "deepseek"))
    key = str(config["translate"].get("api_key", ""))
    # 免费通道不需要 key；只有大模型通道才校验
    if provider == "deepseek" and not key.startswith("sk-"):
        raise ValueError("config.local.json 里的 translate.api_key 不是有效格式")
    return config


def ensure_config(path: Path | None = None) -> bool:
    """配置文件不存在时生成默认配置，返回是否新建。"""
    config_path = Path(path) if path else CONFIG_PATH
    if config_path.exists():
        return False
    save_config(json.loads(json.dumps(DEFAULTS)), config_path)
    return True


def save_config(config: dict, path: Path | None = None) -> None:
    config_path = Path(path) if path else CONFIG_PATH
    # 先写临时文件再原子替换：写到一半被强杀也不会留下坏 JSON。
    temp_path = config_path.with_name(config_path.name + ".tmp")
    temp_path.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temp_path, config_path)
