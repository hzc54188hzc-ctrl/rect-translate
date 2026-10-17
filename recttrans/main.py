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

from PySide6.QtCore import QObject, QPoint, QRect, QRunnable, QThreadPool, QTimer, Signal
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtWidgets import QApplication

from recttrans import capture
from recttrans.autotrans import AutoTranslator
from recttrans.config import CONFIG_PATH, ensure_config, load_config, save_config
from recttrans.controls import ModeBar
from recttrans.frame import RegionFrame
from recttrans.hotkey import HotkeyManager, normalize_sequence, parse_sequence
from recttrans.ocr_client import OcrWorker
from recttrans.popup import ResultPopup
from recttrans.quick import grab_selected_text
from recttrans.settings_window import SettingsWindow
from recttrans.tray import Tray
from recttrans.translator import translate, translate_rich
from recttrans.version import BUILD

# 初始选框：短一些，方便直接放在一段文字上
DEFAULT_GEOMETRY = QRect(770, 465, 420, 110)

# 配置里的组合被占用时按顺序尝试；托盘与设置窗口显示的都是真正生效的那个。
QUICK_HOTKEY_FALLBACKS = ("Ctrl+Alt+G", "Ctrl+Shift+Q", "Ctrl+Alt+F9")

APP_DIR = pathlib.Path(__file__).resolve().parent.parent
ERROR_LOG = APP_DIR / "error.log"
DEBUG_LOG = APP_DIR / "debug.log"
_DEBUG = bool(os.environ.get("RECTTRANS_DEBUG"))


def _debug(message: str) -> None:
    if not _DEBUG:
        return
    try:
        with DEBUG_LOG.open("a", encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%H:%M:%S')} {message}\n")
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
        self._signals.done.emit(result)


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
            return _fit_to_screen(rect)
    return DEFAULT_GEOMETRY


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
    popup_cfg = config.get("popup") or {}
    # `pinned` 是 2026-10-17f 的旧字段，迁移为「已记住位置」。
    if popup_cfg.get("placed") or popup_cfg.get("pinned"):
        popup.set_saved_position(
            QPoint(int(popup_cfg.get("x", 760)), int(popup_cfg.get("y", 600)))
        )
    bar = ModeBar()
    tray = Tray()
    hotkeys = HotkeyManager()
    auto = AutoTranslator(frame)
    signals = _Signals()
    pool = QThreadPool()
    geometry_timer = QTimer()
    geometry_timer.setSingleShot(True)
    geometry_timer.setInterval(500)
    geometry_timer.timeout.connect(
        lambda: save_frame_geometry(config, frame.geometry())
    )
    state = {
        "busy": False,
        "worker": None,
        "manual": True,
        "hotkey_id": 0,
        "hotkey_label": "",
        "tray_hinted": False,
        "hidden": False,
        "ocr_lang": str((config.get("ocr") or {}).get("language", "auto")),
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
        if state["hidden"] and not force:
            return  # 已收进托盘：自动翻译只更新内容，不把窗口弹回来
        if popup.has_saved_position():
            popup.place_saved()  # 放好之后不再跟随选框
        else:
            # 首次出现：在选框下方；收进托盘时放在鼠标附近。
            anchor = (
                QCursor.pos() + QPoint(0, 18)
                if state["hidden"]
                else frame.geometry().bottomLeft()
            )
            popup.place_below(anchor)
            popup.save_position()
            save_popup_state()
        popup.show()
        popup.raise_()

    def on_done(result: dict) -> None:
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

    def toggle_visibility() -> None:
        visible = not frame.isVisible()
        state["hidden"] = not visible
        frame.setVisible(visible)
        bar.setVisible(visible)
        if not visible:
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
        """第二次启动快捷方式时，把已有实例的选框唤到前面。"""
        state["hidden"] = False
        frame.show()
        bar.show()
        bar.place_for(frame.geometry())
        frame.raise_()
        bar.raise_()
        _debug("revealed by second launch")

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

    def reset_popup_position() -> None:
        popup.clear_saved_position()
        popup.place_below(frame.geometry().bottomLeft())
        popup.save_position()
        save_popup_state()
        popup.show()

    def on_ocr_language_changed(value: str) -> None:
        state["ocr_lang"] = value if value in ("auto", "zh", "en") else "auto"
        save_ocr_language(state["ocr_lang"])

    frame.translate_requested.connect(start_translation)
    auto.triggered.connect(lambda payload: start_translation(payload, False))
    frame.quit_requested.connect(hide_to_tray)
    popup.hide_requested.connect(popup.hide)
    popup.position_changed.connect(save_popup_state)
    popup.reset_requested.connect(reset_popup_position)
    bar.mode_changed.connect(apply_mode)
    bar.theme_changed.connect(popup.set_theme)
    bar.settings_requested.connect(open_settings)
    bar.translate_requested.connect(start_translation)
    bar.quit_requested.connect(hide_to_tray)
    tray.toggle_requested.connect(toggle_visibility)
    tray.quick_requested.connect(translate_selection)
    tray.settings_requested.connect(open_settings)
    tray.auto_toggled.connect(lambda on: apply_mode("auto" if on else "manual"))
    tray.quit_requested.connect(lambda: request_quit("tray"))
    frame.auto_toggled.connect(lambda enabled: apply_mode("auto" if enabled else "manual"))
    frame.ocr_language_changed.connect(on_ocr_language_changed)
    frame.geometry_changed.connect(bar.place_for)
    frame.geometry_changed.connect(lambda _rect: geometry_timer.start())
    _APP.installNativeEventFilter(hotkeys)
    apply_quick_hotkey()
    _APP.aboutToQuit.connect(shutdown)

    frame.show()

    auto_enabled = "--no-auto" not in argv
    apply_mode("auto" if auto_enabled else "manual")
    bar.place_for(frame.geometry())
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

    code = _APP.exec()
    _debug(f"exec returned {code}")
    return code


def main(argv: list[str] | None = None) -> int:
    global _ACTIVATE_EVENT
    _ensure_std_streams()
    args = list(sys.argv[1:] if argv is None else argv)
    if "--selftest" in args:
        return run_selftest(args)
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
