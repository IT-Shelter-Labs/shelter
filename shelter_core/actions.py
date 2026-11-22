"""Выполнение действий из конфига."""

from shelter_core.paths import ROOT_DIR

import ctypes
import importlib.util
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from shelter_core import tasks
from shelter_core import policy
from shelter_core import bus

from shelter_core.avatar import AVATAR
from shelter_core import voice
from shelter_core.audio import LISTENING

ROOT = ROOT_DIR
# Окно на Rust рисует видеокарта: вчетверо легче Tk. Если exe нет (не собран,
# другая ОС) — работает прежнее окно на Python.
HUD_EXE = os.path.join(ROOT, "bin", "jarvis-hud.exe" if os.name == "nt" else "jarvis-hud")
PLUGINS_DIR = os.path.join(ROOT_DIR, "plugins")
# Через этот файл открытому окну сообщается новый заголовок и срок жизни.
OVERLAY_STATE = os.path.join(ROOT_DIR,
                             "logs", "overlay.json")
_overlay_proc = None
_avatar_until = 0.0
_allow_shell = False
_allow_plugins = False
_profiles = {}
_runtime_config = {}
_tool_handler = None


def configure_tool(handler, ask=None):
    """handler(имя, аргумент, подтверждено) — инструмент; ask(вопрос) — ответ ассистента."""
    global _tool_handler, _ask_handler
    _tool_handler = handler
    _ask_handler = ask


_ask_handler = None
_plugin_modules = {}
RIOT_CLIENT = r"C:\Riot Games\Riot Client\RiotClientServices.exe"
RIOT_LOCKFILE = os.path.join(
    os.environ.get("LOCALAPPDATA", ""),
    "Riot Games", "Riot Client", "Config", "lockfile",
)
CURL = os.path.join(os.environ.get("WINDIR", r"C:\Windows"),
                    "System32", "curl.exe")
IS_WINDOWS = sys.platform == "win32"

# В отличие от VK_MEDIA_PLAY_PAUSE эти команды не являются переключателями.
APP_COMMANDS = {
    "next": 11,
    "prev": 12,
    "stop": 13,
    "toggle": 14,
    "play": 46,
    "pause": 47,
    "mute": 8,
    "voldown": 9,
    "volup": 10,
}


def configure(config):
    """Применить настройки, общие для обработчиков действий."""
    global _allow_shell, _allow_plugins, _profiles, _runtime_config
    security = config.get("security") or {}
    _allow_shell = bool(security.get("allow_shell", False))
    _allow_plugins = bool(security.get("allow_plugins", False))
    _profiles = config.get("profiles") or {}
    _runtime_config = config
    AVATAR.configure(config)


def _run_plugin(action):
    """Плагин — в отдельном процессе (plugins_manager): зависание или падение
    плагина не останавливает Джарвиса. Плагину передаются только его параметры."""
    if not _allow_plugins:
        raise RuntimeError("плагины отключены в security.allow_plugins")
    from shelter_core import plugins_manager
    name = str(action.get("name", ""))
    configured = ((_runtime_config or {}).get("plugins") or {})
    settings = (configured.get("settings") or {}).get(name, configured.get(name) or {})
    try:
        result = plugins_manager.call(name, str(action.get("action") or ""), action.get("params") or {},
                                      settings if isinstance(settings, dict) else {}, token=tasks.current())
    except plugins_manager.PluginError as error:
        if tasks.current() is not None and tasks.current().is_set():
            raise tasks.Cancelled()
        raise RuntimeError(str(error)) from error
    if isinstance(result, dict) and isinstance(result.get("say"), str) and result["say"].strip():
        voice.say(result["say"][:500])
    return result


