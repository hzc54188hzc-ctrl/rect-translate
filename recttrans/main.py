"""阶段 1 主流程：常驻矩形 + 抓图 + 内置 OCR + DeepSeek 翻译 + 结果浮窗。

用法：
  .venv\\Scripts\\python.exe 01-run.py                            正常启动
  .venv\\Scripts\\python.exe 01-run.py --selftest --rect x,y,w,h  跑一次抓图→OCR→翻译并打印结果
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import time
import ctypes
import difflib
import subprocess

import numpy as np

from PySide6.QtCore import QObject, QPoint, QRect, QRunnable, QThreadPool, QTimer, Signal
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtWidgets import QApplication, QMessageBox, QProgressDialog

from recttrans import capture
from recttrans.asr import WhisperEngine, model_available
from recttrans.audio import SILENCE_RMS, RollingCapture
from recttrans.autotrans import AutoTranslator
from recttrans.caption import CaptionAssembler, is_partial
from recttrans.config import CONFIG_PATH, ensure_config, load_config, save_config
from recttrans.controls import ModeBar
from recttrans.frame import RegionFrame
from recttrans.history import add_entry, load_history, save_history
from recttrans.history_window import HistoryWindow
from recttrans.hotkey import HotkeyManager, normalize_sequence, parse_sequence
from recttrans.ocr_client import OcrWorker
from recttrans.popup import ResultPopup
from recttrans.quick import grab_selected_text
from recttrans.settings_window import SettingsWindow
from recttrans.tray import Tray
from recttrans.translator import translate, translate_caption, translate_rich
from recttrans.version import BUILD

# 旧版默认位置，仅用于识别「用户没动过」的旧配置并迁移到右上角
DEFAULT_GEOMETRY = QRect(770, 465, 420, 110)


def _default_geometry() -> QRect:
    """默认选框：主屏右上角，落在功能浮窗下方。"""
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return DEFAULT_GEOMETRY
    area = screen.availableGeometry()
    width, height = 420, 110
    return QRect(area.right() - width - 40, area.top() + 96, width, height)

# 配置里的组合被占用时按顺序尝试；托盘与设置窗口显示的都是真正生效的那个。
QUICK_HOTKEY_FALLBACKS = ("Ctrl+Alt+G", "Ctrl+Shift+Q", "Ctrl+Alt+F9")

def _app_dir() -> pathlib.Path:
    """打包后日志与配置放在 exe 旁边，而不是 _internal。"""
    if getattr(sys, "frozen", False):
        return pathlib.Path(sys.executable).resolve().parent
    return pathlib.Path(__file__).resolve().parent.parent


APP_DIR = _app_dir()
ERROR_LOG = APP_DIR / "error.log"
DEBUG_LOG = APP_DIR / "debug.log"
_trace_override = os.environ.get("RECTRANS_TRACE", "").strip()
CAPTION_TRACE = (
    pathlib.Path(_trace_override) if _trace_override else APP_DIR / "caption-trace.log"
)
_DEBUG = bool(os.environ.get("RECTTRANS_DEBUG"))


def _debug(message: str) -> None:
    if not _DEBUG:
        return
    try:
        with DEBUG_LOG.open("a", encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%H:%M:%S')} {message}\n")
    except Exception:  # noqa: BLE001
        pass


def _trace_caption(event: str, **fields) -> None:
    """把同传翻译轨迹写成 JSON 行，供事后判断卡在哪一步。"""
    try:
        line = json.dumps(
            {"time": time.strftime("%H:%M:%S"), "event": event, **fields},
            ensure_ascii=False,
        )
        with CAPTION_TRACE.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        if CAPTION_TRACE.stat().st_size > 1_500_000:
            data = CAPTION_TRACE.read_text(encoding="utf-8", errors="replace")
            CAPTION_TRACE.write_text(data[-500_000:], encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _log_line(message: str) -> None:
    """不受 RECTTRANS_DEBUG 控制的关键事件日志（热键、版本、重复启动）。"""
    try:
        with DEBUG_LOG.open("a", encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
    except Exception:  # noqa: BLE001
        pass


def _log_start() -> None:
    """每次启动都记一行（不受 RECTTRANS_DEBUG 控制）：排障时确认实际运行的版本。"""
    try:
        with DEBUG_LOG.open("a", encoding="utf-8") as handle:
            handle.write(
                f"{time.strftime('%Y-%m-%d %H:%M:%S')} start pid={os.getpid()} build={BUILD}\n"
            )
    except Exception:  # noqa: BLE001
        pass


def _ensure_std_streams() -> None:
    """pythonw 下 sys.stdout / sys.stderr 是 None。

    Qt 解码图片时会往 stderr 写警告（实测见过 `libpng warning`），写向 None 会让
    PySide6 在 C++ 回调里抛异常、直接把进程打掉。这里把两个流接到日志文件。
    """
    log_path = APP_DIR / "runtime.log"
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            try:
                setattr(sys, name, log_path.open("a", encoding="utf-8", buffering=1))
            except Exception:  # noqa: BLE001
                pass


_SINGLE_INSTANCE_MUTEX = None
_ACTIVATE_EVENT_NAME = "Local\\RectTranslateActivate"
_ACTIVATE_EVENT = None


def _acquire_single_instance() -> bool:
    """命名互斥体：已有实例在跑就返回 False，避免两个实例抢同一份配置、日志与热键。"""
    global _SINGLE_INSTANCE_MUTEX
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        _SINGLE_INSTANCE_MUTEX = kernel32.CreateMutexW(
            None, False, "Local\\RectTranslateSingleInstance"
        )
        return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS
    except Exception:  # noqa: BLE001
        return True


def _notify_already_running() -> None:
    """已有实例时给出可见提示：静默退出会让人以为程序坏了。"""
    try:
        ctypes.windll.user32.MessageBoxW(
            None,
            "矩形翻译已经在运行。\n\n"
            "如果看不到选框，请点任务栏右下角的托盘图标（可能收在「^」里）恢复；"
            "要完全关闭请用托盘菜单里的「退出」。",
            "矩形翻译",
            0x40,  # MB_ICONINFORMATION
        )
    except Exception:  # noqa: BLE001
        pass


def _create_activate_event(name: str = _ACTIVATE_EVENT_NAME):
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateEventW.restype = ctypes.c_void_p
        handle = kernel32.CreateEventW(None, False, False, name)
        return handle or None
    except Exception:  # noqa: BLE001
        return None


def _signal_existing_instance(name: str = _ACTIVATE_EVENT_NAME) -> bool:
    """让已在运行的实例把选框显示出来。"""
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenEventW.restype = ctypes.c_void_p
        handle = kernel32.OpenEventW(0x0002, False, name)  # EVENT_MODIFY_STATE
        if not handle:
            return False
        kernel32.SetEvent(ctypes.c_void_p(handle))
        kernel32.CloseHandle(ctypes.c_void_p(handle))
        return True
    except Exception:  # noqa: BLE001
        return False


def _consume_activate_event(handle) -> bool:
    if not handle:
        return False
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        kernel32.WaitForSingleObject.restype = ctypes.c_uint
        return kernel32.WaitForSingleObject(ctypes.c_void_p(handle), 0) == 0
    except Exception:  # noqa: BLE001
        return False


def _notify_config_error(exc: Exception) -> None:
    """配置坏了要让人看得见：pythonw 下静默退出等于「打不开」。"""
    message = (
        f"配置读取失败：{exc}\n\n"
        f"请检查：{APP_DIR / 'config.local.json'}\n\n"
        "常见原因：\n"
        "· 大模型通道的 API key 为空或不是 sk- 开头（可先切到免费接口）\n"
        "· 文件被改坏，不是合法的 JSON\n\n"
        "改好后重新启动即可。"
    )
    try:
        ctypes.windll.user32.MessageBoxW(None, message, "矩形翻译", 0x10)
    except Exception:  # noqa: BLE001
        pass


# QApplication 必须由模块级变量持有；被 GC 回收会让进程以访问违例崩溃。
_APP: QApplication | None = None


def _install_error_log() -> None:
    """把未捕获异常写进 error.log。

    用 pythonw 启动时没有控制台，异常会被静默丢掉——实测因此把一个真 bug 拖了几轮。
    """
    import traceback

    def hook(exc_type, exc, tb) -> None:
        try:
            with ERROR_LOG.open("a", encoding="utf-8") as handle:
                handle.write("".join(traceback.format_exception(exc_type, exc, tb)))
        except Exception:  # noqa: BLE001
            pass
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = hook


class _Signals(QObject):
    done = Signal(object)


class _AudioBridge(QObject):
    segment = Signal(object)
    failed = Signal(str)


class _Job(QRunnable):
    def __init__(self, work, signals: _Signals) -> None:
        super().__init__()
        self._work = work
        self._signals = signals

    def run(self) -> None:
        try:
            result = self._work()
        except Exception as exc:  # noqa: BLE001
            result = {"error": f"{type(exc).__name__}: {exc}"}
        try:
            self._signals.done.emit(result)
        except RuntimeError:
            # 程序退出时后台任务可能晚于信号对象销毁，结果直接丢弃即可。
            pass


def _parse_rect(argv: list[str], config: dict | None = None) -> QRect:
    if "--rect" in argv:
        raw = argv[argv.index("--rect") + 1]
        x, y, width, height = (int(part) for part in raw.split(","))
        return QRect(x, y, width, height)
    saved = ((config or {}).get("frame") or {}).get("geometry") if config else None
    if isinstance(saved, dict):
        try:
            rect = QRect(
                int(saved["x"]), int(saved["y"]), int(saved["w"]), int(saved["h"])
            )
        except Exception:  # noqa: BLE001
            rect = QRect()
        if rect.width() >= 160 and rect.height() >= 70:
            if rect == DEFAULT_GEOMETRY:
                return _default_geometry()
            return _fit_to_screen(rect)
    return _default_geometry()


def _fit_to_screen(rect: QRect) -> QRect:
    """保存的选框如果落在已断开的显示器上，就居中放到主屏。"""
    app = QGuiApplication.instance()
    screens = app.screens() if app is not None else []
    if not screens:
        return rect
    for screen in screens:
        if screen.availableGeometry().intersects(rect):
            return rect
    area = screens[0].availableGeometry()
    width = max(160, min(rect.width(), area.width()))
    height = max(70, min(rect.height(), area.height()))
    x = area.left() + (area.width() - width) // 2
    y = area.top() + (area.height() - height) // 2
    return QRect(x, y, width, height)


def save_frame_geometry(
    config: dict, rect: QRect, path: pathlib.Path | None = None
) -> None:
    """只更新 frame.geometry，保留磁盘上的其它字段。"""
    config_path = pathlib.Path(path) if path else CONFIG_PATH
    try:
        fresh = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        fresh = json.loads(json.dumps(config))
    section = fresh.setdefault("frame", {})
    geometry = {
        "x": rect.x(),
        "y": rect.y(),
        "w": rect.width(),
        "h": rect.height(),
    }
    section["geometry"] = geometry
    save_config(fresh, config_path)
    config.setdefault("frame", {})["geometry"] = dict(geometry)


def _frame_style(config: dict) -> tuple[str, int, int]:
    section = config.get("frame") or {}
    return (
        str(section.get("color", "#FFA800")),
        int(section.get("thickness", 6)),
        int(section.get("length", 48)),
    )


def run_selftest(argv: list[str]) -> int:
    global _APP
    rect = _parse_rect(argv)
    ensure_config()
    config = load_config()
    _APP = QApplication(sys.argv)

    png = capture.grab_region(rect.x(), rect.y(), rect.width(), rect.height())
    if "--save-png" in argv:
        pathlib.Path(argv[argv.index("--save-png") + 1]).write_bytes(png)
    worker = OcrWorker()
    try:
        text = worker.recognize(png)
        translation = translate(text, config) if text.strip() else ""
        languages = list(worker.languages)
    finally:
        worker.close()

    print(json.dumps(
        {
            "rect": [rect.x(), rect.y(), rect.width(), rect.height()],
            "ocr_languages": languages,
            "text": text,
            "translation": translation,
        },
        ensure_ascii=False,
        indent=2,
    ))
    return 0 if text.strip() and translation else 1


def run_app(argv: list[str]) -> int:
    global _APP
    _install_error_log()
    _log_start()
    config_created = ensure_config()
    try:
        config = load_config()
    except Exception as exc:  # noqa: BLE001
        _log_line(f"config load failed: {type(exc).__name__}: {exc}")
        _notify_config_error(exc)
        return 2
    _APP = QApplication(sys.argv)
    _APP.setQuitOnLastWindowClosed(False)

    frame = RegionFrame(
        _parse_rect(argv, config), capture_excluded="--allow-capture" not in argv
    )
    frame.apply_style(*_frame_style(config))
    frame.set_ocr_language(str((config.get("ocr") or {}).get("language", "auto")))
    popup = ResultPopup()
    bridge = _AudioBridge()
    asr = WhisperEngine()
    asr_signals = _Signals()
    caption_signals = _Signals()
    download_signals = _Signals()
    popup_cfg = config.get("popup") or {}
    # `pinned` 是 2026-10-17f 的旧字段，迁移为「已记住位置」。
    saved_x = int(popup_cfg.get("x", 760))
    saved_y = int(popup_cfg.get("y", 600))
    if (popup_cfg.get("placed") or popup_cfg.get("pinned")) and (saved_x or saved_y):
        # (0,0) 是旧版本留下的贴边值，不当作「用户放好的位置」。
        popup.set_saved_position(QPoint(saved_x, saved_y))
    bar = ModeBar()
    tray = Tray()
    hotkeys = HotkeyManager()
    auto = AutoTranslator(frame)
    signals = _Signals()
    pool = QThreadPool()
    history = load_history()
    geometry_timer = QTimer()
    geometry_timer.setSingleShot(True)
    geometry_timer.setInterval(500)
    geometry_timer.timeout.connect(
        lambda: save_frame_geometry(config, frame.geometry())
    )
    caption_hold = QTimer()
    caption_hold.setSingleShot(True)
    caption_hold.setInterval(1500)
    state = {
        "busy": False,
        "worker": None,
        "manual": True,
        "hotkey_id": 0,
        "hotkey_label": "",
        "tray_hinted": False,
        "hidden": False,
        "ocr_lang": str((config.get("ocr") or {}).get("language", "auto")),
        "kind": "ocr",
        "asr_busy": False,
        "asr_queue": [],
        "asr_started": 0.0,
        "asr_audio_seconds": 0.0,
        "subtitle_on": False,
        "caption_pause_until": 0.0,
        "capture": None,
        "caption": None,
        "caption_zh": "",
        "caption_zh_source": "",
        "caption_zh_history": [],
        "caption_zh_lengths": {},
        "caption_zh_latest": "",
        "caption_zh_latest_at": 0.0,
        "caption_shown_at": 0.0,
        "caption_dirty": False,
        "caption_last_previous": "",
        "caption_zh_active": 0,
        "caption_zh_at": 0.0,
        "caption_zh_failures": 0,
        "asr_silence": 0,
        "caption_requests": 0,
        "caption_ok": 0,
        "caption_dropped": 0,
        "caption_errors": 0,
        "download_progress": None,
    }

    def get_worker() -> OcrWorker:
        if state["worker"] is None:
            state["worker"] = OcrWorker()
        return state["worker"]

    def save_popup_state() -> None:
        # 只更新 popup 一段：以磁盘上的文件为准，避免一个持有旧内存配置的
        # 实例退出时把 API key / 热键等外部修改整份覆盖掉。
        try:
            fresh = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            fresh = json.loads(json.dumps(config))
        section = fresh.setdefault("popup", {})
        section.pop("pinned", None)
        section["placed"] = popup.has_saved_position()
        if popup.has_saved_position():
            position = popup.pos()
            section["x"], section["y"] = position.x(), position.y()
        try:
            save_config(fresh)
            config["popup"] = dict(section)
        except Exception as exc:  # noqa: BLE001
            _debug(f"save popup state failed: {exc}")

    def mark_hint_shown() -> None:
        try:
            fresh = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            fresh = json.loads(json.dumps(config))
        fresh["hint_shown"] = True
        try:
            save_config(fresh)
            config["hint_shown"] = True
        except Exception as exc:  # noqa: BLE001
            _debug(f"save hint flag failed: {exc}")

    def save_ocr_language(value: str) -> None:
        try:
            fresh = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            fresh = json.loads(json.dumps(config))
        fresh.setdefault("ocr", {})["language"] = value
        try:
            save_config(fresh)
            config.setdefault("ocr", {})["language"] = value
        except Exception as exc:  # noqa: BLE001
            _debug(f"save ocr language failed: {exc}")

    def show_result(
        status: str,
        source: str = "",
        translation: str = "",
        is_error: bool = False,
        force: bool = False,
        terms: list[dict] | None = None,
    ) -> None:
        popup.set_content(source, translation, status, is_error, terms=terms)
        if state["subtitle_on"]:
            # 同传开着时手动翻一次：先让译文完整显示 8 秒，别被下一句字幕顶掉。
            state["caption_pause_until"] = time.time() + 8.0
        if state["hidden"] and not force:
            return  # 已收进托盘：自动翻译只更新内容，不把窗口弹回来
        if popup.has_saved_position():
            popup.place_saved()  # 放好之后不再跟随选框
        else:
            # 首次出现：在选框下方；收进托盘时放在鼠标附近。
            if state["hidden"]:
                popup.place_below(QCursor.pos() + QPoint(0, 18))
            else:
                popup.place_below_rect(frame.geometry())
            popup.save_position()
            save_popup_state()
        popup.show()
        popup.raise_()

    def on_done(result: dict) -> None:
        nonlocal history
        state["busy"] = False
        auto.set_busy(False)
        if "error" in result:
            auto.mark_failed()
            show_result(f"出错：{result['error']}", is_error=True, force=state["manual"])
            return
        text = result["text"]
        if not text.strip():
            show_result("区域内没有识别到文字", force=state["manual"])
            return
        if state["manual"]:
            auto.note_manual_translation()
            history = add_entry(
                history,
                text,
                result["translation"],
                state["kind"],
            )
            try:
                save_history(history)
            except Exception as exc:  # noqa: BLE001
                _debug(f"save history failed: {exc}")
        if result.get("fallback"):
            _debug(f"translate fallback: {result.get('reason')}")
        status = (
            "大模型暂不可用，已改用免费通道"
            if result.get("fallback") == "free"
            else ""
        )
        show_result(
            status,
            text,
            result["translation"],
            force=state["manual"],
            terms=result.get("terms") or [],
        )

    signals.done.connect(on_done)

    def start_translation(png: bytes | None = None, manual: bool = True) -> None:
        if state["busy"]:
            if manual:
                show_result("上一次还在处理中…", force=True)
            return
        state["busy"] = True
        state["manual"] = manual
        state["kind"] = "ocr"
        auto.set_busy(True)
        _debug(f"start manual={manual}")
        show_result("正在识别与翻译…", force=manual)

        # OCR 前统一抓 2 倍图：小字号（菜单/代码）识别率明显更好。
        try:
            x, y, width, height = capture.window_rect(frame)
            png = capture.grab_region(x, y, width, height, scale=2)
        except Exception:
            if png is None:
                raise

        def work() -> dict:
            text = get_worker().recognize(png, lang=state["ocr_lang"])
            if not text.strip():
                return {"text": "", "translation": "", "terms": []}
            result = translate_rich(text, config)
            return {
                "text": text,
                "translation": result["text"],
                "terms": result["terms"],
                "fallback": result.get("fallback"),
            }

        pool.start(_Job(work, signals))

    def shutdown() -> None:
        _debug("aboutToQuit")
        hotkeys.unregister_all()
        save_popup_state()
        if geometry_timer.isActive():
            geometry_timer.stop()
        save_frame_geometry(config, frame.geometry())
        capture = state.get("capture")
        if capture is not None:
            capture.stop()
            state["capture"] = None
        asr.close()
        popup.hide()
        worker = state["worker"]
        if worker is not None:
            worker.close()

    def request_quit(source: str) -> None:
        _debug(f"quit requested by {source}")
        _APP.quit()

    def translate_selection() -> None:
        _debug("hotkey quick fired")
        text = grab_selected_text()
        _debug(f"selection text len={len(text)}")
        if not text.strip():
            label = state["hotkey_label"] or "划词热键"
            show_result(
                f"没有取到选中的文字：先在浏览器里选中文本，再按 {label}",
                is_error=True,
                force=True,
            )
            return
        if state["busy"]:
            return
        state["busy"] = True
        state["manual"] = True
        state["kind"] = "selection"
        auto.set_busy(True)
        _debug("start selection-translate")
        show_result("正在翻译选中文字…", force=True)

        def work() -> dict:
            result = translate_rich(text, config)
            return {
                "text": text,
                "translation": result["text"],
                "terms": result["terms"],
                "fallback": result.get("fallback"),
            }

        pool.start(_Job(work, signals))

    def apply_quick_hotkey(preferred: str | None = None) -> str:
        """按配置注册划词热键，占用时回退；返回真正生效的组合名（空=未绑定）。"""
        if state["hotkey_id"]:
            hotkeys.unregister(state["hotkey_id"])
            state["hotkey_id"] = 0

        wanted = str(
            config.get("quick_hotkey", "") if preferred is None else preferred
        ).strip()
        candidates = [wanted] + [key for key in QUICK_HOTKEY_FALLBACKS if key != wanted]
        for text in candidates:
            parsed = parse_sequence(text)
            if parsed is None:
                continue
            hotkey_id = hotkeys.register(parsed[0], parsed[1], translate_selection)
            if hotkey_id:
                state["hotkey_id"] = hotkey_id
                state["hotkey_label"] = normalize_sequence(text) or text
                tray.set_hotkeys(state["hotkey_label"])
                _debug(f"quick hotkey registered as {state['hotkey_label']!r}")
                _log_line(
                    f"quick hotkey registered as {state['hotkey_label']!r} (requested {wanted!r})"
                )
                return state["hotkey_label"]

        state["hotkey_label"] = ""
        tray.set_hotkeys("未绑定")
        _debug("no quick hotkey could be registered")
        _log_line(f"no quick hotkey could be registered (requested {wanted!r})")
        return ""

    def apply_mode(mode: str) -> None:
        """模式只有一个真值来源：自动器；控制条与右键菜单都只是它的入口。"""
        enabled = mode == "auto"
        auto.set_enabled(enabled)
        frame.set_auto_checked(enabled)
        bar.set_mode("auto" if enabled else "manual")
        tray.set_auto_checked(enabled)

    def ensure_frame_visible() -> None:
        """只在用户真的要选区域时才把矩形叫出来。"""
        state["hidden"] = False
        if not frame.isVisible():
            frame.show()
            frame.raise_()
        bar.place_for(frame.geometry())
        bar.show()
        bar.raise_()

    def on_mode_changed(mode: str) -> None:
        ensure_frame_visible()
        apply_mode(mode)

    def on_bar_translate() -> None:
        ensure_frame_visible()
        start_translation()

    def close_frame_only() -> None:
        """只隐藏选框，功能浮窗留在右上角。"""
        frame.hide()
        state["hidden"] = False
        bar.place_default()
        bar.show()
        bar.raise_()
        _debug("frame closed, bar kept")

    def on_popup_closed() -> None:
        """点浮窗的 ×：同传开着就一起停掉，避免看不见但还在后台跑。"""
        if state["subtitle_on"]:
            toggle_subtitles(False)
        else:
            popup.hide()

    def toggle_visibility() -> None:
        if bar.isVisible() or frame.isVisible():
            hide_to_tray()
        else:
            state["hidden"] = False
            bar.place_default()
            bar.show()
            bar.raise_()
        if not bar.isVisible():
            popup.hide()

    def hide_to_tray() -> None:
        """控制条 ✕ / Esc：收进托盘，进程与热键继续活着。"""
        _debug("hide to tray")
        state["hidden"] = True
        frame.hide()
        bar.hide()
        popup.hide()
        if not state["tray_hinted"]:
            state["tray_hinted"] = True
            tray.notify(
                "矩形翻译仍在后台",
                "点托盘图标可恢复选框；要完全关闭，请用托盘菜单里的「退出」。",
            )

    def reveal_frame() -> None:
        """第二次启动快捷方式时，只把功能浮窗唤到前面，不弹矩形。"""
        state["hidden"] = False
        if not bar.isVisible():
            bar.place_default()
        bar.show()
        bar.raise_()
        _debug("revealed bar by second launch")

    def open_settings() -> None:
        nonlocal config
        was_auto = auto.enabled
        auto.set_enabled(False)  # 设置窗口是模态的，别让浮窗盖上来
        # 录制新热键时要能亲手按到当前组合：先释放全局注册，否则会被系统截走。
        hotkeys.unregister(state["hotkey_id"])
        state["hotkey_id"] = 0
        requested = None
        original_style = _frame_style(config)
        accepted = False
        try:
            dialog = SettingsWindow(config, current_hotkey=state["hotkey_label"])
            dialog.frame_style_changed.connect(
                lambda style: frame.apply_style(
                    style["color"], style["thickness"], style["length"]
                )
            )
            if dialog.exec() and dialog.saved_config is not None:
                accepted = True
                config = dialog.saved_config
                requested = normalize_sequence(str(config.get("quick_hotkey", "")))
        finally:
            if not accepted:
                frame.apply_style(*original_style)
            actual = apply_quick_hotkey()
            if requested and actual and actual != requested:
                tray.notify(
                    "热键已被占用",
                    f"{requested} 被别的程序占用了，划词已改用 {actual}。",
                )
            apply_mode("auto" if was_auto else "manual")

    def open_history() -> None:
        nonlocal history
        dialog = HistoryWindow(history)
        dialog.exec()
        if dialog.cleared:
            history = []
            try:
                save_history(history)
            except Exception as exc:  # noqa: BLE001
                _debug(f"save history failed: {exc}")

    def run_asr(window, window_start: float, window_seconds: float) -> None:
        state["asr_busy"] = True
        state["asr_started"] = time.time()
        state["asr_audio_seconds"] = len(window) / 16000.0

        def work() -> dict:
            return {
                "words": asr.transcribe_words(window),
                "start": window_start,
                "seconds": window_seconds,
            }

        pool.start(_Job(work, asr_signals))

    def on_audio_window(payload) -> None:
        if not state["subtitle_on"]:
            return
        window, window_start = payload
        rms = float(np.sqrt(np.mean(np.square(window, dtype=np.float32))))
        if rms < SILENCE_RMS:
            state["asr_silence"] += 1
            _debug(f"asr skip silent window at {window_start:.1f}s rms={rms:.5f}")
            return
        if state["asr_silence"] >= 2:
            # 暂停/长静音后恢复：当前半句收尾，别和恢复后的语音拼在一起。
            caption = state.get("caption")
            if caption is not None:
                caption.break_current()
                state["caption_last_previous"] = caption.snapshot()[1]
            state["caption_zh"] = ""
        state["asr_silence"] = 0
        queue = state["asr_queue"]
        if len(queue) >= 3:
            queue.pop(0)  # 滚动窗口互相重叠，落后时丢最旧的不会留下空洞
        queue.append((window, window_start))
        if not state["asr_busy"]:
            start_next_asr()

    def start_next_asr() -> None:
        if not state["subtitle_on"] or state["asr_busy"]:
            return
        queue = state["asr_queue"]
        if not queue:
            return
        window, window_start = queue.pop(0)
        run_asr(window, window_start, len(window) / 16000.0)

    def refresh_caption(force: bool = False) -> None:
        """只画中文：当前句大字，上一句小字。英文不占浮窗。"""
        caption = state.get("caption")
        if caption is None or not state["subtitle_on"]:
            return
        if time.time() < state["caption_pause_until"]:
            return
        now = time.time()
        if not force and now - state["caption_shown_at"] < 1.5:
            # 快速语速下译文更新太密会看不清：同一位置至少停留 1.5 秒。
            state["caption_dirty"] = True
            if not caption_hold.isActive():
                caption_hold.start(
                    int((1.5 - (now - state["caption_shown_at"])) * 1000)
                )
            return
        current, _previous = caption.snapshot()
        zh = state["caption_zh"]
        lines = ([zh] if zh else []) + list(state["caption_zh_history"])
        if not lines:
            latest = state["caption_zh_latest"]
            if latest and time.time() - state["caption_zh_latest_at"] < 6.0:
                popup.set_caption_zh_lines([latest])
            elif current:
                popup.set_caption_status("正在翻译…")
            return
        if zh and current:
            source = state["caption_zh_source"]
            if len(source) < len(current) * 0.75:
                # 只覆盖了当前句一部分的半句不占当前行，先把上一句完整译文留着。
                zh = ""
                lines = list(state["caption_zh_history"])
        display = int((config.get("caption") or {}).get("display_lines", 3))
        display = max(2, min(4, display))
        popup.set_caption_zh_lines(lines, display_lines=display)
        state["caption_shown_at"] = now
        state["caption_dirty"] = False

    caption_hold.timeout.connect(lambda: refresh_caption(force=True))

    def request_caption_translation(
        text: str,
        target: str = "current",
        sentence_id: int = -1,
        force: bool = False,
        context: str = "",
    ) -> None:
        if not state["subtitle_on"] or not text.strip():
            return
        if target == "current" and len(text.split()) < 3:
            return  # 两三个词的半句不值得单独请求
        if target == "previous" and len(text.split()) < 2:
            return
        if time.time() < state["caption_pause_until"]:
            return
        now = time.time()
        if (
            target == "current"
            and not force
            and now - state["caption_zh_at"] < 0.9
        ):
            return
        if state["caption_zh_active"] >= 3:
            return
        if target == "current":
            state["caption_zh_at"] = now
        state["caption_zh_active"] += 1
        state["caption_requests"] += 1
        source = text
        _trace_caption(
            "request",
            source=source,
            target=target,
            sentence=sentence_id,
            context_len=len(context),
        )

        def work() -> dict:
            started = time.time()
            try:
                return {
                    "text": translate_caption(
                        source, config, timeout=8.0, context=context
                    ),
                    "source": source,
                    "target": target,
                    "sentence_id": sentence_id,
                    "context_len": len(context),
                    "elapsed": time.time() - started,
                }
            except Exception as exc:  # noqa: BLE001
                return {
                    "error": f"{type(exc).__name__}: {exc}",
                    "source": source,
                    "target": target,
                    "sentence_id": sentence_id,
                    "context_len": len(context),
                    "elapsed": time.time() - started,
                }

        pool.start(_Job(work, caption_signals))

    def on_caption_translated(result: dict) -> None:
        state["caption_zh_active"] = max(0, state["caption_zh_active"] - 1)
        source = str(result.get("source", ""))
        target = str(result.get("target", "current"))
        sentence_id = int(result.get("sentence_id", -1))
        elapsed = float(result.get("elapsed", 0.0))
        if "error" in result:
            state["caption_zh_failures"] += 1
            state["caption_errors"] += 1
            _log_line(f"caption translate failed: {result['error']}")
            _trace_caption(
                "error",
                source=source,
                target=target,
                sentence=sentence_id,
                context_len=int(result.get("context_len", 0)),
                elapsed=round(elapsed, 2),
                error=result["error"],
            )
            if (
                state["caption_zh_failures"] >= 2
                and not state["caption_zh"]
                and not state["caption_zh_history"]
            ):
                popup.set_caption_status("中文翻译失败，请检查网络或 API")
        else:
            state["caption_zh_failures"] = 0
            text = str(result.get("text", "")).strip()
            if text:
                state["caption_zh_latest"] = text
                state["caption_zh_latest_at"] = time.time()
            caption = state.get("caption")
            accepted = ""
            if caption is not None and text:
                lengths = state["caption_zh_lengths"]
                if sentence_id == caption.current_id:
                    if len(source) >= lengths.get(sentence_id, 0):
                        state["caption_zh"] = text
                        state["caption_zh_source"] = source
                        lengths[sentence_id] = len(source)
                        accepted = "current"
                elif sentence_id == caption.previous_id:
                    if len(source) >= lengths.get(sentence_id, 0):
                        history = state["caption_zh_history"]
                        if history:
                            history[0] = text
                        else:
                            history.append(text)
                        lengths[sentence_id] = len(source)
                        accepted = "previous"
                if len(lengths) > 40:
                    cutoff = caption.current_id - 10
                    state["caption_zh_lengths"] = {
                        key: value
                        for key, value in lengths.items()
                        if key >= cutoff
                    }
                if accepted:
                    refresh_caption(force=True)
                    state["caption_ok"] += 1
                else:
                    state["caption_dropped"] += 1
                    if (
                        text
                        and text != state["caption_zh"]
                        and text not in state["caption_zh_history"]
                    ):
                        # 迟到的完整译文也别丢，放进历史行，至少让用户看到。
                        state["caption_zh_history"].append(text)
                        del state["caption_zh_history"][30:]
                    refresh_caption()
            _trace_caption(
                "result",
                source=source,
                target=target,
                sentence=sentence_id,
                context_len=int(result.get("context_len", 0)),
                elapsed=round(elapsed, 2),
                text=text,
                accepted=accepted or "dropped",
            )

    def on_asr_done(result: dict) -> None:
        state["asr_busy"] = False
        elapsed = time.time() - state["asr_started"] if state["asr_started"] else 0.0
        _debug(
            f"asr {state['asr_audio_seconds']:.1f}s audio in {elapsed:.2f}s "
            f"queue={len(state['asr_queue'])}"
        )
        if state["subtitle_on"]:
            if "error" in result:
                popup.set_caption_status(f"识别失败：{result['error']}")
            else:
                caption = state.get("caption")
                fresh = (
                    caption.add_window(
                        result.get("words", []),
                        float(result.get("start", 0.0)),
                        float(result.get("seconds", 0.0)),
                    )
                    if caption is not None
                    else []
                )
                if fresh:
                    current, previous = caption.snapshot()
                    if previous and previous != state["caption_last_previous"]:
                        state["caption_last_previous"] = previous
                        if state["caption_zh"] and not is_partial(
                            state["caption_zh"]
                        ):
                            history = state["caption_zh_history"]
                            text = state["caption_zh"]
                            if history and difflib.SequenceMatcher(
                                None, history[0], text
                            ).ratio() > 0.6:
                                if len(text) > len(history[0]):
                                    history[0] = text
                            else:
                                history.insert(0, text)
                            del state["caption_zh_history"][30:]
                        state["caption_zh"] = ""
                        current, _ = caption.snapshot()
                        if previous:
                            request_caption_translation(
                                previous,
                                "previous",
                                caption.previous_id,
                                context=caption.context_before(2),
                            )
                    refresh_caption()
                    if current:
                        context_lines = int(
                            (config.get("caption") or {}).get("context_lines", 2)
                        )
                        context_lines = max(1, min(3, context_lines))
                        request_caption_translation(
                            current,
                            "current",
                            caption.current_id,
                            context=caption.context(context_lines),
                        )
                    _debug(
                        f"caption committed_end={caption.committed_end:.2f}s "
                        f"fresh={len(fresh)} current={len(current)}chars"
                    )
        if state["subtitle_on"]:
            start_next_asr()

    def on_audio_error(message: str) -> None:
        _debug(f"audio capture failed: {message}")
        toggle_subtitles(False)
        tray.set_subtitle_checked(False)
        tray.notify("系统声音采集失败", message, 5000)

    def on_model_downloaded(result: dict) -> None:
        progress = state.get("download_progress")
        state["download_progress"] = None
        if progress is not None:
            progress.close()
        if result.get("ok"):
            tray.notify("语音模型已就绪", "现在可以开启同声传译了。", 4000)
            toggle_subtitles(True)
            return
        QMessageBox.warning(
            None,
            "模型下载失败",
            "下载没有完成，请检查网络后重试，或手动运行 tools\\download-model.ps1。\n\n"
            + str(result.get("output", ""))[-600:],
        )

    def toggle_subtitles(enabled: bool) -> None:
        if enabled:
            if not model_available():
                answer = QMessageBox.question(
                    None,
                    "需要语音模型",
                    "同声传译需要下载约 75MB 的 tiny.en 语音模型。\n"
                    "现在自动下载吗？",
                    QMessageBox.StandardButton.Yes
                    | QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    tray.set_subtitle_checked(False)
                    return
                progress = QProgressDialog(
                    "正在下载语音模型…", None, 0, 0, None
                )
                progress.setWindowTitle("下载模型")
                progress.setWindowModality(Qt.WindowModality.ApplicationModal)
                progress.setCancelButton(None)
                progress.show()
                state["download_progress"] = progress

                def work() -> dict:
                    script = APP_DIR / "tools" / "download-model.ps1"
                    completed = subprocess.run(
                        [
                            "powershell",
                            "-NoProfile",
                            "-ExecutionPolicy",
                            "Bypass",
                            "-File",
                            str(script),
                        ],
                        capture_output=True,
                        text=True,
                        timeout=900,
                    )
                    output = (completed.stdout or "") + (completed.stderr or "")
                    return {
                        "ok": completed.returncode == 0 and model_available(),
                        "output": output,
                    }

                pool.start(_Job(work, download_signals))
                return
            popup.show_caption(bar.geometry())
            popup.set_caption_status("正在加载英文模型…")
            QApplication.processEvents()
            try:
                asr.load()
            except Exception as exc:  # noqa: BLE001
                popup.hide()
                tray.set_subtitle_checked(False)
                tray.notify("语音模型加载失败", str(exc), 6000)
                return
            try:
                loopback = RollingCapture(
                    on_window=lambda window, start: bridge.segment.emit(
                        (window, start)
                    ),
                    on_error=bridge.failed.emit,
                )
                loopback.start()
            except Exception as exc:  # noqa: BLE001
                tray.set_subtitle_checked(False)
                tray.notify("无法采集系统声音", str(exc), 6000)
                return
            state["capture"] = loopback
            state["caption"] = CaptionAssembler()
            state["subtitle_on"] = True
            state["caption_pause_until"] = 0.0
            state["caption_zh"] = ""
            state["caption_zh_source"] = ""
            state["caption_zh_history"] = []
            state["caption_zh_lengths"] = {}
            state["caption_zh_latest"] = ""
            state["caption_zh_latest_at"] = 0.0
            state["caption_shown_at"] = 0.0
            state["caption_dirty"] = False
            state["caption_last_previous"] = ""
            state["caption_zh_active"] = 0
            state["caption_zh_at"] = 0.0
            state["caption_zh_failures"] = 0
            state["asr_silence"] = 0
            state["caption_requests"] = 0
            state["caption_ok"] = 0
            state["caption_dropped"] = 0
            state["caption_errors"] = 0
            _trace_caption("session_start", provider=str(
                (config.get("translate") or {}).get("provider", "deepseek")
            ))
            state["asr_queue"] = []
            popup.clear_caption()
            popup.set_caption_status("正在采集系统声音…")
            popup.raise_()
            bar.set_caption_active(True)
            tray.set_subtitle_checked(True)
            tray.notify(
                "系统声音字幕已开启",
                "只采集系统输出，在本机识别，不保存音频。",
                4000,
            )
        else:
            state["subtitle_on"] = False
            state["asr_queue"] = []
            loopback = state.get("capture")
            if loopback is not None:
                loopback.stop()
            state["capture"] = None
            state["caption"] = None
            state["caption_zh"] = ""
            state["caption_zh_source"] = ""
            state["caption_zh_history"] = []
            state["caption_zh_lengths"] = {}
            state["caption_zh_latest"] = ""
            state["caption_zh_latest_at"] = 0.0
            state["caption_shown_at"] = 0.0
            state["caption_dirty"] = False
            state["caption_last_previous"] = ""
            state["caption_zh_active"] = 0
            state["caption_zh_failures"] = 0
            state["asr_silence"] = 0
            _trace_caption(
                "session_stop",
                requests=state["caption_requests"],
                ok=state["caption_ok"],
                dropped=state["caption_dropped"],
                errors=state["caption_errors"],
            )
            popup.hide()
            bar.set_caption_active(False)
            tray.set_subtitle_checked(False)

    def reset_popup_position() -> None:
        popup.clear_saved_position()
        popup.place_below_rect(frame.geometry())
        popup.save_position()
        save_popup_state()
        popup.show()

    def on_ocr_language_changed(value: str) -> None:
        state["ocr_lang"] = value if value in ("auto", "zh", "en") else "auto"
        save_ocr_language(state["ocr_lang"])

    frame.translate_requested.connect(start_translation)
    auto.triggered.connect(lambda payload: start_translation(payload, False))
    frame.quit_requested.connect(hide_to_tray)
    popup.hide_requested.connect(on_popup_closed)
    popup.position_changed.connect(save_popup_state)
    popup.reset_requested.connect(reset_popup_position)
    bar.mode_changed.connect(on_mode_changed)
    bar.theme_changed.connect(popup.set_theme)
    bar.settings_requested.connect(open_settings)
    bar.translate_requested.connect(on_bar_translate)
    bar.quit_requested.connect(hide_to_tray)
    bar.caption_requested.connect(
        lambda: toggle_subtitles(not state["subtitle_on"])
    )
    bar.close_frame_requested.connect(close_frame_only)
    tray.toggle_requested.connect(toggle_visibility)
    tray.quick_requested.connect(translate_selection)
    tray.history_requested.connect(open_history)
    tray.subtitle_toggled.connect(toggle_subtitles)
    tray.settings_requested.connect(open_settings)
    tray.auto_toggled.connect(lambda on: apply_mode("auto" if on else "manual"))
    tray.quit_requested.connect(lambda: request_quit("tray"))
    frame.auto_toggled.connect(lambda enabled: apply_mode("auto" if enabled else "manual"))
    frame.ocr_language_changed.connect(on_ocr_language_changed)
    bridge.segment.connect(on_audio_window)
    bridge.failed.connect(on_audio_error)
    asr_signals.done.connect(on_asr_done)
    caption_signals.done.connect(on_caption_translated)
    download_signals.done.connect(on_model_downloaded)
    frame.geometry_changed.connect(bar.place_for)
    frame.geometry_changed.connect(lambda _rect: geometry_timer.start())
    _APP.installNativeEventFilter(hotkeys)
    apply_quick_hotkey()
    _APP.aboutToQuit.connect(shutdown)

    auto_enabled = "--no-auto" not in argv and frame.isVisible()
    apply_mode("auto" if auto_enabled else "manual")
    bar.place_default()
    bar.show()
    tray.show()
    _debug(
        f"tray visible={tray.isVisible()} available={tray.isSystemTrayAvailable()}"
    )

    if _ACTIVATE_EVENT:
        activate_timer = QTimer(_APP)
        activate_timer.setInterval(400)
        activate_timer.timeout.connect(
            lambda: reveal_frame() if _consume_activate_event(_ACTIVATE_EVENT) else None
        )
        activate_timer.start()

    if config_created:
        QTimer.singleShot(
            1200,
            lambda: tray.notify(
                "已生成默认配置",
                "当前使用免费通道，免 key 即可翻译；要更稳定的质量，请在设置里切换大模型并填入 API key。",
                7000,
            ),
        )

    # 启动后把「实际用的热键」告诉用户：被别的程序占用时不能默默换键。
    requested = normalize_sequence(str(config.get("quick_hotkey", "")))
    if state["hotkey_label"] and requested and state["hotkey_label"] != requested:
        QTimer.singleShot(
            1500,
            lambda: tray.notify(
                "划词热键已调整",
                f"{requested} 被别的程序占用，划词改用 {state['hotkey_label']}。",
                6000,
            ),
        )
    elif not state["hotkey_label"]:
        QTimer.singleShot(
            1500,
            lambda: tray.notify(
                "划词热键未绑定", "候选组合都被占用了，请到设置里换一个。", 6000
            ),
        )

    if not config.get("hint_shown") and not any(a.startswith("--dump") for a in argv):
        def show_hint() -> None:
            tray.notify(
                "怎么翻译当前区域",
                "点控制条上的「翻译」翻当前矩形；「自动」会随内容变化自己翻。",
                6000,
            )
            mark_hint_shown()

        QTimer.singleShot(2500, show_hint)

    if "--dump-state" in argv:
        def dump() -> None:
            mask = frame.mask()
            print(json.dumps(
                {
                    "frame": {
                        "geometry": list(frame.geometry().getRect()),
                        "visible": frame.isVisible(),
                        "mask_bounds": list(mask.boundingRect().getRect()) if not mask.isEmpty() else None,
                        "win_id": int(frame.winId()),
                        "screen": frame.screen().name() if frame.screen() else None,
                    },
                    "popup": {
                        "geometry": list(popup.geometry().getRect()),
                        "visible": popup.isVisible(),
                        "size_hint": [popup.sizeHint().width(), popup.sizeHint().height()],
                    },
                    "primary_screen": [
                        QApplication.primaryScreen().geometry().getRect(),
                        QApplication.primaryScreen().devicePixelRatio(),
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ), flush=True)
            _APP.quit()

        QTimer.singleShot(1500, dump)

    if "--dump-tray" in argv:
        def visible_state() -> dict:
            quit_rect = next(
                rect for group, value, rect in bar._segments() if group == "quit"
            )
            return {
                "frame": frame.isVisible(),
                "bar": bar.isVisible(),
                "popup": popup.isVisible(),
                "hotkey": state["hotkey_label"],
                "quit_segment": list(quit_rect.getRect()),
                "bar_size": [bar.width(), bar.height()],
            }

        def dump_tray() -> None:
            bar.quit_requested.emit()  # 与鼠标点控制条 ✕ 走同一条信号
            print(json.dumps({"after_bar_close": visible_state()}, ensure_ascii=False))
            tray.toggle_requested.emit()  # 与托盘左键 / 菜单项走同一条信号
            print(json.dumps({"after_tray_restore": visible_state()}, ensure_ascii=False))
            QTimer.singleShot(200, _APP.quit)

        QTimer.singleShot(1200, dump_tray)

    if "--dump-quick" in argv:
        def dump_quick() -> None:
            bar.quit_requested.emit()  # 与点 ✕ 同一条信号：收进托盘
            translate_selection()  # 后台划词；自检环境没有选区，会显示错误浮窗
            print(json.dumps(
                {
                    "frame": frame.isVisible(),
                    "bar": bar.isVisible(),
                    "popup": popup.isVisible(),
                    "popup_pos": [popup.x(), popup.y()],
                    "saved": popup.has_saved_position(),
                },
                ensure_ascii=False,
            ))
            QTimer.singleShot(200, _APP.quit)

        QTimer.singleShot(1200, dump_quick)

    if "--dump-startup" in argv:
        def snapshot() -> dict:
            return {
                "frame": frame.isVisible(),
                "bar": bar.isVisible(),
                "bar_pos": [bar.x(), bar.y()],
                "bar_size": [bar.width(), bar.height()],
                "frame_geometry": [
                    frame.x(), frame.y(), frame.width(), frame.height()
                ],
                "screen": [
                    bar.screen().availableGeometry().width(),
                    bar.screen().availableGeometry().height(),
                ],
            }

        def dump_startup() -> None:
            before = snapshot()
            bar.mode_changed.emit("manual")
            QApplication.processEvents()
            after = snapshot()
            bar.close_frame_requested.emit()
            QApplication.processEvents()
            after_close = snapshot()
            print(json.dumps(
                {
                    "startup": before,
                    "after_select": after,
                    "after_frame_close": after_close,
                },
                ensure_ascii=False,
            ))
            QTimer.singleShot(200, _APP.quit)

        QTimer.singleShot(1500, dump_startup)

    if "--dump-subtitles" in argv:
        def enable_subtitles() -> None:
            toggle_subtitles(True)

        def play_wav() -> None:
            if "--play-wav" in argv:
                import winsound

                winsound.PlaySound(
                    argv[argv.index("--play-wav") + 1],
                    winsound.SND_FILENAME | winsound.SND_ASYNC,
                )

        def dump_subtitles() -> None:
            caption = state.get("caption")
            print(json.dumps(
                {
                    "text": popup.caption_text(),
                    "previous": popup.caption_previous(),
                    "status": popup.status_text(),
                    "subtitle_visible": popup.isVisible(),
                    "popup_pos": [popup.x(), popup.y()],
                    "popup_size": [popup.width(), popup.height()],
                    "screen": [
                        popup.screen().availableGeometry().width(),
                        popup.screen().availableGeometry().height(),
                    ],
                    "committed_end": (
                        round(caption.committed_end, 2) if caption is not None else 0.0
                    ),
                },
                ensure_ascii=False,
            ))
            toggle_subtitles(False)
            QTimer.singleShot(200, _APP.quit)

        QTimer.singleShot(800, enable_subtitles)
        QTimer.singleShot(2000, play_wav)
        dump_after = 22.0
        if "--dump-after" in argv:
            dump_after = float(argv[argv.index("--dump-after") + 1])
        QTimer.singleShot(int(dump_after * 1000), dump_subtitles)

    code = _APP.exec()
    _debug(f"exec returned {code}")
    return code


def main(argv: list[str] | None = None) -> int:
    global _ACTIVATE_EVENT
    args = list(sys.argv[1:] if argv is None else argv)
    if "--ocr-worker" in args:
        # 打包后 sys.executable 是 exe 本身：用参数回到同一个程序跑 OCR 子进程
        from recttrans.ocr_worker import main as ocr_worker_main

        return ocr_worker_main()
    _ensure_std_streams()
    if "--selftest" in args:
        return run_selftest(args)
    if "--allow-multi" in args:
        # 诊断用：跳过单实例检查，不影响正在运行的用户实例
        return run_app(args)
    if not _acquire_single_instance():
        _debug("another instance is running; exiting")
        try:
            with DEBUG_LOG.open("a", encoding="utf-8") as handle:
                handle.write(
                    f"{time.strftime('%Y-%m-%d %H:%M:%S')} "
                    f"second instance pid={os.getpid()} build={BUILD}\n"
                )
        except Exception:  # noqa: BLE001
            pass
        if not _signal_existing_instance():
            _notify_already_running()
        return 0
    _ACTIVATE_EVENT = _create_activate_event()
    return run_app(args)
