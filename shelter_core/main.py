from shelter_core.paths import ROOT_DIR

from shelter_core import netfix  # noqa: F401 — локальное мимо системного прокси
import argparse
import sys
import re
import os
import queue
import threading
import time

import numpy as np
import sounddevice as sd
import yaml
from shelter_core import tasks
from shelter_core import policy
from shelter_core import secrets_store
import copy
import json
from shelter_core.policy import CONFIRMATIONS

detector = None          # Legacy sound trigger is loaded only when explicitly enabled.
from shelter_core import llm
from shelter_core import fastpath
from shelter_core import gaming
from shelter_core import media
from shelter_core import memory
from shelter_core import neural
from shelter_core import obs
from shelter_core import pc
from shelter_core import scheduler
from shelter_core import smarthome
from shelter_core import tools
from shelter_core import voice
from shelter_core.actions import (ActionRunner, close_overlay, configure as configure_actions,
                     overlay_alive, run_action)
from shelter_core.audio import LISTENING, THINKING, AudioCapture
from shelter_core.companion import CompanionServer
from shelter_core.control import ControlServer
from shelter_core import browser_episode
from shelter_core import automation_intent
from shelter_core import bus


CONFIG_PATH = "config.yaml"
# Так лаунчер (bin/jarvis.exe) просит завершиться аккуратно: с остановкой
# голосового сервера и закрытием окна, а не обрывом процесса.
STOP_REQUEST = os.path.join(ROOT_DIR, "logs", "stop.request")
TEST_RATES = [16000, 32000, 44100, 48000]
BAR_WIDTH = 30


SETTINGS_PATH = os.path.join(ROOT_DIR, "data", "settings.json")


def _merge(base, extra):
    """Наложить пользовательские настройки на конфиг: словари — вглубь, остальное — заменой."""
    if not isinstance(extra, dict):
        raise ValueError("настройки должны быть JSON-объектом")
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value
    return base


def load_config(path=CONFIG_PATH):
    """config.yaml — значения по умолчанию (с комментариями, для продвинутых);
    data/settings.json — то, что человек выставил в приложении «Джарвис»."""
    if path == CONFIG_PATH and not os.path.isfile(path):
        path = os.path.join(ROOT_DIR, "config.public.yaml")
    with open(path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    try:
        import json
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            candidate = _merge(copy.deepcopy(config), secrets_store.decode(json.load(f)))
            validate_config(candidate)
            config = candidate
    except FileNotFoundError:
        pass
    except (ValueError, TypeError) as error:
        print(f">> SETTINGS  //  data/settings.json повреждён ({error}) — беру config.yaml")
        try:
            with open(SETTINGS_PATH + ".bak", encoding="utf-8") as f:
                candidate = _merge(copy.deepcopy(config), secrets_store.decode(json.load(f)))
                validate_config(candidate)
                config = candidate
        except (OSError, ValueError, TypeError):
            pass
    return validate_config(config)


def validate_config(config):
    """Дать понятную ошибку в конфиге до запуска потоков и микрофона."""
    if not isinstance(config, dict):
        raise ValueError("корень config.yaml должен быть YAML-словарём")
    config.setdefault("detector", {"enabled": False})
    for section in ("audio", "detector", "wake"):
        if not isinstance(config.get(section), dict):
            raise ValueError(f"config.yaml: нужен раздел {section}")
    for section in ("tts", "llm", "ui", "security", "smarthome", "confirm", "asr", "control", "gaming", "integrations", "performance"):
        if section in config and not isinstance(config[section], dict):
            raise ValueError(f"config.yaml: раздел {section} должен быть словарём")
    words = config["wake"].get("words", [])
    if not isinstance(words, list) or not words or not all(isinstance(w, str) and w.strip() for w in words):
        raise ValueError("wake.words: нужно хотя бы одно непустое слово-обращение")
    if not isinstance(config.get("commands", []), list):
        raise ValueError("config.yaml: commands должен быть списком")
    for command in config.get("commands", []):
        if not isinstance(command, dict) or not isinstance(command.get("actions", []), list):
            raise ValueError("commands: нужны объекты со списком actions")
        if not all(isinstance(a, dict) and isinstance(a.get("type"), str) for a in command.get("actions", [])):
            raise ValueError("commands.actions: у каждого действия должен быть type")
    if not isinstance(config.get("profiles", {}), dict):
        raise ValueError("config.yaml: profiles должен быть словарём")
    if not isinstance(config.get("companion", {}), dict):
        raise ValueError("config.yaml: companion должен быть словарём")
    sample_rate = int(config["audio"].get("sample_rate", 0))
    if sample_rate <= 0:
        raise ValueError("config.yaml: audio.sample_rate должен быть положительным")
    for name, profile in config.get("profiles", {}).items():
        if not isinstance(profile, dict) or not isinstance(profile.get("actions", []), list):
            raise ValueError(f"config.yaml: профиль {name!r} должен содержать список actions")
    companion = config.get("companion") or {}
    port = int(companion.get("port", 8765))
    if not 0 <= port <= 65535:
        raise ValueError("config.yaml: companion.port вне диапазона 0..65535")
    agent = (config.get("llm") or {}).get("agent", {})
    if not isinstance(agent, dict) or agent.get("protocol", "auto") not in ("auto", "native", "tags"):
        raise ValueError("llm.agent.protocol: auto, native или tags")
    if not 1 <= int(agent.get("max_steps", 6)) <= 12:
        raise ValueError("llm.agent.max_steps: от 1 до 12")
    if not 2048 <= int((config.get("llm") or {}).get("context", 8192)) <= 262144:
        raise ValueError("llm.context: от 2048 до 262144")
    from shelter_core import llm_connections
    llm_connections.validate(config.get('llm') or {})
    memory_options=(config.get('llm') or {}).get('memory') or {}
    if not isinstance(memory_options,dict) or not 2 <= int(memory_options.get('recent_turns',6)) <= 20:
        raise ValueError('llm.memory.recent_turns: от 2 до 20')
    if not 0 <= int((config.get("tts") or {}).get("reply_sentences", 3)) <= 20:
        raise ValueError("tts.reply_sentences: от 0 до 20")
    servers = (config.get("integrations") or {}).get("servers", [])
    if not isinstance(servers, list) or len(servers) > 16:
        raise ValueError("integrations.servers: список до 16 подключений")
    ids = set()
    for server in servers:
        if not isinstance(server, dict) or not isinstance(server.get("id"), str) or server["id"] in ids:
            raise ValueError("У подключения MCP должно быть уникальное имя id")
        ids.add(server["id"])
        if server.get("transport", "stdio") not in ("stdio", "http"):
            raise ValueError("MCP transport: stdio или http")
        for key in ("tools", "trusted_tools", "args"):
            if not isinstance(server.get(key, []), list) or not all(isinstance(s, str) for s in server.get(key, [])):
                raise ValueError("MCP " + key + ": список строк")
    return config


def to_db(level):
    return 20.0 * np.log10(level + 1e-9)


def bar(level, width=BAR_WIDTH):
    """Индикатор по шкале дБ (-60..0), в линейной шкале всё жмётся к нулю."""
    filled = int(round((to_db(level) + 60.0) / 60.0 * width))
    filled = max(0, min(width, filled))
    return "#" * filled + "-" * (width - filled)


def list_devices():
    hostapis = sd.query_hostapis()
    default_in = sd.default.device[0]
    for i, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] < 1:
            continue
        rates = []
        for rate in TEST_RATES:
            try:
                sd.check_input_settings(device=i, samplerate=rate, channels=1, dtype="float32")
                rates.append(str(rate))
            except Exception:
                pass
        mark = " (по умолчанию)" if i == default_in else ""
        print(f"[{i:2d}] {dev['name']}{mark}")
        print(f"     API: {hostapis[dev['hostapi']]['name']}, "
              f"каналов: {dev['max_input_channels']}, "
              f"своя частота: {int(dev['default_samplerate'])} Гц")
        print(f"     поддерживает: {', '.join(rates) if rates else '—'}")


def open_capture(config):
    audio_cfg = config.get("audio") or {}
    cap = AudioCapture(sample_rate=int(audio_cfg.get("sample_rate", 32000)),
                       device={"name": audio_cfg["device_name"]} if audio_cfg.get("device_name") else audio_cfg.get("device"),
                       detector_enabled=bool((config.get("detector") or {}).get("enabled", False)))
    try:
        cap.start()
    except (sd.PortAudioError, ValueError):
        if cap.device is None:
            raise
        bus.publish("error", text="Выбранный микрофон недоступен. Использую устройство по умолчанию.")
        cap.device = None
        cap.start()
    dev = sd.query_devices(cap.stream.device, "input")
    print(f">> AUDIO LINK  //  [{cap.stream.device}] {dev['name']}  "
          f"{int(cap.stream.samplerate)} Hz")
    if audio_cfg.get("echo_cancel"):
        enable_echo(cap)
    return cap