class ActionRunner:
    """Последовательный исполнитель: UI и аудиопотоки не блокируются.

    Одинаковое событие (например, повторный звук банки) не ставится второй раз,
    пока его цепочка действий ещё выполняется.
    """

    def __init__(self):
        self._jobs = queue.Queue(maxsize=64)
        self._closed = False
        self._current = None
        self.current_label = ""
        self._active_keys = set()
        self._lock = threading.Lock()
        self._stop = object()
        self._thread = threading.Thread(target=self._run, name="actions", daemon=True)
        self._thread.start()

    def submit(self, actions, key=None, label=None, session_id=None):
        actions = list(actions)
        if not actions:
            return True
        with self._lock:
            if self._closed or self._jobs.full():
                return False
            if key is not None and key in self._active_keys:
                print(f"[action] {key} уже выполняется — повтор пропущен")
                return False
            if key is not None:
                self._active_keys.add(key)
            self._jobs.put_nowait((actions, key, self._journal(label, session_id), label))
        return True

    def submit_lazy(self, factory, key=None, label=None, session_id=None, context=None):
        """Получить действия в рабочем потоке: LLM не задерживает события."""
        with self._lock:
            if self._closed or self._jobs.full():
                return False
            if key is not None and key in self._active_keys:
                return False
            if key is not None:
                self._active_keys.add(key)
            self._jobs.put_nowait((factory, key, self._journal(label, session_id), label, context))
        return True

    @staticmethod
    def _journal(label, session_id):
        if label:
            from shelter_core import assistant_store as store
            return store.create_run(label, session_id)
        return None, None

    def _run(self):
        while True:
            job = self._jobs.get()
            if job is self._stop:
                return
            actions, key, journal, label = job[:4]
            token = tasks.Token(run_id=journal[0], session_id=journal[1])
            token.remote = job[4] if len(job) > 4 else None
            self._current = token
            self.current_label = label or ""
            status = "done"
            try:
                with tasks.scope(token):
                    if self._closed:
                        status = "cancelled"
                        continue
                    if token.run_id:
                        from shelter_core import assistant_store as store
                        run = store.run_detail(token.run_id)
                        store.run_state(token.run_id, "running")
                        store.add_message(token.session_id, "user", run["question"])
                    if callable(actions):
                        actions = actions() or []
                    for action in actions:
                        token.check()
                        run_action(action)
                        if token.run_id:
                            tasks.step("action:" + action.get("type", "?"), action.get("text", action.get("name", "")), "done", "Действие завершено")
                            if action.get("type") == "say":
                                token.reply = action.get("text", "")
            except tasks.Cancelled:
                status = "failed" if token.error else "cancelled"
            except Exception as error:
                status = "failed"
                token.error = str(error)
                print(f"[action] цепочка упала: {error}")
            finally:
                if token.remote:
                    from shelter_core import remote_audio
                    remote_audio.finish(token, token.error or ("остановлено" if token.is_set() else ""))
                if token.run_id:
                    from shelter_core import assistant_store as store
                    if token.error:
                        status = "failed"
                    store.run_state(token.run_id, status, token.reply, token.error)
                    if token.reply:
                        store.add_message(token.session_id, "assistant", token.reply)
                    bus.publish("task", name=token.run_id, text=status)
                self._current = None
                self.current_label = ""
                if key is not None:
                    with self._lock:
                        self._active_keys.discard(key)

    def stop(self):
        with self._lock:
            self._closed = True
            if self._current:
                self._current.cancel()
            while not self._jobs.empty():
                try:
                    job = self._jobs.get_nowait()
                    if job is not self._stop and job[2][0]:
                        from shelter_core import assistant_store as store
                        store.run_state(job[2][0], "cancelled")
                    if job is not self._stop and len(job) > 4 and job[4]:
                        from shelter_core import remote_audio
                        remote_audio.finish_target(job[4], "остановлено")
                except queue.Empty:
                    break
            self._active_keys.clear()
            self._jobs.put_nowait(self._stop)
        self._thread.join(timeout=2.0)

    def cancel_current(self):
        with self._lock:
            if self._current:
                self._current.cancel()
            while not self._jobs.empty():
                try:
                    job = self._jobs.get_nowait()
                except queue.Empty:
                    break
                if job is self._stop:
                    self._jobs.put_nowait(job)
                    break
                if job[1] is not None:
                    self._active_keys.discard(job[1])
                if job[2][0]:
                    from shelter_core import assistant_store as store
                    store.run_state(job[2][0], "cancelled")
                if len(job) > 4 and job[4]:
                    from shelter_core import remote_audio
                    remote_audio.finish_target(job[4], "остановлено")


