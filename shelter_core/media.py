"""Что играет и управление любым плеером — через медиасессии Windows (GSMTC).

Это тот же механизм, что у всплывающей панели громкости Windows: видны
Spotify, Яндекс Музыка, браузеры (YouTube, ВК), VLC, Windows Media Player —
все, кто сообщает системе о воспроизведении. Ключи и API сервисов не нужны.

Пакет: winrt-Windows.Media.Control. Нет его — функции просто возвращают None.
"""

import asyncio
import re
import os
import subprocess
import time
import threading
from shelter_core import native_runtime


def _playerctl(*args):
    try:
        result = subprocess.run(["playerctl", *args], capture_output=True, text=True, timeout=3)
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None

PLAYING, PAUSED = 4, 5

_APP_NAMES = {"spotify": "Spotify", "firefox": "Firefox", "chrome": "Chrome", "msedge": "Edge",
              "yandex": "Яндекс", "browser": "Яндекс Браузер", "opera": "Opera", "vlc": "VLC",
              "zunemusic": "проигрыватель Windows", "telegram": "Telegram", "aimp": "AIMP",
              "foobar2000": "foobar2000", "308046b0af4a39cb": "Firefox"}
_BROWSER_IDS = {"firefox": ("firefox", "308046b0af4a39cb"), "chrome": ("chrome", "chromium"),
                "chromium": ("chromium", "chrome"), "msedge": ("msedge", "microsoftedge"),
                "opera": ("opera",), "brave": ("brave",), "vivaldi": ("vivaldi",),
                "yandex": ("yandex", "browser.exe"), "browser": ("yandex", "browser.exe")}
_BROWSERS = tuple({marker for items in _BROWSER_IDS.values() for marker in items})
_MUSIC = ("spotify", "zunemusic", "aimp", "foobar2000", "music.yandex", "yandexmusic", "rhythmbox", "clementine", "strawberry", "audacious")
_cache_lock = threading.Lock()
_cache = (0., [])


def _classify(item):
    source = item.get("source", "").lower()
    item = dict(item)
    item["app"] = next((name for key,name in _APP_NAMES.items() if key in source), source.split("!")[0] or "плеер")
    # Browsers often mark ALL YouTube videos as Music. Their metadata alone
    # cannot establish whether the content is a song; never infer it from artist.
    if any(name in source for name in _BROWSERS):
        item["kind"] = "video" if item.get("kind") == "video" else "unknown"
    elif any(name in source for name in _MUSIC):
        item["kind"] = "music"
    return item


def _select(items, music_only=False, source=None):
    items = [_classify(i) for i in items]
    if source is not None: items = [i for i in items if i.get("source") == source]
    if music_only: items = [i for i in items if i.get("kind") == "music"]
    return min(items,key=lambda i:(not i.get("playing"),not i.get("current")),default=None)


def _native_sessions():
    global _cache
    with _cache_lock:
        if time.monotonic()-_cache[0] < .75: return _cache[1]
        items = native_runtime.media_sessions()
        if items is not None: _cache = time.monotonic(),items
        return items


def _manager():
    from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as M
    return M


def _app(session):
    raw = (session.source_app_user_model_id or "").lower()
    for key, name in _APP_NAMES.items():
        if key in raw:
            return name
    raw = re.split(r"[!_]", raw)[0]
    return raw.removesuffix(".exe") or "плеер"


async def _sessions():
    manager = await _manager().request_async()
    sessions = list(manager.get_sessions())
    current = manager.get_current_session()
    # Играющая сессия важнее «текущей»: Windows помнит последнюю тронутую, даже на паузе.
    sessions.sort(key=lambda s: (int(s.get_playback_info().playback_status) != PLAYING,
                                 not (current and s.source_app_user_model_id == current.source_app_user_model_id)))
    return sessions


async def _now(music_only=False):
    return _select(await _windows_sessions(), music_only)


async def _windows_sessions():
    sessions = await _sessions()
    if not sessions:
        return []
    items = []
    for session in sessions:
        try:
            props = await session.try_get_media_properties_async()
            kind = getattr(props,"playback_type",None)
            kind = getattr(kind,"value",kind)
            info = session.get_playback_info()
            controls = info.controls
            items.append({"source":session.source_app_user_model_id,"title":props.title or "", "artist":props.artist or "",
                          "kind":{1:"music",2:"video"}.get(kind,"unknown"),
                          "next_enabled": bool(controls.is_next_enabled), "previous_enabled": bool(controls.is_previous_enabled),
                          "playing":int(info.playback_status)==PLAYING})
        except Exception:
            continue
    return items


def _run(coroutine):
    try:
        return asyncio.run(coroutine)
    except Exception as error:
        print(f"[media] {error}")
        return None


def now_playing(music_only=False):
    """{'app', 'title', 'artist', 'playing'} или None, если ничего нет."""
    if os.name != "nt":
        status = _playerctl("status")
        if not status:
            return None
        item = {"source": _playerctl("metadata", "--format", "{{playerName}}") or "плеер",
                "title": _playerctl("metadata", "title") or "", "artist": _playerctl("metadata", "artist") or "",
                "kind":"unknown","playing": status.lower() == "playing"}
        return _select([item],music_only)
    items = _native_sessions()
    if items is not None: return _select(items,music_only)
    try:
        _manager()
    except ImportError:
        return None
    return _run(_now(music_only))