def enable_echo(cap):
    """«Пользуюсь колонками»: вычитать из микрофона то, что играет компьютер."""
    from shelter_core import echo
    if not echo.available():
        print(">> ECHO CANCEL  //  не установлено — мастер: компонент «Колонки»")
        return
    try:
        cap.echo = echo.Canceller(int(cap.sample_rate))
        print(">> ECHO CANCEL  //  ON (WebRTC AEC3)")
    except Exception as error:
        print(f">> ECHO CANCEL  //  недоступно: {error}")
        bus.publish("error", text=f"Подавление эха не включилось: {error}")


def watch_capture(cap, config, events, stop):
    while not stop.wait(2):
        if time.monotonic() - cap.last_block < 5:
            continue
        WORKERS["microphone"] = {"state": "error", "error": "Микрофон отключён, переподключаю"}
        bus.publish("error", text="Потерян микрофон. Пробую подключить устройство по умолчанию.")
        try:
            cap.stop()
            cap.device = None
            cap.start()
            WORKERS["microphone"] = {"state": "running", "error": ""}
        except Exception as error:
            WORKERS["microphone"] = {"state": "error", "error": str(error)}


def meter(config):
    """Проверка микрофона: уровень в консоли."""
    cap = open_capture(config)
    print("Ctrl+C — выход.\n")
    peak_hold = 0.0
    try:
        while True:
            time.sleep(0.2)
            for q in (cap.vosk_queue, cap.det_queue):
                while not q.empty():
                    q.get_nowait()
            w = cap.get_window(0.0, 0.2)
            if w.size == 0:
                continue
            rms = float(np.sqrt(np.mean(w ** 2)))
            peak = float(np.max(np.abs(w)))
            peak_hold = max(peak_hold, peak)
            warn = "  КЛИППИНГ" if peak >= 0.99 else ""
            line = (f"RMS {rms:6.4f} ({to_db(rms):6.1f} дБ)  "
                    f"пик {peak:6.4f}  макс {peak_hold:6.4f}  [{bar(rms)}]{warn}")
            print("\r" + line.ljust(90), end="", flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        cap.stop()
        print(f"\n\nМаксимальный пик: {peak_hold:.4f}")
        print(f"Переполнений входа: {cap.overflows}, дропнуто блоков: {cap.dropped}")


def all_action_lists(config):
    lists = [(config.get("wake") or {}).get("actions") or []]
    lists += list((config.get("triggers") or {}).values())
    lists += [cmd.get("actions") or [] for cmd in config.get("commands") or []]
    lists += [profile.get("actions") or []
              for profile in (config.get("profiles") or {}).values()]
    return lists


def all_texts(config):
    """Фразы для синтеза. У кого свой файл — тому silero не нужен."""
    engine = (config.get("tts") or {}).get("engine", "files")
    return [a["text"] for actions in all_action_lists(config) for a in actions
            if a.get("type") == "say" and (engine == "silero" or not a.get("file"))]


def _wake_label(config):
    for action in (config.get("wake") or {}).get("actions") or []:
        if action.get("type") == "overlay":
            return action.get("text", "AWAITING ORDERS")
    return "AWAITING ORDERS"


RUNNER = None           # исполнитель действий — для статуса «выполняю …» в окне
_events = None          # очередь главного цикла — туда приходят сработавшие таймеры
WORKERS = {}
question_now = {"text": ""}   # вопрос, на который сейчас отвечаем (инструментам бывает нужен)

TOOL_LABELS = {"app": "LAUNCHING", "weather": "WEATHER UPLINK", "search": "WEB SEARCH",
               "home": "SMART HOME", "timer": "TIMER SET",
               "remember": "MEMORY UPDATED", "forget": "MEMORY ERASED",
               "nowplaying": "NOW PLAYING", "obs": "OBS LINK"}


def handle_quick(action):
    """Команда без имени: «пауза», «дальше», «громче». Только если что-то играет —
    иначе это, скорее всего, разговор в голосовом чате, а не просьба к Джарвису."""
    info = media.now_playing()
    if action == "play":
        if info and not info["playing"]:
            media.control("play")
        return
    if not (info and info["playing"]):
        return
    if action in ("louder", "quieter"):
        media.volume(5 if action == "louder" else -5)     # ±10 %
    else:
        media.control(action)


def _offer(config, arg):
    """«Хочется музыки» -> модель предлагает действие; «да» его выполнит.

    Само предложение ничего не делает: действие ждёт подтверждения, а разговор
    остаётся открытым, чтобы ответить можно было без «Джарвис»."""
    from shelter_core import llm
    kind, value = llm.parse_tag(arg.strip().strip("[]"))
    commands = config.get("commands") or []
    if kind == "command":
        if not (1 <= value <= len(commands) and (config.get("llm") or {}).get("commands", True)):
            return "fail", "Не понял, что предложить, сэр."
        actions = [{"type": "tool", "name": "scenario", "arg": str(value), "confirmed": True}]
    else:
        tool, tool_arg = value
        if tool == "offer" or not policy.allowed(config, tool):
            return "fail", "Эта возможность выключена в настройках, сэр."
        if tool in llm.INFO_TOOLS:
            # Поиск, погода, экран: результат нужно пересказать — это вопрос ассистенту.
            question = {"weather": "какая погода " + tool_arg, "screen": "что на экране",
                        "clipboard": "что в буфере обмена"}.get(tool, tool_arg) or tool_arg
            actions = [{"type": "ask", "text": question.strip()}]
        else:
            actions = [{"type": "tool", "name": tool, "arg": tool_arg, "confirmed": True},
                       {"type": "say", "text": "Готово, сэр."}]
    CONFIRMATIONS.request({"offer": True, "description": "предложение: " + arg.strip(), "actions": actions},
                          float((config.get("confirm") or {}).get("timeout", 20)))
    tasks.continue_dialogue()                 # ответ «да» — без повторного «Джарвис»
    return "done", "Жду ответа"


def run_tool(config, name, arg, confirmed=False):
    bus.publish("tool_start", name=name)
    try:
        outcome, result = _run_tool(config, name, arg, confirmed)
    except tasks.Cancelled:
        tasks.step(name, arg, "cancelled", "Действие отменено; состояние могло измениться")
        raise
    except Exception as error:
        tasks.step(name, arg, "fail", str(error))
        raise
    tasks.step(name, arg, outcome, result)
    return outcome, result


def _run_tool(config, name, arg, confirmed=False):
    """Инструмент по тегу модели -> (исход, текст), см. llm.respond."""
    tasks.check()
    if name == "scenario":
        commands = config.get("commands") or []
        if not (config.get("llm") or {}).get("commands", True) or not arg.isdigit() or not 1 <= int(arg) <= len(commands):
            return "fail", "Сценарий недоступен"
        command = commands[int(arg) - 1]
        if command.get("confirm") and not confirmed:
            CONFIRMATIONS.request(command)
            return "say", str(command["confirm"])
        if command.get("scenario"):
            # Сценарий — общим исполнителем: проверка шагов, отмена, честная ошибка.
            run_action({"type": "scenario", "id": command["scenario"], "source": "нейросеть", "speak_errors": False})
            return "done", "Сценарий завершён"
        for action in command.get("actions") or []:
            tasks.check()
            run_action(action)
        return "done", "Сценарий завершён"
    if not policy.allowed(config, name):
        return "fail", "Эта возможность выключена в настройках, сэр."
    if not isinstance(arg, str) or len(arg) > (16000 if name in ("mcp","desktop","type") else 2000):
        return "fail", "Некорректные параметры действия, сэр."
    if name == "browser_episode" and arg == "next":
        return media.next_episode()
    if name == "desktop":
        from shelter_core import desktop_input
        try:
            command=json.loads(arg)
            if not isinstance(command,dict):raise ValueError("Некорректное действие ввода")
        except (ValueError,TypeError):return "fail","Некорректное действие ввода"
        return desktop_input.execute(command,config)
    if name == "offer":
        return _offer(config, arg)
    if name == "display":
        from shelter_core import display
        kind, _, rest = (p.strip() for p in arg.partition("|"))
        if kind in ("dismiss", "appear"):
            from shelter_core import actions
            actions.dismiss() if kind == "dismiss" else actions.appear()
            if kind == "dismiss":
                tasks.end_dialogue()
            return "done", ""
        if kind == "mode" and rest in ("auto", "full", "orb", "hidden"):
            display.set_mode(config, rest)
            return "done", ""
        if kind == "move":
            monitor, _, position = (p.strip() for p in rest.partition("|"))
            if monitor.isdigit() and position in ("", "center", "left", "right", "top-left", "top-right",
                                                   "bottom-left", "bottom-right"):
                return "done", display.move(config, int(monitor), position)
        return "fail", "Не понял, как показываться, сэр."
    if name == "persona":
        from shelter_core import personas
        target = personas.get(arg.strip())
        if not target:
            return "fail", "Такого персонажа нет. Выберите имя в разделе «Персонаж»."
        return "done", switch_persona(config, target["id"])
    if name == "avatar":
        from shelter_core import avatar_motion
        try:
            return "done", avatar_motion.execute(config, arg)
        except (ValueError, TypeError) as error:
            return "fail", str(error)
    risky = name == "pc" and pc.parse(arg.partition("|")[0]) in ("shutdown", "restart", "sleep", "lock")
    if name == "home":
        try:
            risky = smarthome.needs_confirmation(arg.partition("|")[0].strip())
        except LookupError as error:
            return "fail", str(error)
    if risky and not confirmed:
        prompt = "Подтвердите действие: " + name + " «" + arg + "». Скажите «да» или «нет»."
        CONFIRMATIONS.request({"actions": [{"type": "tool", "name": name, "arg": arg, "confirmed": True}]},
                              float((config.get("confirm") or {}).get("timeout", 20)))
        return "say", prompt
    if name == "mcp":
        from shelter_core import integrations
        return integrations.execute(config, arg, confirmed)
    print(f">> TOOL  //  {name}")
    if name == "textops":
        from shelter_core import textops
        if arg == "apply":
            try:
                textops.apply()
                return "done", "Заменил, сэр."
            except RuntimeError as error:
                return "fail", str(error).capitalize() + "."
        return textops.voice_command(arg, config)
    if name == "app":
        ok, title = tools.open_app(arg)
        if ok:
            return "done", title
        return "fail", f"Не нашёл у вас программу «{arg}», сэр."
    if name == "weather":
        try:
            return "data", tools.weather(arg, config)
        except LookupError:
            return "fail", f"Не нашёл город «{arg}», сэр."
        except OSError:
            return "fail", "Сервис погоды не отвечает, сэр."
    if name == "search":
        try:
            return "data", tools.search(arg, config)
        except OSError as error:
            print(f">> SEARCH ERROR  //  {error}")
            return "fail", "Поиск сейчас недоступен, сэр."
    if name == "home":
        device, _, action = arg.partition("|")
        try:
            title = smarthome.act(device.strip(), action.strip() or "toggle", config)
            return "done", title
        except smarthome.StateUnverified as error:
            return "say", str(error)
        except LookupError as error:
            return "fail", str(error)
        except Exception as error:
            print(f">> SMART HOME ERROR  //  {error}")
            return "fail", "Устройство не отвечает, сэр."
    if name == "nowplaying":
        return "say", media.describe()
    if name == "media":
        # Любой плеер и видео в браузере — через медиа-сессии Windows.
        action = {"пауза": "pause", "стоп": "pause", "play": "play", "продолжи": "play", "дальше": "next",
                  "следующий": "next", "назад": "previous", "предыдущий": "previous", "prev": "previous"}.get(
            arg.strip().lower(), arg.strip().lower())
        if action not in ("pause", "play", "toggle", "next", "previous", "stop"):
            return "fail", "Не понял, что сделать с воспроизведением, сэр."
        done = media.ensure(action) if action in ("pause", "play") else media.control(action)
        return ("done", "") if done else ("fail", "Сейчас ничего не играет, сэр.")
    if name == "obs":
        try:
            normal, phrase = obs.act(arg, config)
        except obs.ObsError as error:
            return "fail", f"{str(error).rstrip('.')}, сэр."
        return ("done", phrase) if normal else ("say", phrase)
    if name == "remember":
        return ("done", arg) if memory.remember(arg) else ("fail", "Не расслышал, что запомнить, сэр.")
    if name == "remember_project":
        from shelter_core import assistant_store as store
        if not store.project_id(tasks.current().session_id if tasks.current() else None):
            return "fail", "Сначала выберите проект в окне Джарвиса"
        return ("done", arg) if memory.remember(arg, project=True) else ("fail", "Не расслышал, что запомнить")
    if name == "forget":
        removed = memory.forget(arg)
        return ("done", arg) if removed else ("fail", "Я и не помнил ничего такого, сэр.")
    if name == "timer":
        amount, _, label = arg.partition("|")
        seconds = tools.number(amount)
        if not seconds or seconds <= 0:
            return "fail", "Не расслышал, на сколько поставить таймер, сэр."
        scheduler.add_timer(seconds, label)
        return "done", ""
    if name == "remind":
        parts = [p.strip() for p in arg.split("|")]
        clock, when, label = (parts + ["", "", ""])[:3]
        if not label and when and not scheduler.parse_clock(when):
            when, label = "", when               # [remind: 09:00 | встреча]
        if scheduler.add_reminder(clock, when, label or "напоминание") is None:
            return "fail", "Не расслышал время, сэр."
        return "done", ""
    if name == "timers":
        return "say", scheduler.describe()
    if name == "cancel":
        removed = scheduler.cancel(arg)
        return ("done", "") if removed else ("fail", "Отменять нечего, сэр.")
    if name == "briefing":
        return "say", tools.briefing(config)
    if name == "screen":
        import base64
        from shelter_core import screen as screen_module
        try:
            shot = screen_module.snapshot(question_now.get("text", ""))
        except Exception as error:
            print(f">> SCREEN ERROR  //  {error}")
            return "fail", "Не получилось посмотреть на экран, сэр."
        text = shot["text"].strip()
        data = {"text": f"Окно «{shot['title']}». Текст на экране (распознан автоматически, "
                        f"возможны опечатки):\n{text or '(текста не видно)'}"}
        if shot["image"] and (config.get("llm") or {}).get("vision", True):
            data["images"] = [base64.b64encode(shot["image"]).decode()]
        if not text and "images" not in data:
            return "fail", "Не вижу на экране текста, сэр."
        return "data", data
    if name == "clipboard":
        text = pc.clipboard_text().strip()
        if not text:
            return "fail", "В буфере обмена нет текста, сэр."
        return "data", "Текст из буфера обмена:\n" + text[:3000]
    if name == "pc":
        return pc_tool(config, arg)
    if name == "type":
        text = arg.strip()
        if not text:
            return "fail", "Не расслышал, что напечатать, сэр."
        # Печатаем туда, где работает человек: HUD Джарвиса фокус не забирает.
        from shelter_core import desktop_input
        return desktop_input.execute({"operation":"write","text":text},config)
    return "fail", "Этого я пока не умею, сэр."


def pc_tool(config, arg):
    """[pc: действие | цель] — управление Windows (pc.py)."""
    action_text, _, target = arg.partition("|")
    action, target = pc.parse(action_text), target.strip()
    if os.name != "nt" and action not in ("volume", "mute", "unmute", "status"):
        return "fail", "Это действие пока доступно только в Windows, сэр."
    try:
        if action in ("close", "minimize", "maximize", "focus"):
            title = pc.window(action, target)
            return ("done", title) if title else ("fail", f"Не нашёл окно «{target}», сэр.")
        if action == "fullscreen":
            # Видео, игра или браузер на весь экран: выход — Esc, вход — F11.
            leave = re.search(r"выйд|выйт|выход|убер|выключ|сверн|off|exit", (action_text + " " + target).lower())
            pc.send_keys("esc" if leave else "f11")
            return "done", ""
        if action == "desktop":
            pc.show_desktop()
        elif action == "volume":
            value = tools.number(target)
            if value is None:
                return "say", f"Громкость {pc.get_volume()} процентов, сэр."
            pc.set_volume(value)
        elif action in ("mute", "unmute"):
            pc.mute(action == "mute")
        elif action == "settings":
            pc.open_settings(target)
        elif action == "screenshot":
            pc.screenshot()
        elif action == "status":
            return "say", pc.system_status()
        elif action in ("lock", "sleep"):
            # Сначала договорить подтверждение, потом гасить экран.
            threading.Timer(2.5, pc.power, args=(action,)).start()
        elif action in ("shutdown", "restart"):
            delay = tools.number(target) or 60
            pc.power(action, delay)
            minutes = max(1, round(delay / 60))
            when = (f"{minutes // 60} ч" if minutes % 60 == 0 and minutes >= 60 else f"{minutes} мин")
            when = {"1 ч": "час", "1 мин": "минуту"}.get(when, when)
            verb = "Выключу" if action == "shutdown" else "Перезагружу"
            return "say", (f"{verb} компьютер через {when}, сэр. "
                           "Скажите «отмени выключение», если передумаете.")
        elif action == "cancel":
            return ("done", "") if pc.power("cancel") else ("fail", "Выключение не было запланировано, сэр.")
        elif action in ("discord_mute", "discord_deafen"):
            pc.discord("mute" if action == "discord_mute" else "deafen", config)
        else:
            return "fail", "Этого я с компьютером пока не умею, сэр."
    except Exception as error:
        print(f">> PC ERROR  //  {action}: {error}")
        return "fail", "Не получилось, сэр."
    return "done", ""


def answer(config, question, guest=False):
    THINKING.set()
    try:
        return _answer(config, question, guest)
    finally:
        THINKING.clear()


def guest_config(config):
    """Чужой голос (узнавание хозяина, режим soft): только узнать — погода, поиск,
    что играет. Ни команд, ни действий, ни памяти хозяина в подсказке."""
    from shelter_core import speaker
    llm_cfg = dict(config.get("llm") or {})
    llm_cfg['guest']=True
    llm_cfg["tools"] = [t for t in (llm_cfg.get("tools") or []) if t in speaker.GUEST_TOOLS]
    return {**config, "llm": llm_cfg, "commands": []}


def _answer(config, question, guest=False):
    """Свободная фраза: модель выбирает команду или инструмент, либо отвечает голосом.

    Ответ идёт потоком: первая фраза звучит, пока модель дописывает остальные.
    """
    tasks.check()
    print(f">> QUERY  //  {question}" + ("  (гость)" if guest else ""))
    token = tasks.current()
    bus.publish("query", text=question, guest=guest, session_id=token.session_id if token else None)
    question_now["text"] = question
    auto_request = automation_intent.inspect(question)
    save_name = automation_intent.save_title(question)
    from shelter_core import minecraft_intents
    from shelter_core import minecraft_npc
    from shelter_core.minecraft_companion import MINECRAFT
    game_session = None if guest else MINECRAFT.reply_session()
    npc_session = None if guest or game_session else minecraft_npc.reply_session()

    def publish_reply(reply, *, fast=False, game=False):
        bus.publish("reply", text=reply, fast=fast, session_id=token.session_id if token else None)
        if game_session:
            MINECRAFT.relay(game_session, reply, game=game)
        elif npc_session:
            minecraft_npc.relay(npc_session, reply)

    def finish_local(reply, *, game=False):
        tasks.check()
        publish_reply(reply, fast=True, game=game)
        tasks.reply(reply)
        voice.speak_stream([reply])
        tasks.check()
        LISTENING.set()
        voice.RESUME.set()
        return []

    from shelter_core import live_facts
    fact = live_facts.answer(question, config)
    if fact is not None:
        return finish_local(fact)

    from shelter_core import game_assist
    game_reply = game_assist.answer(question, config, guest=guest)
    if game_reply is not None:
        return finish_local(game_reply)

    image_request = re.fullmatch(r"(?:нарисуй|создай (?:картинку|изображение)|сгенерируй (?:картинку|изображение))"
                                 r"\s+(.+)", question.strip(), re.IGNORECASE | re.DOTALL)
    if image_request and (config.get("image_generation") or {}).get("connection"):
        if guest:
            return finish_local("Создание изображений доступно только владельцу.")
        from shelter_core import cloud_media
        try:
            cloud_media.image(image_request[1], config)
        except (ValueError, KeyError, TypeError, OSError) as error:
            return finish_local(f"Не удалось создать изображение. {error}")
        return finish_local("Изображение готово. Я сохранил его в папке data/generated внутри папки приложения.")

    if save_name is not None or auto_request and auto_request.chain:
        if guest:
            return finish_local("Собирать и сохранять цепочки может только владелец.")
        CONFIRMATIONS.clear()
        if save_name is not None:
            try:
                reply = automation_intent.save(save_name)
            except (OSError, ValueError):
                reply = "Сценарий не удалось сохранить. Выполненные действия не повторялись."
        else:
            reply, _ = automation_intent.run(auto_request, config)
        return finish_local(reply)
    if browser_episode.matches(question):
        if guest:
            reply = "Переключать серии может только владелец."
        else:
            _, reply = run_tool(config, "browser_episode", "next")
        return finish_local(reply)
    npc = MINECRAFT.phase != "ready" and minecraft_npc.paired()
    game = minecraft_intents.desktop(question, MINECRAFT.phase == "ready" or npc, allow_implicit=not guest,
                                     version=MINECRAFT.info.get("version", ""))
    if game is not None:
        try:
            if guest:
                reply = "Игровые команды доступны только владельцу."
            else:
                reply = minecraft_npc.voice(game) if npc else MINECRAFT.execute(game)
        except RuntimeError as error:
            reply = str(error)
        return finish_local(reply, game=True)
    if game_session:
        config = {**config, "_minecraft_actions": True, "_minecraft_state": MINECRAFT.game_context(game_session)}
    elif npc_session:
        config = {**config, "_minecraft_state": minecraft_npc.game_context(npc_session)}
    if guest:
        config = guest_config(config)
    commands = config.get("commands") or []
    from shelter_core import desktop_input
    from shelter_core import desktop_intent
    semantic_desktop = desktop_intent.Request(question, config)
    llm_cfg = config.get("llm") or {}
    semantic_enabled = not guest and llm_cfg.get("enabled") and llm_cfg.get("semantic_input", True) and policy.allowed(config, "pc")
    desktop_request = desktop_input.resolve(question)
    if not guest and desktop_request and desktop_request["operation"] in ("write","replace","append","rewrite"):
        CONFIRMATIONS.clear()  # A dictated «да» is text, not approval of an older action.
    kind, confirmed = (None, None) if guest or desktop_request else CONFIRMATIONS.resolve(question, config)
    if kind:
        if _events is not None:
            _events.put((kind, confirmed))
        return []
    command = None if guest else voice.find_command(question.lower(), commands)
    if command and semantic_enabled:
        whole = re.sub(r"\s+", " ", question.lower().replace("ё", "е")).strip(" .!?,")
        exact = any(whole == str(k).lower().replace("ё", "е").rstrip("*") for k in command.get("keywords", []))
        if not exact:
            # A keyword inside an unfamiliar dictation phrase is literal text,
            # e.g. «в это поле впиши Привет», not the greeting scenario.
            intent = semantic_desktop.inspect()
            if intent["decision"] in ("execute", "clarify") and not intent.get("unavailable"):
                command = None
    if command:
        if _events is not None:
            _events.put(("command", command))
        else:
            voice.inject(command, question)
        return []
    run_action({"type": "overlay", "seconds": 0, "text": "PROCESSING"})
    acted = []
    approved_desktop = set()

    def use_tool(name, arg):
        if guest:
            from shelter_core import speaker
            if name not in speaker.GUEST_TAGS:
                print(f">> GUEST BLOCKED  //  {name}")
                return "fail", "Это может сделать только хозяин, сэр."
        if name == "minecraft":
            action = minecraft_intents.model_command(arg)
            if not action or not game_session or game_session != MINECRAFT.reply_session():
                return "say", "Не удалось выполнить игровую команду. Уточните цель или проверьте подключение."
            try:
                reply = MINECRAFT.execute(action, game_session[0], epoch=game_session[1])
            except RuntimeError as error:
                reply = str(error)
            return "say", reply
        if name in ("remember", "remember_project", "forget"):
            explicit = r"\b(запомни|запомнить|сохрани|учти|помни|забудь|забыть|удали)\b"
            if not re.search(explicit, question, re.I) or re.search(r'\bне\s+(?:запоминай|запомни|сохраняй|удаляй|забывай|забудь)\b',question,re.I):
                return "fail", "Для изменения памяти нужна ваша явная просьба, сэр."
        if name == "persona":
            from shelter_core import personas
            if not personas.switch_requested(question):
                return "fail", "Для смены персонажа нужна просьба сменить образ. Одно имя только вызывает помощника."
        if name in ("desktop","type"):
            from shelter_core import desktop_input
            explicit=desktop_input.resolve(question)
            if name=="type" and explicit and explicit["operation"]=="write":
                arg=explicit.get("text","")
            else:
                try: requested=json.loads(arg) if name=="desktop" else {"operation":"write"}
                except (ValueError,TypeError):requested={"operation":arg}
                if not isinstance(requested,dict):return "fail","Не понял действие ввода"
                if requested != explicit and arg not in approved_desktop:
                    if not policy.allowed(config,"pc"):return "fail","Управление компьютером выключено в настройках"
                    status,command=semantic_desktop.authorize(requested.get("operation"))
                    if status!="execute":
                        if status=="say":tasks.continue_dialogue()
                        return status,command
                    # The classifier, not a proposed payload or past conversation,
                    # supplies bounded arguments grounded in this user utterance.
                    name="desktop"
                    arg=json.dumps(command,ensure_ascii=False)
                    if command["operation"] in ("write","replace","append","rewrite"):
                        CONFIRMATIONS.clear()
        run_action({"type": "overlay", "seconds": 0, "text": TOOL_LABELS.get(name, "WORKING")})
        tasks.check()
        outcome, text = run_tool(config, name, arg)
        bus.publish("tool", name=name, ok=outcome != "fail", session_id=token.session_id if token else None,
                    label=TOOL_LABELS.get(name, name.upper()))
        if outcome == "done":
            acted.append(name)
            if brief:
                gaming.earcon("done")
        return outcome, text

    # Во время игры: действия подтверждаются коротким звуком вместо фразы (синтез
    # голоса не трогает видеокарту), а модель быстрее отпускает видеопамять.
    game_cfg = config.get("gaming") or {}
    in_game = gaming.busy(config)
    brief = in_game and bool(game_cfg.get("brief", True))
    if in_game and game_cfg.get("keep_alive"):
        config = {**config, "llm": {**(config.get("llm") or {}), "keep_alive": game_cfg["keep_alive"]}}

    # Однозначные простые фразы — сразу, без модели (fastpath.py).
    try:
        # Быстрые правила выполняют действия сразу — гостю они недоступны.
        plan = None if guest else tasks.run(lambda: fastpath.plan(question, config))
        semantic_input = semantic_desktop.result and semantic_desktop.result["decision"] in ("execute", "clarify") and not semantic_desktop.result.get("unavailable")
        if semantic_input:
            fast = None
        elif plan:
            approved_desktop.update(arg for calls,_ in plan for name,arg in calls if name=="desktop")
            replies, did, executed = [], False, []
            for calls, success in plan:
                for name, arg in calls:
                    outcome, result = use_tool(name, arg)
                    executed.append((name, arg))
                    replies.append((success or str(result)) if outcome == "done" else str(result))
                    did |= outcome == "done"
                    if outcome != "done":
                        break
                if outcome != "done":
                    break
            # «Поставь на паузу и выйди из полноэкранного»: выход из полного экрана
            # мог снять паузу — проверить ещё раз, когда всё выполнено.
            if ("media", "pause") in executed and len(executed) > 1:
                time.sleep(0.4)
                media.ensure("pause")
            fast = " ".join(replies), did
        elif guest:
            fast = None
        else:
            fast = tasks.run(lambda: fastpath.handle(question, config, run_tool=use_tool))
    except tasks.Cancelled:
        raise
    except Exception as error:
        print(f">> FAST PATH ERROR  //  {error}")
        fast = None
    # Resolve unrecognised input requests before the conversational model can
    # answer instead of acting, or choose a nearby but wrong tool. One cached
    # classification is shared with the dispatcher, never a second LLM pass.
    if (fast is None and auto_request and not guest and not desktop_request
            and llm_cfg.get("enabled") and llm_cfg.get("action_plans", True)):
        return finish_local(automation_intent.run(auto_request, config)[0])
    if fast is None and semantic_enabled:
        intent = semantic_desktop.inspect()
        if intent["decision"] == "execute":
            outcome, reply = use_tool("desktop", json.dumps(intent["command"], ensure_ascii=False))
            fast = reply, outcome == "done"
        elif intent["decision"] == "clarify" and not intent.get("unavailable"):
            tasks.continue_dialogue()
            fast = intent["question"], False
    if fast:
        reply, did = fast
        print(f">> FAST  //  {reply}")
        publish_reply(reply, fast=True)
        tasks.reply(reply)
        if did and brief:
            gaming.earcon("done")
        else:
            voice.speak_stream([reply])
        continuing = tasks.dialogue_continues()
        close_after = tasks.dialogue_ends() or (not continuing and (
            brief or bool((config.get("wake") or {}).get("close_after_action", False))))
        run_action({"type": "close"} if did and close_after else
                   {"type": "overlay", "seconds": 0, "text": _wake_label(config)})
        if continuing:
            LISTENING.set()
            voice.RESUME.set()
        return []

    if not (config.get("llm") or {}).get("enabled"):
        reply = "Свободный разговор выключен. Я могу выполнить локальную команду, например поставить таймер или открыть программу."
        publish_reply(reply, fast=True)
        voice.speak_stream([reply])
        return []

    devices = smarthome.names() if smarthome.enabled(config) else []
    stream = llm.respond(question, config, commands, run_tool=use_tool, devices=devices)
    chosen = None
    mute = False
    spoken = []
    voiced = 0
    voice_limit = max(0, int((config.get("tts") or {}).get("reply_sentences", 3)))

    def sentences():
        for kind, value in patient(stream, token):
            tasks.check()
            yield from handle(kind, value)

    def handle(kind, value):
        nonlocal chosen, mute, voiced
        if kind == "tool":
            return
        if kind == "hint":
            yield value                     # «Секунду…» — звучит, но в ответ не входит
            return
        if kind == "command":
            # Второе действие той же фразы («открой калькулятор и сделай тише»).
            if (config.get("llm") or {}).get("commands", True) and 1 <= value <= len(commands):
                chosen = commands[value - 1]
                mute = bool(chosen.get("confirm")) or any(a.get("type") == "say" for a in chosen.get("actions") or [])
                print(f">> COMMAND BY MEANING  //  {llm.describe_commands([commands[value - 1]])[3:]}")
                voice.inject(commands[value - 1], question)
            return
        if kind == "text":
            spoken.append(value)
            if not mute and not (brief and acted) and (not voice_limit or voiced < voice_limit):
                voiced += 1
                yield value
        elif kind == "error":
            print(f">> LLM ERROR  //  {value}")
            from shelter_core.avatar import AVATAR
            AVATAR.trigger("error")
            bus.publish("error", text=f"Языковая модель: {value}")
            tasks.fail(value)
            if not spoken:
                yield ("Нейросеть сейчас не отвечает, сэр: похоже, видеокарта занята. Попробуйте ещё раз чуть позже."
                       if "видеокарта" in str(value) or "timed out" in str(value) else "Языковая модель не отвечает, сэр.")

    def speak():
        voice.speak_stream(sentences())
        tasks.check()
        if spoken:
            print(f">> REPLY  //  {' '.join(spoken)}")
            publish_reply(" ".join(spoken))
            tasks.reply(" ".join(spoken))
        if tasks.dialogue_continues():
            run_action({"type": "overlay", "seconds": 0, "text": _wake_label(config)})
            LISTENING.set()
            voice.RESUME.set()
        elif acted and (brief or (config.get("wake") or {}).get("close_after_action", False)):
            # Как и у команд: дело сделано — интерфейс уходит.
            run_action({"type": "close"})
        elif chosen is None and overlay_alive():
            run_action({"type": "overlay", "seconds": 0, "text": _wake_label(config)})

    speak()
    return []


LLM_HINT_AFTER = 6.0        # нет ни слова — сказать, что модель загружается
LLM_GIVE_UP_AFTER = 90.0    # совсем нет ответа — сказать об этом и освободить очередь


def patient(stream, token):
    """Ответ модели — в отдельном потоке, чтобы Джарвис не молчал, пока она
    загружается или видеокарта занята (другая нейросеть, игра, видео)."""
    box = queue.Queue()

    def pump():
        with tasks.scope(token):
            try:
                for item in stream:
                    box.put(item)
            except tasks.Cancelled:
                pass
            except Exception as error:
                box.put(("error", str(error)))
            finally:
                box.put(None)

    threading.Thread(target=pump, name="llm-stream", daemon=True).start()
    started, first, hinted = time.monotonic(), True, False
    while True:
        try:
            item = box.get(timeout=0.25)
        except queue.Empty:
            tasks.check()
            waited = time.monotonic() - started
            if first and not hinted and waited > LLM_HINT_AFTER:
                hinted = True
                yield "hint", "Секунду, сэр, нейросеть ещё загружается."
            if first and waited > LLM_GIVE_UP_AFTER:
                yield "error", "нейросеть не ответила за полторы минуты — видеокарта занята"
                return
            continue
        if item is None:
            return
        first = False
        yield item


def actions_for(config, kind, payload):
    if kind == "can_opened":
        from shelter_core import scenarios
        try:
            own = [i for i in scenarios.load(config) if i.get("enabled", True)
                   and any(t.get("type") == "can_opened" for t in i.get("triggers") or [])]
        except Exception:
            own = []
        if own:
            return [{"type": "scenario", "id": i["id"], "source": "звук банки"} for i in own]
        return []
    if kind == "command":
        if isinstance(payload, dict) and payload.get("confirm"):
            CONFIRMATIONS.request(payload, float((config.get("confirm") or {}).get("timeout", 20)))
            prompt = payload["confirm"]
            return actions_for(config, "confirm", prompt if isinstance(prompt, dict) else {"text": prompt})
        if isinstance(payload, dict) and payload.get("scenario"):
            return [{"type": "scenario", "id": payload["scenario"], "source": payload.get("source", "голос")}]
        # Новые отправители передают команду целиком, чтобы сохранить её
        # поведенческие настройки. Старый формат со списком пока поддерживаем.
        return (payload.get("actions") or []) if isinstance(payload, dict) else (payload or [])
    if kind == "wake":
        actions = (config.get("wake") or {}).get("actions") or []
        # Раннее обращение: окно сразу ("visual"), а «Да, сэр» — отдельно
        # ("voice"), когда ясно, что человек больше ничего не говорит.
        if payload == "visual":
            return [a for a in actions if a.get("type") != "say"]
        # Отклик «Да, сэр» помечен: пока он звучит, микрофон слушает просьбу дальше.
        mark = lambda a: {**a, "ack": True} if a.get("type") == "say" else a
        if payload == "voice":
            return [mark(a) for a in actions if a.get("type") == "say"]
        return [mark(a) for a in actions]
    if kind == "confirm":
        from shelter_core.avatar import AVATAR
        AVATAR.trigger("confirm")             # персонаж ждёт «да/нет»: наклон головы, внимательный взгляд
        ask = payload or {}
        return [{"type": "overlay", "seconds": 0, "text": "CONFIRM ?"},
                {"type": "say", "text": ask.get("text", "Вы уверены, сэр?"),
                 "file": ask.get("file")}]
    if kind == "cancelled":
        return [{"type": "overlay", "seconds": 4, "text": "CANCELLED"}]
    if kind == "listen_timeout":
        return [{"type": "close"}]
    if kind == "timer":
        item = payload if isinstance(payload, dict) else {"label": payload or "", "kind": "timer"}
        label = (item.get("label") or "").strip()
        if label.lower() in ("сводка", "брифинг", "доброе утро", "утренняя сводка"):
            return [{"type": "overlay", "seconds": 12, "text": "DAILY BRIEFING"},
                    {"type": "say", "text": tools.briefing(config)}]
        if item.get("missed"):
            text = f"Сэр, пока я был выключен, сработало напоминание: {label or 'таймер'}."
        elif label:
            text = f"Сэр, напоминаю: {label}."
        else:
            text = "Сэр, время вышло."
        gaming.earcon("wake")
        return [{"type": "overlay", "seconds": 10, "text": "REMINDER // " + (label or "TIME IS UP").upper()},
                {"type": "say", "text": text}]
    return []


def persona_runtime(config):
    """Голос под активного персонажа: образец клона, запасные голоса, кэш фраз."""
    from shelter_core import personas
    persona = personas.active()
    tts = config.get("tts") or {}
    voice.SPEAKER = tts.get("speaker", voice.SPEAKER)
    piper_voice = (tts.get("piper") or {}).get("voice", voice.PIPER_VOICE)
    if piper_voice != voice.PIPER_VOICE:
        voice.PIPER_VOICE, voice._piper = piper_voice, None
    clone_cfg = tts.get("clone") or {}
    voice.PITCH = float((persona.get("voice") or {}).get("pitch", 1.0)) if persona["id"] != personas.DEFAULT_ID else 1.0
    voice.EFFECT = str((persona.get("voice") or {}).get("effect", "")) if persona["id"] != personas.DEFAULT_ID else ""
    if voice.ENGINE == "piper" and not os.path.isdir(os.path.join(personas.ROOT, "models", "piper", voice.PIPER_VOICE)):
        def fetch(name=voice.PIPER_VOICE):
            try:
                from shelter_core import setup_tool
                setup_tool.install("piper:" + name)
                voice._piper = None
            except Exception as error:
                print(f"[persona] голос Piper {name} не скачался: {error}")
        threading.Thread(target=fetch, name="persona-voice", daemon=True).start()
    # Образец — всегда явно, и для Джарвиса тоже: сервер голоса мог стартовать
    # с образцом другого персонажа, и «по умолчанию» был бы её голос.
    reference = clone_cfg.get("reference") or ""
    full = reference if os.path.isabs(reference) else os.path.join(personas.ROOT, reference)
    clone_ref = ({"reference": os.path.relpath(full, personas.ROOT),
                  "reference_text": clone_cfg.get("reference_text", "")} if reference and os.path.isfile(full) else {})
    if clone_cfg.get("jarvis_adapter"):
        clone_ref["model_profile"] = "jarvis" if persona["id"] == personas.DEFAULT_ID else "default"
    voice.set_voice(clone_ref, lambda: voice.configure_cache(config))


def switch_persona(config, persona_id):
    """«Стань аниме-тянкой»: характер, голос и окно меняются сразу, без перезапуска."""
    from shelter_core import personas
    from shelter_core.avatar import AVATAR
    from shelter_core import actions
    persona = personas.switch(config, persona_id)
    tasks.continue_dialogue()
    persona_runtime(config)
    actions.close_hud()                       # реактор Джарвиса — не её интерфейс (и наоборот)
    AVATAR.configure(config)
    if AVATAR.builtin:
        AVATAR.start()
        AVATAR.trigger("listening")
    bus.publish("persona", persona=personas.public(persona))
    print(f">> PERSONA  //  {persona.get('name', persona_id)}")
    # Фраза превращения звучит первой и запоминается — готовим её проверенным
    # дублем заранее (секунда-две), а не потоком на удачу.
    reply = persona.get("switch_reply") or f"Теперь я {persona.get('name', persona_id)}."
    try:
        if voice.ENGINE != "clone" or voice.clone_ready():
            voice.prepare([reply])
    except Exception as error:
        print(f"[tts] фраза превращения не подготовлена: {error}")
    # Готовые фразы — сразу новым голосом, чтобы «Да, хозяин?» не ждало синтеза.
    texts = [a["text"] for actions in all_action_lists(config) for a in actions if a.get("type") == "say"]
    threading.Thread(target=lambda: voice.prepare(texts + list(llm.FILLERS.values())),
                     name="persona-phrases", daemon=True).start()
    return persona.get("switch_reply") or f"Теперь я {persona.get('name', persona_id)}."


def interrupt(config, runner, *, dismiss_dialogue=False):
    """Остановить работу и движение. Кнопка «Стоп» завершает и текущий диалог."""
    if dismiss_dialogue:
        voice.stop_listening()
        THINKING.clear()
    from shelter_core import desktop_input
    desktop_input.clear_pending()
    runner.cancel_current()
    from shelter_core.minecraft_companion import MINECRAFT
    MINECRAFT.interrupt()
    from shelter_core import minecraft_npc
    minecraft_npc.interrupt()
    from shelter_core import scenarios
    scenarios.cancel()                 # и всё, что сценарии ещё ждут
    voice.stop_speaking()
    from shelter_core.avatar import AVATAR
    if AVATAR.motion_active:
        from shelter_core import avatar_motion
        AVATAR.start()
        avatar_motion.perform(config, "stop")
        if not dismiss_dialogue:
            LISTENING.set()
            voice.RESUME.set()
    if dismiss_dialogue:
        close_overlay()


def start_services(config, dry_run=False):
    """Голос, модель, умный дом и индекс программ — всё грузится в фоне."""
    from shelter_core import assistant_store as store
    from shelter_core import personas
    persona = personas.apply(config)          # характер, голос и окно активного персонажа
    if persona["id"] != personas.DEFAULT_ID:
        print(f">> PERSONA  //  {persona.get('name')}")
    memory.initialize()
    store.recover_runs()
    tts_cfg = config.get("tts") or {}
    voice.SPEAKER = tts_cfg.get("speaker", voice.SPEAKER)
    voice.ENGINE = tts_cfg.get("engine", voice.ENGINE)
    voice.CLOUD_TTS = config if voice.ENGINE == "cloud" else {}
    voice.SILERO_MODEL = (tts_cfg.get("silero") or {}).get("model", "v5_6_ru")
    voice.SILERO_THREADS = int((tts_cfg.get("silero") or {}).get("threads", 2))
    voice.STRESS = tts_cfg.get("stress") or {}
    piper_cfg = tts_cfg.get("piper") or {}
    voice.PIPER_VOICE = piper_cfg.get("voice", voice.PIPER_VOICE)
    voice.PIPER_SPEED = float(piper_cfg.get("speed", voice.PIPER_SPEED))
    persona_runtime(config)
    from shelter_core import speech_text
    speech_text.PRONUNCIATIONS = (tts_cfg.get("pronunciations") or {})
    threading.Thread(target=speech_text.morph, name="morph-boot", daemon=True).start()   # словарь падежей
    configure_actions(config)
    from shelter_core import actions
    actions.configure_tool(lambda name, arg, confirmed=False: run_tool(config, name, arg, confirmed),
                           ask=lambda question: answer(config, question))
    # Сценарии — общий формат команд: голос, кнопка, событие, расписание, телефон.
    from shelter_core import scenarios
    scenarios.configure(config, run_tool=lambda name, arg: run_tool(config, name, arg),
                        switch_persona=lambda persona_id: switch_persona(config, persona_id))
    voice.speaking_flag(False)   # снять флаг, если прошлый запуск умер во время фразы
    try:
        os.remove(STOP_REQUEST)       # старый запрос от прошлого запуска
    except OSError:
        pass
    gaming.recover()                  # прошлый запуск умер с приглушённым звуком

    def prepare_phrases():
        try:
            voice.prepare(all_texts(config) + list(llm.FILLERS.values()))
        except Exception as e:
            print(f"[tts] кэш не готов ({e})")

    if not dry_run:
        from shelter_core import startup_assets
        threading.Thread(target=startup_assets.repair_piper, args=(voice.ENGINE, voice.PIPER_VOICE, config),
                         name="fallback-voice-repair", daemon=True).start()
    if voice.ENGINE == "clone" and not dry_run:
        # Тяжёлая модель голоса живёт в своём процессе и грузится в фоне:
        # ассистент слушает уже сейчас, а не через полминуты.
        def when_ready():
            print(">> VOICE CLONE ONLINE")
            threading.Thread(target=prepare_phrases, name="tts-warm-phrases", daemon=True).start()
        threading.Thread(target=neural.boot, args=(config, voice, when_ready), name="tts-boot", daemon=True).start()
    else:
        prepare_phrases()

    if (config.get("llm") or {}).get("enabled") and not dry_run:
        threading.Thread(target=llm.warm_up, args=(config,), name="llm-boot",
                         daemon=True).start()

    if smarthome.enabled(config) and not dry_run:
        threading.Thread(target=smarthome.load, args=(config,), name="home-boot",
                         daemon=True).start()
    # Индекс программ из меню «Пуск» — заранее, чтобы «открой Firefox» не ждал.
    threading.Thread(target=tools.load_apps, name="apps-boot", daemon=True).start()
    # Таймеры и напоминания из data/schedule.json — в том числе пропущенные.
    if not dry_run:
        scheduler.start(lambda item, missed: _events and _events.put(
            ("timer", {**item, "missed": missed})))


def chat(config):
    """Текстовый режим для проверки: вопрос с клавиатуры, ответ голосом и текстом.

    Микрофон не нужен — удобно проверять модель, инструменты и голос.
    """
    global _events
    start_services(config)
    _events = queue.Queue()
    runner = ActionRunner()

    def timers():
        while True:
            kind, payload = _events.get()
            runner.submit(actions_for(config, kind, payload))
    threading.Thread(target=timers, name="chat-events", daemon=True).start()

    print("Текстовый режим. Пишите вопрос или команду, пустая строка — выход.\n")
    try:
        while True:
            try:
                line = input("вы > ").strip().lstrip("﻿")
            except EOFError:
                break
            if not line:
                break
            finished = threading.Event()
            def process_line(question=line):
                try:
                    return answer(config, question)
                finally:
                    finished.set()
            if not runner.submit_lazy(process_line, label=line):
                print("Очередь занята; попробуйте ещё раз")
                continue
            while not finished.wait(0.1):
                pass
            # Команду из списка модель выбрала по смыслу — выполнить здесь,
            # опасные (выключение и т. п.) — только после подтверждения.
            while not voice.INBOX.empty():
                command, _, origin = voice.INBOX.get_nowait()
                if origin and origin.is_set():
                    continue
                if command.get("confirm"):
                    if input("   подтвердить? [д/н] ").strip().lower() not in ("д", "да", "y", "yes"):
                        print("   отменено")
                        continue
                runner.submit(actions_for(config, "command", command))
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        voice.stop_speaking()
        gaming.restore()
        neural.stop()
        runner.stop()
        close_overlay()


def core_status(config, cap):
    """Состояние для окна приложения (control.py -> /api/status)."""
    from shelter_core import asr
    from shelter_core import control as control_module
    from shelter_core import llm_connections
    llm_cfg = llm_connections.resolve(config.get("llm") or {})
    try:
        mic = sd.query_devices(cap.stream.device, "input")["name"]
    except Exception:
        mic = ""
    return {
        "version": control_module.VERSION,
        "listening": LISTENING.is_set(),
        "speaking": voice.SPEAKING.is_set(),
        "thinking": THINKING.is_set(),
        "voice": voice.ENGINE,
        "clone_ready": neural.status()["phase"] == "ready" if voice.ENGINE == "clone" else None,
        "voice_status": neural.status() if voice.ENGINE == "clone" else None,
        "asr": "gigaam" if asr._recognizer is not None else "vosk",
        "wake_engine": voice.WAKE_ENGINE,
        "persona": {k: (config.get("persona") or {}).get(k) for k in ("id", "name", "title", "address", "gender")},
        # Подавление эха: откуда берём звук колонок и идёт ли он (render — кадры 10 мс).
        "echo": ({"speaker": cap.echo.speaker, "error": cap.echo.error, "frames": cap.echo.render_frames}
                 if getattr(cap, "echo", None) is not None else None),
        "llm": {"enabled": bool(llm_cfg.get("enabled")), "model": llm_cfg.get("model", ""),
                "provider": llm_cfg.get("provider", "ollama")},
        "in_game": gaming.busy(config),
        "mic": mic,
        "wake_word": ((config.get("wake") or {}).get("words") or ["джарвис"])[0],
        "workers": dict(WORKERS),
        # Для главной: «жду подтверждения», «выполняю …», что в очереди.
        "confirming": CONFIRMATIONS.active(),
        "executing": bool(RUNNER and RUNNER._current is not None),
        "task": (RUNNER.current_label if RUNNER else "") or "",
        "queued": RUNNER._jobs.qsize() if RUNNER else 0,
        "recognizing": bool(getattr(voice, "HEARING", None) and voice.HEARING.is_set()),
        "platform": sys.platform,
    }


def run(config, dry_run):
    global _events, detector
    start_services(config, dry_run)
    try:
        cap = open_capture(config)
    except Exception:
        voice.stop_speaking()
        neural.stop()
        gaming.restore()
        close_overlay()
        raise
    events = queue.Queue()
    _events = events
    stop = threading.Event()
    runner = ActionRunner()
    global RUNNER
    RUNNER = runner
    companion = CompanionServer(config, events)
    companion.start()
    from shelter_core.minecraft_companion import MINECRAFT
    control = ControlServer(config, events, cap, lambda: core_status(config, cap),
                            minecraft=None if dry_run else MINECRAFT)
    control.start()
    bus.publish("state", text="online")
    threads = []

    def listen_repaired(cap, config, events, stop):
        from shelter_core import startup_assets
        startup_assets.listen(voice.listen, cap, config, events, stop,
                              lambda phase: WORKERS.update(vosk={"state": phase, "error": ""}))
    workers = [(listen_repaired if not dry_run else voice.listen, "vosk"), (watch_capture, "microphone")]
    detector_cfg = config.get("detector") or {}
    if detector_cfg.get("enabled", False):
        try:
            import importlib
            detector = importlib.import_module("shelter_core.detector")
        except Exception as error:
            bus.publish("error", text=f"Необязательный звуковой триггер недоступен: {error}")
    if detector is not None and detector_cfg.get("enabled", True) \
            and os.path.exists(detector_cfg.get("model_path", "models/can_model.pkl")):
        workers.append((detector.run, "detector"))
    for target, name in workers:
        t = threading.Thread(target=_guard(target, name), name=name,
                             args=(cap, config, events, stop), daemon=True)
        t.start()
        threads.append(t)

    if dry_run:
        print("--dry-run: события логируются, действия не выполняются")
    print("Ctrl+C — выход.\n")

    if not dry_run:
        from shelter_core import triggers
        triggers.start(events, config)        # события и расписания сценариев
        from shelter_core import telegram_bot
        telegram_bot.start(config, events)    # свой бот: сопряжённые чаты владельца
    try:
        while True:
            from shelter_core.avatar import AVATAR
            AVATAR.tick(config)
            try:
                kind, payload = events.get(timeout=0.2)
            except queue.Empty:
                # Таймер диалога ведёт распознавание. Отсутствие окна во время
                # запуска HUD/аватара само по себе не сбрасывает обращение.
                if LISTENING.is_set():
                    from shelter_core.actions import hud_closed
                    if hud_closed():
                        voice.stop_listening()
                # Диалог закончился — вернуть громкость игре и музыке.
                if gaming.ducked() and not LISTENING.is_set() and not voice.SPEAKING.is_set():
                    gaming.restore()
                if os.path.exists(STOP_REQUEST) or control.stop_requested.is_set():
                    print("\n>> SHUTDOWN  //  запрос от лаунчера")
                    break
                continue
            if kind == "wake" and payload != "voice":
                bus.publish("wake")
            elif kind == "command" and isinstance(payload, dict):
                bus.publish("command", text=payload.get("description") or ", ".join(payload.get("keywords") or []))
            elif kind == "timer":
                bus.publish("reminder", text=(payload or {}).get("label", "") if isinstance(payload, dict) else str(payload))
            if kind == "wake" and payload != "voice" and not dry_run:
                # Мгновенный отклик на «Джарвис»: сигнал и тише всё остальное.
                wake_cfg = config.get("wake") or {}
                if wake_cfg.get("earcon", True):
                    gaming.earcon("wake")
                threading.Thread(target=gaming.duck, args=(float(wake_cfg.get("duck", 0.3)),),
                                 name="duck", daemon=True).start()
            if kind == "quick":
                if not dry_run:
                    threading.Thread(target=handle_quick, args=(payload,), name="quick",
                                     daemon=True).start()
                continue
            if kind == "interrupt":
                interrupt(config, runner, dismiss_dialogue=payload == "ui")
                continue
            if kind == "scenario" and isinstance(payload, dict):
                # Кнопка в окне, телефон, событие или расписание — тот же исполнитель, что у голоса.
                from shelter_core import scenarios
                item = scenarios.get(str(payload.get("id", "")))
                if item is None or not item.get("enabled", True):
                    bus.publish("error", text="Сценарий не найден или выключен")
                    continue
                if dry_run:
                    print(f"[событие] сценарий {item['name']} пропущен")
                    continue
                if item.get("confirm") and not payload.get("confirmed"):
                    kind, payload = "command", {"keywords": item["phrases"], "description": item["name"],
                                                "confirm": item["confirm"], "scenario": item["id"],
                                                "source": payload.get("source", "кнопка"), "actions": []}
                else:
                    if not runner.submit([{"type": "scenario", "id": item["id"], "source": payload.get("source", "кнопка"),
                                           "run": payload.get("run"), "speak_errors": payload.get("speak_errors", True)}],
                                         key="scenario:" + item["id"], label=item["name"]):
                        bus.publish("error", text=f"«{item['name']}» уже выполняется или очередь занята")
                    continue
            if kind == "minecraft_speech":
                from shelter_core.minecraft_companion import MINECRAFT
                session, epoch, reply = payload
                if not dry_run:
                    runner.submit_lazy(lambda session=session, epoch=epoch, reply=reply:
                                       voice.speak_stream([reply]) if MINECRAFT.process is session and MINECRAFT.chat_epoch == epoch else None,
                                       key="minecraft-speech", label="Minecraft")
                continue
            if kind == "preview":
                if not dry_run:
                    runner.submit([{"type": "say", "text": payload}])
                continue
            if kind == "guest_ignored":
                bus.publish("guest", text=str(payload))      # режим strict: чужой голос не слушаем
                continue
            if kind in ("ask", "typed", "guest"):
                if not dry_run:
                    # Голосовой вопрос, пока идёт ответ, — скорее всего повтор (эхо,
                    # переспрос): пропускаем. Напечатанные в окне — встают в очередь.
                    request = payload if isinstance(payload, dict) else {"text": payload}
                    question = str(request.get("text", ""))
                    guest = kind == "guest"
                    if question.strip():
                        # Голосовой вопрос, пока идёт ответ, — скорее всего эхо или переспрос: пропуск.
                        # С именем («Джарвис, а ещё…») listen помечает его queue — тогда в очередь.
                        queued = kind == "typed" or bool(request.get("queue"))
                        submitted = runner.submit_lazy(lambda question=question, guest=guest: answer(config, question, guest),
                                           key=None if queued else "ask", label=question,
                                           session_id=request.get("session_id"),
                                           **({"context": request["remote"]} if request.get("remote") else {}))
                        if not submitted:
                            if request.get("remote"):
                                from shelter_core import remote_audio
                                remote_audio.finish_target(request["remote"], "Очередь занята")
                            bus.publish("error", text="Очередь занята. Дождитесь ответа или остановите текущую задачу.")
                else:
                    print("[событие] ask: запрос к модели пропущен")
                continue
            if kind == "can_opened":
                if detector is None or not detector.is_armed(config["detector"]):
                    print("[detector] открытие банки проигнорировано: сначала скажите «Джарвис»")
                    continue
                # Звуковой триггер использует текущее обращение один раз.
                # Это также не даёт таймеру ожидания закрыть игровой HUD позже.
                if config["detector"].get("requires_wake", True):
                    LISTENING.clear()
            actions = actions_for(config, kind, payload)
            awaiting_confirmation = kind == "command" and isinstance(payload, dict) and bool(payload.get("confirm"))
            if dry_run:
                print(f"[событие] {kind}: {len(actions)} действий пропущено")
                continue
            if kind == "wake" and payload != "voice":
                # Visual acknowledgement is independent of queued replies and
                # must still happen while the previous task is winding down.
                visuals = [a for a in actions if a.get("type") == "overlay"]
                for action in visuals or [{"type": "overlay", "seconds": 0, "text": _wake_label(config)}]:
                    run_action(action)
                actions = [a for a in actions if a.get("type") != "overlay"]
            key = "can_opened" if kind == "can_opened" else None
            label = (payload.get("description") or ", ".join(payload.get("keywords") or [])) if kind == "command" and isinstance(payload, dict) else None
            submitted = runner.submit(actions, key=key, label=label)
            # Команда отработала — интерфейс уходит. Если команда открыла своё
            # окно, оно закроется само по своему таймеру.
            keep_listening = (kind == "command" and isinstance(payload, dict)
                              and bool(payload.get("keep_listening")))
            inner = (payload.get("actions") or []) if kind == "command" and isinstance(payload, dict) and payload.get("scenario") else actions
            if (submitted and kind == "command" and not keep_listening and not awaiting_confirmation
                    and not any(a.get("type") in ("overlay", "close") for a in inner)):
                runner.submit([{"type": "close"}])
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        from shelter_core import triggers
        triggers.stop()
        from shelter_core import telegram_bot
        telegram_bot.stop()
        from shelter_core import avatar_motion
        avatar_motion.BEAT.stop()
        voice.stop_speaking()
        gaming.restore()
        neural.stop()
        from shelter_core import integrations
        integrations.stop()
        MINECRAFT.close()
        companion.stop()
        bus.publish("state", text="offline")
        control.stop()
        runner.stop()
        for t in threads:
            t.join(timeout=1.0)
        close_overlay()
        cap.stop()
        print("\nОстановлено.")


def _guard(target, name):
    """Упавший поток не должен уносить с собой весь ассистент."""
    def wrapper(*args):
        stop = args[-1]
        for attempt in range(3):
            try:
                WORKERS[name] = {"state": "running", "error": ""}
                target(*args)
                return
            except Exception as e:
                WORKERS[name] = {"state": "error", "error": str(e)}
                bus.publish("error", text=f"{name}: {e}")
                if stop.wait(min(5, attempt + 1)):
                    return
        WORKERS[name]["state"] = "failed"
    return wrapper


def main():
    parser = argparse.ArgumentParser(description="Shelter")
    parser.add_argument("--list-devices", action="store_true")
    parser.add_argument("--dry-run", action="store_true",
                        help="детектить и логировать, но не выполнять действия")
    parser.add_argument("--meter", action="store_true",
                        help="только уровень сигнала, для проверки микрофона")
    parser.add_argument("--verbose", action="store_true",
                        help="печатать всё, что слышит vosk, и состояние ожидания")
    parser.add_argument("--chat", action="store_true",
                        help="текстовый режим: вопросы с клавиатуры, без микрофона")
    args = parser.parse_args()

    if args.list_devices:
        list_devices()
        return

    config = load_config()
    if args.meter:
        meter(config)
        return

    config["verbose"] = args.verbose
    if args.chat:
        chat(config)
        return
    run(config, args.dry_run)


if __name__ == "__main__":
    main()