def _process_windows(process_name):
    """Найти видимые верхнеуровневые окна указанного exe."""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    hwnd_t = ctypes.c_void_p
    lparam_t = ctypes.c_ssize_t
    enum_proc_t = ctypes.WINFUNCTYPE(ctypes.c_bool, hwnd_t, lparam_t)

    user32.EnumWindows.argtypes = [enum_proc_t, lparam_t]
    user32.EnumWindows.restype = ctypes.c_bool
    user32.IsWindowVisible.argtypes = [hwnd_t]
    user32.IsWindowVisible.restype = ctypes.c_bool
    user32.GetWindowThreadProcessId.argtypes = [hwnd_t, ctypes.POINTER(ctypes.c_ulong)]
    user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
    kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_bool, ctypes.c_ulong]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.QueryFullProcessImageNameW.argtypes = [
        ctypes.c_void_p, ctypes.c_ulong, ctypes.c_wchar_p,
        ctypes.POINTER(ctypes.c_ulong),
    ]
    kernel32.QueryFullProcessImageNameW.restype = ctypes.c_bool
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]

    windows = []

    def enum_window(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        handle = kernel32.OpenProcess(0x1000, False, pid.value)
        if not handle:
            return True
        try:
            path = ctypes.create_unicode_buffer(32768)
            size = ctypes.c_ulong(len(path))
            if (kernel32.QueryFullProcessImageNameW(
                    handle, 0, path, ctypes.byref(size))
                    and os.path.basename(path.value).casefold()
                    == process_name.casefold()):
                windows.append(hwnd)
        finally:
            kernel32.CloseHandle(handle)
        return True

    callback = enum_proc_t(enum_window)
    user32.EnumWindows(callback, 0)
    return windows


def _send_linux_media(process_name, command):
    """MPRIS через playerctl — обычный способ управлять Spotify на Linux."""
    command_map = {
        "next": ["next"], "prev": ["previous"], "stop": ["stop"],
        "toggle": ["play-pause"], "play": ["play"], "pause": ["pause"],
        "mute": ["volume", "0"], "voldown": ["volume", "0.05-"],
        "volup": ["volume", "0.05+"],
    }
    player = os.path.splitext(os.path.basename(process_name))[0].casefold()
    try:
        subprocess.run(["playerctl", "--player", player, *command_map[command]],
                       check=True, capture_output=True, text=True, timeout=2)
    except FileNotFoundError as error:
        raise RuntimeError("для media на Linux установите playerctl") from error
    except subprocess.CalledProcessError as error:
        detail = error.stderr.strip() or "плеер не найден"
        raise RuntimeError(f"MPRIS-команда не выполнена: {detail}") from error


def _open_path(path):
    """Открыть файл или приложение средствами текущей ОС."""
    if IS_WINDOWS:
        os.startfile(path)
    elif (os.path.isfile(path) and os.access(path, os.X_OK)) or shutil.which(path):
        subprocess.Popen([path])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def _send_app_command(process_name, command):
    """Отправить WM_APPCOMMAND конкретному приложению, а не всей системе."""
    if not IS_WINDOWS:
        _send_linux_media(process_name, command)
        return
    windows = _process_windows(process_name)
    if not windows:
        raise RuntimeError(f"окно процесса {process_name} не найдено")

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    hwnd_t = ctypes.c_void_p
    lparam_t = ctypes.c_ssize_t
    wparam_t = ctypes.c_size_t
    user32.SendMessageTimeoutW.argtypes = [
        hwnd_t, ctypes.c_uint, wparam_t, lparam_t, ctypes.c_uint,
        ctypes.c_uint, ctypes.POINTER(ctypes.c_size_t),
    ]
    user32.SendMessageTimeoutW.restype = lparam_t

    # WM_APPCOMMAND: команда хранится в старшем слове lParam.
    result = ctypes.c_size_t()
    ok = user32.SendMessageTimeoutW(
        windows[0], 0x0319, windows[0], APP_COMMANDS[command] << 16,
        0x0002, 1500, ctypes.byref(result),
    )
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())