def playing():
    """Играет ли сейчас что-нибудь (для команд без имени: «пауза», «дальше»)."""
    info = now_playing()
    return bool(info and info["playing"])


def _browser_session():
    if os.name == "nt":
        from shelter_core.gaming import _foreground_process
        name = _foreground_process()
        items = _native_sessions()
        if items is None:
            try:
                _manager()
            except ImportError:
                return None
            items = _run(_windows_sessions()) or []
    else:
        from shelter_core.desktop_linux import foreground
        name = (foreground() or {}).get("process", "")
        items = [{"source": player, "title": _playerctl("--player", player, "metadata", "title") or ""}
                 for player in (_playerctl("-l") or "").splitlines()]
    markers = _BROWSER_IDS.get(name.lower().removesuffix(".exe"), ())
    hits = [item for item in items if any(marker in item["source"].lower() for marker in markers)]
    return hits[0] if len(hits) == 1 else None


def next_episode():
    """Request Next only from an unambiguous media session of the foreground browser."""
    from shelter_core import tasks
    session = _browser_session()
    if not session:
        return "fail", "Откройте плеер в активном окне браузера. Подходящая медиасессия не найдена."
    if session.get("next_enabled") is False:
        return "fail", "Этот плеер не передаёт браузеру команду «Следующая серия»."
    tasks.check()
    if not control("next", source=session["source"]):
        return "fail", "Плеер не принял переход. На этом сайте может понадобиться выбрать серию вручную."
    before = (session.get("title"), session.get("artist"))
    until = time.monotonic() + 1.8
    while time.monotonic() < until:
        tasks.check()
        current = _browser_session()
        if current and current["source"] == session["source"] and current.get("title") and (
            current.get("title"), current.get("artist")
        ) != before:
            return "done", "Плеер переключился на следующий элемент."
        time.sleep(0.15)
    return "fail", "Плеер принял команду, но не подтвердил смену видео. Проверьте серию в браузере."


def describe():
    """Фраза для ответа на «что играет»."""
    info = now_playing()
    if not info or not (info["title"] or info["artist"]):
        return "Сейчас ничего не играет, сэр."
    track = " — ".join(part for part in (info["artist"], info["title"]) if part)
    state = "играет" if info["playing"] else "на паузе"
    return f"В {info['app']} {state}: {track}."


async def _control(action, source=None):
    sessions = await _sessions()
    if not sessions:
        return False
    session = next((s for s in sessions if source is None or s.source_app_user_model_id == source),None)
    if session is None: return False
    method = {"pause": session.try_pause_async, "play": session.try_play_async,
              "toggle": session.try_toggle_play_pause_async, "next": session.try_skip_next_async,
              "previous": session.try_skip_previous_async, "stop": session.try_stop_async}[action]
    return bool(await method())


def volume(step):
    """Общая громкость: step > 0 — громче, < 0 — тише; один шаг Windows — 2%."""
    if os.name != "nt":
        return _playerctl("volume", f"{abs(step) * 0.02:.2f}{'+' if step > 0 else '-'}")
    import ctypes
    key = 0xAF if step > 0 else 0xAE          # VK_VOLUME_UP / VK_VOLUME_DOWN
    for _ in range(abs(int(step))):
        ctypes.windll.user32.keybd_event(key, 0, 0, 0)
        ctypes.windll.user32.keybd_event(key, 0, 2, 0)


def _media_key():
    """Системная медиаклавиша Play/Pause — последний запасной путь."""
    if os.name == "nt":
        import ctypes
        ctypes.windll.user32.keybd_event(0xB3, 0, 0, 0)        # VK_MEDIA_PLAY_PAUSE
        ctypes.windll.user32.keybd_event(0xB3, 0, 2, 0)


def ensure(action, checks=4):
    """Пауза/продолжение с проверкой: браузер иногда принимает команду, но не
    выполняет её (например, когда сразу за ней приходит Esc из полноэкранного
    режима). Не встало — повторить переключателем, потом медиаклавишей."""
    want_playing = action == "play"
    if now_playing() is None:
        return False                      # ни одного плеера — честно сказать
    control(action)                       # отказ не страшен: ниже проверяем по факту
    import time
    for attempt in range(3):
        for _check in range(checks):                       # ~0.6 с на каждую попытку
            info = now_playing()
            if not info or info["playing"] == want_playing:
                return True
            time.sleep(0.15)
        if attempt == 0:
            control("toggle")
        elif attempt == 1:
            _media_key()
    info = now_playing()
    return not info or info["playing"] == want_playing


def control(action, source=None):
    """pause | play | toggle | next | previous | stop. True — плеер выполнил."""
    if os.name != "nt":
        if action not in ("pause", "play", "toggle", "next", "previous", "stop"):
            return False
        return _playerctl(*(["--player",source] if source else []),"play-pause" if action == "toggle" else action) is not None
    if source is None:
        info = now_playing()
        source = info.get("source") if info else None
    if source:
        result = native_runtime.media_control(action,source)
        if result is not None:
            global _cache
            _cache = (0.,[])
            return result
    try:
        _manager()
    except ImportError:
        return False
    return bool(_run(_control(action, source)))