def _minimize_process(process_name):
    """Свернуть окна приложения, не закрывая его и не меняя воспроизведение."""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.ShowWindowAsync.argtypes = [ctypes.c_void_p, ctypes.c_int]
    user32.ShowWindowAsync.restype = ctypes.c_bool
    windows = _process_windows(process_name)
    for hwnd in windows:
        user32.ShowWindowAsync(hwnd, 6)  # SW_MINIMIZE
    return bool(windows)


def _focus_process(process_name, timeout):
    """Дождаться главного окна приложения и вывести его на передний план."""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.ShowWindowAsync.argtypes = [ctypes.c_void_p, ctypes.c_int]
    user32.ShowWindowAsync.restype = ctypes.c_bool
    user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
    user32.SetForegroundWindow.restype = ctypes.c_bool
    user32.BringWindowToTop.argtypes = [ctypes.c_void_p]
    user32.BringWindowToTop.restype = ctypes.c_bool
    user32.GetWindowTextLengthW.argtypes = [ctypes.c_void_p]
    user32.GetWindowTextLengthW.restype = ctypes.c_int

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        windows = _process_windows(process_name)
        if windows:
            # У игрового окна есть заголовок; служебные окна обычно без него.
            hwnd = max(windows, key=user32.GetWindowTextLengthW)
            user32.ShowWindowAsync(hwnd, 9)  # SW_RESTORE
            user32.BringWindowToTop(hwnd)
            if not user32.SetForegroundWindow(hwnd):
                # Windows разрешает смену foreground после краткого Alt-события.
                user32.keybd_event(0x12, 0, 0, 0)
                user32.SetForegroundWindow(hwnd)
                user32.keybd_event(0x12, 0, 2, 0)
            return True
        time.sleep(0.25)
    return False


def _riot_launch_request(product="valorant", patchline="live", timeout=4.0):
    """Повторить рабочий CMD-запрос через системный curl.exe."""
    with open(RIOT_LOCKFILE, encoding="utf-8") as file:
        name, _pid, port, secret, protocol = file.read().strip().split(":", 4)
    if name != "Riot Client":
        raise RuntimeError("неожиданный формат Riot lockfile")

    url = (f"{protocol}://127.0.0.1:{port}/product-launcher/v1/products/"
           f"{product}/patchlines/{patchline}")
    try:
        result = subprocess.run(
            [CURL, "--silent", "--show-error", "--insecure",
             "--ssl-auto-client-cert",
             "--user", f"riot:{secret}", "--request", "POST",
             "--output", "NUL", "--write-out", "%{http_code}",
             "--connect-timeout", "2", "--max-time", str(timeout), url],
            capture_output=True,
            text=True,
            timeout=timeout + 1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        raise OSError("curl не дождался локального Riot API") from None
    if result.returncode:
        detail = result.stderr.strip() or "без описания"
        raise OSError(f"curl завершился с кодом {result.returncode}: {detail}")
    try:
        return int(result.stdout.strip())
    except ValueError:
        raise OSError(f"curl вернул неожиданный HTTP-код: {result.stdout!r}") from None


def _launch_valorant(action):
    """Нажать Play тем же POST-запросом, что и рабочая CMD-команда."""
    product = action.get("product", "valorant")
    patchline = action.get("patchline", "live")
    timeout = float(action.get("timeout", 30))
    deadline = time.monotonic() + timeout
    client_started = False
    last_error = None
    _minimize_process(action.get("minimize", "Spotify.exe"))

    while time.monotonic() < deadline:
        try:
            status = _riot_launch_request(product, patchline)
            if 200 <= status < 300:
                print(f"[action] Riot принял запуск VALORANT (HTTP {status})")
                break
            # Riot отвечает 423, если игра уже запущена: это желаемый итог.
            if status == 423:
                print("[action] VALORANT уже запущен")
                break
            last_error = RuntimeError(f"Riot API вернул HTTP {status}")
        except (OSError, ValueError) as error:
            last_error = error

        if not client_started:
            client = action.get("path", RIOT_CLIENT)
            subprocess.Popen(
                [client],
                cwd=action.get("cwd") or os.path.dirname(client),
            )
            client_started = True
        time.sleep(0.5)
    else:
        detail = f": {last_error}" if last_error else ""
        raise RuntimeError(f"Riot Client не разрешил запуск за {timeout:g} с{detail}")

    focus_process = action.get("focus", "VALORANT-Win64-Shipping.exe")
    focus_timeout = float(action.get("focus_timeout", 60))
    if _focus_process(focus_process, focus_timeout):
        print("[action] окно VALORANT выведено на передний план")
    else:
        print(f"[action] окно {focus_process} не появилось за {focus_timeout:g} с")


def _hidden():
    """«Работай без окна»: ни HUD, ни персонажа — только голос и сигнал."""
    return ((_runtime_config or {}).get("ui") or {}).get("layout") == "hidden"


def overlay_alive():
    # Без окна разговор живёт столько же, сколько жило бы окно.
    if AVATAR.enabled or _hidden():
        return time.monotonic() < _avatar_until
    return _overlay_proc is not None and _overlay_proc.poll() is None


def hud_closed():
    global _overlay_proc
    if _overlay_proc is not None and _overlay_proc.poll() == 0:
        _overlay_proc = None
        return True
    return False


_last_state = {}


def _write_state(state):
    global _last_state
    _last_state = dict(state)
    os.makedirs(os.path.dirname(OVERLAY_STATE), exist_ok=True)
    with open(OVERLAY_STATE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)


def place_hud(monitor, position):
    """Переставить живое окно HUD: оно читает «place» из overlay.json."""
    if _last_state:
        _write_state({**_last_state, "place": {"monitor": int(monitor), "corner": str(position or "")}})


def dismiss():
    """«Исчезни, пропади»: убрать с экрана HUD или персонажа прямо сейчас."""
    close_hud()
    AVATAR.dismiss()


def appear():
    """«Появись»: показать снова (кроме режима «без окна»)."""
    if not _hidden():
        run_action({"type": "overlay", "seconds": 0, "text": "AWAITING ORDERS"})


def close_hud():
    """Закрыть окно HUD, не завершая разговор (смена персонажа)."""
    global _overlay_proc
    if _overlay_proc is not None and _overlay_proc.poll() is None:
        _overlay_proc.terminate()
    _overlay_proc = None


def close_overlay():
    """Закрыть окно. Вместе с ним снимается и режим приёма команд:
    интерфейс закрыт — значит без обращения ничего не принимается."""
    global _overlay_proc, _avatar_until
    from shelter_core import desktop_input
    desktop_input.clear_pending()
    if overlay_alive():
        if _overlay_proc is not None and _overlay_proc.poll() is None:
            _overlay_proc.terminate()
    _overlay_proc = None
    _avatar_until = 0.0
    AVATAR.trigger("idle")
    AVATAR.hide()
    LISTENING.clear()


def _show_overlay(action):
    # Отдельным процессом: tkinter не любит неглавный поток, а ронять
    # детектор из-за окошка нельзя.
    global _overlay_proc, _avatar_until
    if _hidden():
        seconds = float(action.get("seconds", 8))
        _avatar_until = float("inf") if seconds <= 0 else time.monotonic() + seconds
        return
    if AVATAR.enabled:
        AVATAR.start()
        seconds = float(action.get("seconds", 8))
        _avatar_until = float("inf") if seconds <= 0 else time.monotonic() + seconds
        label = str(action.get("text", ""))
        busy = label not in ("", "AWAITING ORDERS", "STANDING BY") and not label.startswith(("CONFIRM", "REMINDER", "DAILY"))
        AVATAR.trigger("thinking" if busy else "listening")
        return
    os.makedirs(os.path.dirname(OVERLAY_STATE), exist_ok=True)
    ui = (_runtime_config or {}).get("ui") or {}
    _write_state({"label": action.get("text", "STANDING BY"), "seconds": float(action.get("seconds", 8)),
                  "place": {"monitor": int(ui.get("monitor", 0) or 0), "corner": str(ui.get("position", "") or "")}})

    # Живое окно подхватит новое состояние само. Перезапуск процесса дал бы
    # заметное мигание: старт Python занимает доли секунды.
    if overlay_alive():
        return

    common = ["--seconds", str(action.get("seconds", 8)),
              "--label", action.get("text", "STANDING BY")]
    # Место окна задают только явно: иначе HUD сам решает — большое окно,
    # другой монитор или кругляш в углу (ui.layout).
    if action.get("pos") or ui.get("position"):
        common += ["--pos", action.get("pos") or str(ui["position"])]
    if os.path.exists(HUD_EXE) and ui.get("hud", "rust") != "python":
        command = [HUD_EXE, *common, "--root", ROOT, "--fps", str(int(ui.get("fps", 30))),
                   "--monitor", str(int(ui.get("monitor", 0) or 0)),
                   "--layout", str(ui.get("layout", "auto")),
                   "--busy", str(ui.get("busy", "orb")),
                   "--corner", str(ui.get("corner", "bottom-right"))]
        if ui.get("busy_apps"):
            command += ["--busy-apps", ",".join(str(a) for a in ui["busy_apps"])]
    else:
        command = [sys.executable, "-m", "shelter_core.overlay", *common]
    env = dict(os.environ, JARVIS_MARKETS="1" if ui.get("markets", False) else "0")
    if not ui.get("markets", False):
        env["JARVIS_HUD_OFF"] = ",".join(filter(None, [env.get("JARVIS_HUD_OFF", ""), "coins"]))
    _overlay_proc = subprocess.Popen(command, env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))




class ScenarioFailed(RuntimeError):
    pass


def _run_scenario(action):
    """Сценарий целиком — общим исполнителем; ошибка шага не становится «готово»."""
    from shelter_core import scenarios
    item = scenarios.get(action.get("id", ""))
    if item is None:
        raise RuntimeError("сценарий удалён или выключен")
    result = scenarios.execute(item, source=action.get("source", "голос"), run_id=action.get("run"))
    if result["status"] == "cancelled":
        raise tasks.Cancelled()
    if result["status"] == "failed":
        AVATAR.trigger("error")                # огорчение на лице — понятно без слов
        if action.get("speak_errors", True):
            persona = (_runtime_config or {}).get("persona") or {}
            reason = result["error"].split(": ", 1)[-1]
            voice.speak_stream([f"Не получилось, {persona.get('address', 'сэр')}: {reason}."])
        tasks.fail(result["error"])
        raise ScenarioFailed(result["error"])
    if result["status"] == "skipped":
        print(f"[scenario] {item['name']}: {result['error']}")


def run_action(action):
    kind = action.get("type")
    try:
        tasks.check()
        capability = {"launch": "app", "url": "app", "app": "app", "riot": "app", "media": "media"}.get(kind)
        if capability:
            policy.require(_runtime_config, capability)
        if kind == "ask":
            # Принятое предложение «найти/узнать» — обычный вопрос ассистенту:
            # результат поиска или погоду надо пересказать, а не выполнить молча.
            if _ask_handler is None:
                raise RuntimeError("ассистент ещё не готов")
            for nested in _ask_handler(action["text"]) or []:
                run_action(nested)
            return
        if kind == "tool":
            if _tool_handler is None:
                raise RuntimeError("исполнитель инструментов ещё не готов")
            outcome, reply = _tool_handler(action["name"], action.get("arg", ""), action.get("confirmed", False))
            if reply and outcome in ("say", "fail"):
                voice.speak_stream([reply])
            return
        if kind == "say":
            AVATAR.trigger("speaking")
            if action.get("ack"):
                voice.ACK.set()
            try:
                voice.say(action["text"], action.get("file"))
            finally:
                if voice.ACK.is_set():
                    voice.ACK_AT = time.monotonic()
                voice.ACK.clear()
                AVATAR.trigger("idle")
        elif kind == "overlay":
            _show_overlay(action)
        elif kind == "avatar":
            from shelter_core import avatar_motion
            avatar_motion.perform(_runtime_config or {}, action.get("animation", "wave"),
                                  action.get("bpm"), action.get("beat", False))
        elif kind == "close":
            close_overlay()
        elif kind == "app":
            # Приложения из Microsoft Store не запускаются по пути к exe —
            # только через их идентификатор в shell:appsFolder.
            if not IS_WINDOWS:
                raise RuntimeError("type: app — это Windows Store; на Linux используйте type: launch")
            subprocess.Popen(["explorer.exe", "shell:appsFolder\\" + action["id"]])
        elif kind == "settings":
            # Под приложением «Джарвис» — его окно (второй запуск exe просто
            # показывает уже открытое); без него — старое окно настроек.
            app_exe = os.environ.get("JARVIS_APP_EXE", "")
            if app_exe and os.path.exists(app_exe):
                subprocess.Popen([app_exe])
            else:
                subprocess.Popen([sys.executable, "-m", "shelter_core.settings"],
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        elif kind == "launch":
            args = action.get("args")
            if args:
                # Рабочая папка обязательна: Riot Client из чужого каталога
                # свои --launch-* игнорирует.
                subprocess.Popen([action["path"], *args],
                                 cwd=action.get("cwd") or os.path.dirname(action["path"]))
            else:
                _open_path(action["path"])
        elif kind == "url":
            webbrowser.open(action["url"])
        elif kind == "media":
            time.sleep(float(action.get("delay", 0)))
            command = action.get("key", "play")
            try:
                _send_app_command(action.get("process", "Spotify.exe"), command)
            except RuntimeError as error:
                # Нужного плеера нет — управлять тем, что играет сейчас (браузер,
                # Яндекс Музыка…), через системные медиа-сессии Windows.
                from shelter_core import media
                system = {"prev": "previous", "toggle": "toggle", "play": "play", "pause": "pause",
                          "next": "next", "stop": "stop"}.get(command)
                if not (system and media.control(system)):
                    print(f"[action] media: {error}; системный плеер тоже не ответил")
        elif kind == "riot":
            _launch_valorant(action)
        elif kind == "profile":
            name = action.get("name")
            profile = _profiles.get(name)
            if not profile:
                raise RuntimeError(f"профиль {name!r} не найден")
            if profile.get("confirm") and not action.get("confirmed"):
                voice.inject({"confirm": profile["confirm"], "actions": [{"type": "profile", "name": name, "confirmed": True}]}, "профиль " + name)
                return
            print(f"[profile] {profile.get('label', name)}")
            for nested in profile.get("actions") or []:
                if nested.get("type") == "profile":
                    raise RuntimeError("профили нельзя вкладывать друг в друга")
                run_action(nested)
        elif kind == "scenario":
            _run_scenario(action)
        elif kind == "plugin":
            _run_plugin(action)
        elif kind == "shell":
            if not _allow_shell:
                raise RuntimeError("shell-действия отключены в security.allow_shell")
            subprocess.Popen(action["cmd"], shell=True)
        else:
            raise ValueError(f"Неизвестный тип действия: {kind}")
    except tasks.Cancelled:
        raise
    except ScenarioFailed:
        raise                         # причину уже показал исполнитель сценариев
    except Exception as e:
        # Упавшее действие не должно ронять ассистента.
        print(f"[action] {kind} упало: {e}")
        from shelter_core import bus
        bus.publish("error", text=f"Действие {kind} не выполнено: {e}")
        if kind not in ("overlay", "close"):
            raise RuntimeError(f"Не выполнено действие {kind}") from e
