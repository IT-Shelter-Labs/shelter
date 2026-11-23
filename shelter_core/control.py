"""Локальный интерфейс ядра для приложения «Джарвис» (окно, мастер настройки).

Только 127.0.0.1 и только с ключом из data/control.token: веб-страница в
браузере не может ни прочитать этот файл, ни подставить заголовок без
разрешения CORS — а CORS здесь не разрешён никому.

GET  /api/status          состояние ядра
GET  /api/events          лента событий (NDJSON-поток, по строке на событие)
POST /api/ask   {text}    спросить текстом, как голосом
POST /api/say   {text}    произнести фразу (проверка голоса)
GET  /api/audio/devices   микрофоны
GET  /api/audio/level     текущая громкость микрофона (для индикатора)
POST /api/stop            аккуратно завершить ассистента
"""

from shelter_core.paths import ROOT_DIR

import json
import os
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

from shelter_core import bus
from shelter_core.local_http import send_json, token_matches

ROOT = ROOT_DIR
TOKEN_PATH = os.path.join(ROOT, "data", "control.token")
from app_version import VERSION


def _token():
    """Ключ создаётся один раз; приложение читает его из того же файла."""
    try:
        with open(TOKEN_PATH, encoding="utf-8") as file:
            token = file.read().strip()
            if len(token) >= 32:
                return token
    except OSError:
        pass
    token = secrets.token_urlsafe(32)
    os.makedirs(os.path.dirname(TOKEN_PATH), exist_ok=True)
    with open(TOKEN_PATH, "w", encoding="utf-8") as file:
        file.write(token)
    return token


class ControlServer:
    def __init__(self, config, events, cap, status, *, minecraft=None):
        self.config = config
        self.events = events          # очередь главного цикла
        self.cap = cap                # микрофон — для индикатора уровня
        self.status = status          # функция -> dict
        self.minecraft = minecraft
        self.stop_requested = threading.Event()
        self.token = _token()
        self.port = int((config.get("control") or {}).get("port", 8770))
        self.server = None

    def start(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def setup(self):
                super().setup()
                self.connection.settimeout(30)

            def log_message(self, *args):
                pass

            def _send(self, code, payload):
                send_json(self, code, payload)

            def _authorized(self):
                if token_matches(self.headers.get("X-Jarvis-Token", ""), owner.token):
                    return True
                self._send(403, {"error": "нужен ключ"})
                return False

            def _body(self):
                length = int(self.headers.get("Content-Length") or 0)
                limit = 1_000_000 if self.path == "/api/scenarios" else 65536
                if not 0 <= length <= limit:
                    raise OverflowError("слишком большой запрос")
                if not length:
                    return {}
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError("нужен JSON-объект")
                return data

            def do_GET(self):
                if not self._authorized():
                    return
                if self.path.startswith("/api/assistant"):
                    from shelter_core import assistant_store as store
                    from urllib.parse import urlsplit, parse_qs
                    if urlsplit(self.path).path != "/api/assistant":
                        self._send(404, {"error": "нет такого адреса"})
                        return
                    try:
                        self._send(200, store.snapshot(parse_qs(urlsplit(self.path).query).get("q", [""])[0]))
                    except Exception as error:
                        self._send(400, {"error": str(error)})
                elif self.path == "/api/status":
                    self._send(200, owner.status())
                elif self.path == "/api/minecraft" and owner.minecraft is not None:
                    self._send(200, owner.minecraft.snapshot())
                elif self.path == "/api/events":
                    self._stream_events()
                elif self.path == "/api/audio/devices":
                    self._send(200, owner.devices())
                elif self.path == "/api/audio/level":
                    self._send(200, owner.level())
                elif self.path == "/api/avatar/timers":
                    from shelter_core import scheduler
                    self._send(200, {"items": scheduler.timers()})
                elif self.path == "/api/schedule":
                    from shelter_core import scheduler
                    self._send(200, {"items": scheduler.all_items(), "now": __import__("time").time()})
                elif self.path == "/api/scenarios":
                    from shelter_core import scenario_api
                    self._send(200, scenario_api.snapshot(owner.config))
                elif self.path == "/api/personas":
                    from shelter_core import personas
                    self._send(200, {"active": personas.active()["id"],
                                     "personas": [personas.public(p) for p in personas.all_personas()]})
                else:
                    self._send(404, {"error": "нет такого адреса"})

            def do_POST(self):
                if not self._authorized():
                    return
                try:
                    data = self._body()
                except OverflowError as error:
                    self.close_connection = True
                    self._send(413, {"error": str(error)})
                    return
                except (ValueError, UnicodeError, OSError) as error:
                    self.close_connection = True
                    self._send(400, {"error": str(error)})
                    return
                if self.path == "/api/scenarios":
                    from shelter_core import scenario_api
                    from shelter_core import scenarios
                    try:
                        self._send(200, scenario_api.dispatch(data, owner.config, owner.events))
                    except (scenarios.ScenarioError, ValueError, KeyError, OSError, RuntimeError) as error:
                        self._send(400, {"error": str(error)})
                    return
                if self.path == "/api/settings/reload":
                    from shelter_core import settings_live
                    try:
                        self._send(200, settings_live.reload(owner.config))
                    except Exception as error:
                        self._send(400, {"error": str(error)})
                    return
                if self.path == "/api/schedule/cancel":
                    from shelter_core import scheduler
                    self._send(200, {"ok": scheduler.cancel_id(str(data.get("id") or ""))})
                    return
                if self.path == "/api/audio/test":
                    # Мастер микрофона: запись из буфера Джарвиса, на диск не пишется.
                    from shelter_core import mic_check
                    try:
                        self._send(200, mic_check.run(owner.cap, str(data.get("phase") or "speech"),
                                                      float(data.get("seconds") or 4), str(data.get("expected") or ""),
                                                      data.get("noise_db")))
                    except Exception as error:
                        self._send(400, {"error": str(error)})
                    return
                if self.path == "/api/companion":
                    # Окно Джарвиса: код сопряжения, список устройств, отзыв доступа.
                    from shelter_core import companion_devices
                    op = str(data.get("op") or "")
                    try:
                        if op == "code":
                            self._send(200, companion_devices.pairing_code())
                        elif op == "revoke":
                            companion_devices.revoke(str(data.get("id") or ""))
                            self._send(200, {"ok": True})
                        else:
                            self._send(200, {"devices": companion_devices.devices()})
                    except ValueError as error:
                        self._send(400, {"error": str(error)})
                    return
                if self.path in ("/api/persona/export", "/api/persona/import"):
                    from shelter_core import persona_package
                    try:
                        if self.path.endswith("export"):
                            self._send(200, persona_package.export(str(data.get("id") or ""), str(data.get("path") or ""),
                                                                   bool(data.get("include_voice")), str(data.get("author") or ""),
                                                                   str(data.get("license") or "")))
                        else:
                            self._send(200, persona_package.install(str(data.get("path") or "")))
                    except Exception as error:
                        self._send(400, {"error": str(error)})
                    return
                if self.path == "/api/textops":
                    from shelter_core import textops
                    op = str(data.get("op") or "state")
                    try:
                        if op == "selection":
                            result = textops.capture_selection()
                        elif op == "clipboard":
                            result = textops.from_clipboard()
                        elif op == "manual":
                            result = textops.manual(str(data.get("text") or ""))
                        elif op == "run":
                            result = textops.run(str(data.get("action") or ""), owner.config)
                        elif op == "apply":
                            result = textops.apply()
                        elif op == "copy":
                            result = textops.copy_result()
                        elif op == "cancel":
                            textops.cancel()
                            result = textops.snapshot()
                        else:
                            result = textops.snapshot()
                        self._send(200, result)
                    except Exception as error:
                        self._send(400, {"error": str(error)})
                    return
                if self.path == "/api/plugins":
                    from shelter_core import plugins_manager as pm
                    op = str(data.get("op") or "list")
                    try:
                        if op == "extensions":
                            from shelter_core import plugin_extensions
                            result = {kind: [{"id": p["id"], "name": p["name"], "settings_schema": p.get("settings_schema") or {}} for p in plugin_extensions.available(kind, owner.config)]
                                      for kind in ("tts", "stt", "trigger", "widget", "reaction")}
                        elif op == "widgets":
                            from shelter_core import plugin_extensions
                            result = {"items": plugin_extensions.widgets(owner.config)}
                        elif op == "catalog":
                            result = {"items": pm.catalog()}
                        elif op in ("source", "source_preview", "source_install"):
                            from shelter_core import plugin_catalog
                            if op == "source":
                                result = plugin_catalog.fetch(str(data.get("source") or ""), bool(data.get("local")))
                            elif op == "source_preview":
                                result = plugin_catalog.prepare(str(data.get("source") or ""), str(data.get("id") or ""),
                                    str(data.get("version") or ""), str(data.get("sha256") or ""), bool(data.get("local")))
                            else:
                                result = plugin_catalog.install(str(data.get("ticket") or ""))
                        elif op == "inspect":
                            result = pm.inspect(str(data.get("path") or ""))
                        elif op == "install":
                            result = pm.install(str(data.get("path") or ""))
                        elif op == "install_catalog":
                            result = pm.install_from_catalog(str(data.get("file") or ""))
                        elif op in ("enable", "disable"):
                            pm.set_enabled(str(data.get("id") or ""), op == "enable")
                            result = {"ok": True}
                        elif op == "remove":
                            pm.remove(str(data.get("id") or ""))
                            result = {"ok": True}
                        elif op == "rollback":
                            result = pm.rollback(str(data.get("id") or ""))
                        else:
                            result = {"items": pm.installed(), "allowed": bool((owner.config.get("security") or {}).get("allow_plugins"))}
                        self._send(200, result)
                    except Exception as error:
                        self._send(400, {"error": str(error)})
                    return
                if self.path == "/api/connections/test":
                    from shelter_core import connections_api
                    self._send(200, connections_api.test(data, owner.config))
                    return
                if self.path == "/api/minecraft" and owner.minecraft is not None:
                    try:
                        self._send(200, owner.minecraft.api(data, owner.config, owner.events))
                    except (ValueError, RuntimeError) as error:
                        self._send(400, {"error": str(error)})
                    except OSError:
                        self._send(400, {"error": "Не удалось запустить игровой клиент или сохранить его настройки."})
                    return
                if self.path == "/api/minecraft/npc" and owner.minecraft is not None:
                    from shelter_core import minecraft_npc
                    try:
                        self._send(200, minecraft_npc.api(data, owner.config))
                    except (ValueError, RuntimeError) as error:
                        self._send(400, {"error": str(error)})
                    return
                if self.path == "/api/media":
                    from shelter_core import media
                    if data.get("action"):
                        source = data.get("source")
                        if data["action"] not in ("pause","play","next","previous") or not isinstance(source,str) or not 0 < len(source) <= 4096:
                            self._send(400,{"error":"нужны действие и выбранный плеер"})
                            return
                        self._send(200,{"ok":media.control(data["action"],source)})
                    else:
                        self._send(200, {"playing": media.now_playing()})
                    return
                if self.path == "/api/image/generate":
                    from shelter_core import cloud_media
                    try:
                        self._send(200, cloud_media.image(data.get("prompt"), owner.config))
                    except (ValueError, KeyError, TypeError, OSError) as error:
                        self._send(400, {"error": str(error)})
                    return
                if self.path == "/api/factorio":
                    from shelter_core import game_assist
                    from pathlib import Path
                    try:
                        if data.get("op") == "prepare":
                            branch = data.get("branch", "2.0")
                            folder = game_assist.ROOT / "data" / "game-mods" / ("factorio-2.1" if branch == "2.1" else "factorio-2.0")
                            archive = game_assist.build_mod(folder / (game_assist.MOD + ".zip"), branch)
                            self._send(200, {"file": str(archive)})
                        elif data.get("op") == "prepare-hoi4":
                            folder = game_assist.ROOT / "data" / "game-mods"
                            archive = game_assist.build_hoi4_mod(folder / "shelter_campaign.zip")
                            self._send(200, {"file": str(archive)})
                        elif data.get("op") == "hoi4-live":
                            from shelter_core import hoi4_link
                            self._send(200, hoi4_link.action(owner.config, data.get("action"), days=data.get("days"),
                                                           equipment=data.get("equipment"), factories=data.get("factories"),
                                                           target=data.get("target")))
                        elif data.get("op") == "status":
                            from shelter_core import factorio_link
                            path = data.get("path")
                            path = Path(path) if isinstance(path, str) and path else game_assist.path_for(owner.config)
                            result = {"path": str(path), "state": None, "message": ""}
                            try:
                                if factorio_link.configured(owner.config):
                                    result.update(state={**factorio_link.request(owner.config, "status"), "age": 0},
                                                  path="127.0.0.1 · RCON")
                                else:
                                    result["state"] = game_assist.snapshot(path)
                            except ValueError as error:
                                result["message"] = str(error)
                            self._send(200, result)
                        elif data.get("op") == "companion":
                            from shelter_core import factorio_companion
                            self._send(200, factorio_companion.action(owner.config, data.get("action"), text=data.get("text", ""),
                                                                    companion_id=data.get("companion_id"), request_id=data.get("request_id"),
                                                                    count=data.get("count")))
                        elif data.get("op") in ("plan", "craft", "stop", "research", "build", "machine"):
                            from shelter_core import factorio_link
                            self._send(200, factorio_link.request(owner.config, data["op"],
                                                                recipe=data.get("recipe"), count=data.get("count"),
                                                                x=data.get("x"), y=data.get("y")))
                        else:
                            self._send(400, {"error": "Неизвестная операция Factorio."})
                    except (ValueError, OSError, RuntimeError) as error:
                        self._send(400, {"error": str(error)})
                    return
                if self.path == "/api/cancel":
                    # Общая «Стоп» из окна: речь, задача, очередь, сценарии и движения.
                    from shelter_core import scenarios
                    from shelter_core.policy import CONFIRMATIONS
                    from shelter_core import voice
                    voice.stop_listening()
                    CONFIRMATIONS.clear()
                    stopped = scenarios.cancel()
                    print(">> STOP  //  кнопка в приложении", flush=True)
                    owner.events.put(("interrupt", "ui"))
                    self._send(200, {"ok": True, "stopped": stopped})
                    return
                if self.path == "/api/assistant":
                    from shelter_core import assistant_api
                    try:
                        self._send(200, assistant_api.dispatch(data, owner.config, owner.events))
                    except Exception as error:
                        self._send(400, {"error": str(error)})
                    return
                text = str(data.get("text") or "").strip()
                if len(text) > 16000:
                    self._send(400, {"error": "Запрос длиннее 16000 знаков; прикрепите текст отдельным материалом"})
                    return
                if self.path == "/api/ask" and text:
                    from shelter_core import assistant_store as store
                    try:
                        session = store.session_for(data.get("session_id"))
                    except ValueError as error:
                        self._send(400, {"error": str(error)})
                        return
                    bus.publish("typed", text=text, session_id=session)
                    owner.events.put(("typed", {"text": text, "session_id": session}))
                    self._send(202, {"ok": True})
                elif self.path == "/api/say" and text:
                    owner.events.put(("preview", text))
                    self._send(202, {"ok": True})
                elif self.path in ("/api/voice/record", "/api/voice/import"):
                    try:
                        if self.path == "/api/voice/record":
                            result = owner.record_sample(float(data.get("seconds") or 10), str(data.get("target") or ""))
                        else:
                            result = owner.import_sample(str(data.get("path") or ""), str(data.get("target") or ""))
                        self._send(200, result)
                    except Exception as error:
                        self._send(400, {"error": str(error)})
                elif self.path == "/api/listen":
                    from shelter_core import voice
                    voice.ARM.set()                    # горячая клавиша: слушать команду
                    self._send(202, {"ok": True})
                elif self.path in ("/api/speaker/enroll", "/api/speaker/test", "/api/speaker/forget",
                                   "/api/speaker/status"):
                    try:
                        self._send(200, owner.speaker_action(self.path.rsplit("/", 1)[1],
                                                             float(data.get("seconds") or 0)))
                    except Exception as error:
                        self._send(400, {"error": str(error)})
                elif self.path == "/api/avatar/finished":
                    from shelter_core.avatar import AVATAR
                    AVATAR.finish_motion(str(data.get("motion_id") or ""))
                    self._send(200, {"ok": True})
                elif self.path == "/api/avatar/options":
                    from shelter_core.avatar import AVATAR
                    try:
                        AVATAR.update_options(owner.config, data.get("options"))
                        self._send(200, {"ok": True})
                    except ValueError as error:
                        self._send(400, {"error": str(error)})
                elif self.path == "/api/avatar/seated":
                    from shelter_core.avatar import AVATAR
                    if type(data.get("seated")) is not bool:
                        self._send(400, {"error": "нужно логическое значение"})
                    else:
                        AVATAR.set_seated(data["seated"])
                        self._send(200, {"ok": True})
                elif self.path == "/api/avatar/resize":
                    from shelter_core import avatar_motion
                    try:
                        reply = avatar_motion.resize(owner.config, scale=data.get("scale"))
                        self._send(200, {"ok": True, "text": reply})
                    except (ValueError, TypeError) as error:
                        self._send(400, {"error": str(error)})
                elif self.path == "/api/avatar/motion":
                    from shelter_core import avatar_motion
                    try:
                        reply = avatar_motion.perform(owner.config, str(data.get("animation") or ""),
                                                      data.get("bpm"), bool(data.get("beat", False)))
                        self._send(200, {"ok": True, "text": reply})
                    except (ValueError, TypeError) as error:
                        self._send(400, {"error": str(error)})
                elif self.path in ("/api/persona", "/api/persona/save", "/api/persona/delete"):
                    from shelter_core import personas
                    from shelter_core import main as core_main
                    try:
                        if self.path == "/api/persona":
                            reply = core_main.switch_persona(owner.config, str(data.get("id") or ""))
                            if data.get("say", True):
                                owner.events.put(("preview", reply))
                            self._send(200, {"ok": True, "active": personas.active()["id"]})
                        elif self.path == "/api/persona/save":
                            saved = personas.save(data.get("persona") or {})
                            if saved["id"] == personas.active()["id"]:
                                core_main.switch_persona(owner.config, saved["id"])
                            self._send(200, {"ok": True, "persona": personas.public(saved)})
                        else:
                            personas.delete(str(data.get("id") or ""))
                            if personas.active_id() == personas.DEFAULT_ID and personas.active()["id"] != personas.DEFAULT_ID:
                                core_main.switch_persona(owner.config, personas.DEFAULT_ID)
                            self._send(200, {"ok": True})
                    except Exception as error:
                        self._send(400, {"error": str(error)})
                elif self.path == "/api/stop":
                    self._send(202, {"ok": True})     # сначала ответ, потом остановка
                    owner.stop_requested.set()
                else:
                    self._send(404, {"error": "нет такого адреса"})

            def _stream_events(self):
                subscriber, recent = bus.subscribe()
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                try:
                    for event in recent:
                        self.wfile.write((json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8"))
                    self.wfile.flush()
                    while not owner.stop_requested.is_set():
                        try:
                            event = subscriber.get(timeout=15)
                        except Exception:
                            event = {"kind": "ping"}      # держать соединение живым
                        self.wfile.write((json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8"))
                        self.wfile.flush()
                except OSError:
                    pass
                finally:
                    bus.unsubscribe(subscriber)

        try:
            self.server = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        except OSError as error:
            print(f">> CONTROL  //  порт {self.port} занят ({error}) — окно приложения не увидит ядро")
            return
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, name="control", daemon=True).start()
        print(f">> CONTROL  //  127.0.0.1:{self.port}")

    def stop(self):
        self.stop_requested.set()
        if self.server:
            self.server.shutdown()
            self.server.server_close()

    def devices(self):
        """Микрофоны того же звукового API, через которое их открывает ядро
        (на Windows — MME: он сам приводит частоту к 32 кГц). Номера совпадают
        с audio.device, поэтому выбор в приложении сразу работает."""
        import sounddevice as sd
        current = (self.config.get("audio") or {}).get("device")
        if isinstance(current, dict):
            current = self.cap.stream.device if self.cap and self.cap.stream else None
        devices = sd.query_devices()
        if isinstance(current, int) and 0 <= current < len(devices):
            api = devices[current]["hostapi"]
        else:
            api = sd.default.hostapi
        default = sd.query_hostapis(api)["default_input_device"]
        result = [{"index": i, "name": d["name"], "default": i == default}
                  for i, d in enumerate(devices)
                  if d["max_input_channels"] > 0 and d["hostapi"] == api
                  and "Переназначение" not in d["name"] and "Sound Mapper" not in d["name"]]
        return {"devices": result, "current": current}

    # ------------------------------------------------- образец голоса для клона

    SAMPLE = os.path.join("data", "voice", "reference.wav")
    SAMPLE_RATE = 24000

    def _save_sample(self, samples, rate, target=""):
        """Моно, 24 кГц, не длиннее 15 с, без тишины по краям -> data/voice/reference.wav
        и расшифровка GigaAM (без неё клон звучит заметно хуже)."""
        from scipy.io import wavfile
        from scipy.signal import resample_poly
        from shelter_core import asr
        samples = np.asarray(samples, dtype=np.float32)
        if samples.ndim > 1:
            samples = samples.mean(axis=1)
        if rate != self.SAMPLE_RATE:
            samples = resample_poly(samples, self.SAMPLE_RATE, rate).astype(np.float32)
        loud = np.flatnonzero(np.abs(samples) > max(0.01, float(np.abs(samples).max()) * 0.05))
        if loud.size < self.SAMPLE_RATE:
            raise RuntimeError("в записи почти нет речи")
        start = max(0, loud[0] - self.SAMPLE_RATE // 5)
        samples = samples[start:min(len(samples), loud[-1] + self.SAMPLE_RATE // 5)][: self.SAMPLE_RATE * 15]
        samples = samples / max(1e-6, float(np.abs(samples).max())) * 0.9
        # Образец для персонажа — отдельный файл: голос Джарвиса не трогаем.
        sample = os.path.join("data", "voice", "persona.wav") if target == "persona" else self.SAMPLE
        path = os.path.join(ROOT, sample)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        wavfile.write(path, self.SAMPLE_RATE, (samples * 32767).astype(np.int16))
        text = ""
        if asr.load(self.config) is not None:
            text = asr.transcribe(resample_poly(samples, 2, 3).astype(np.float32))
        return {"path": sample.replace("\\", "/"), "text": text, "seconds": round(len(samples) / self.SAMPLE_RATE, 1)}

    def _record16k(self, seconds):
        """Записать с микрофона Джарвиса и привести к 16 кГц моно."""
        import sounddevice as sd
        from scipy.signal import resample_poly
        device = (self.config.get("audio") or {}).get("device")
        rate = int(sd.query_devices(device, "input")["default_samplerate"])
        bus.publish("state", text="recording")
        audio = sd.rec(int(seconds * rate), samplerate=rate, channels=1, dtype="float32", device=device)
        sd.wait()
        divisor = np.gcd(16000, rate)
        return resample_poly(audio[:, 0], 16000 // divisor, rate // divisor).astype(np.float32)

    def speaker_action(self, action, seconds):
        """Узнавание хозяина: enroll — запомнить голос, test — узнаёт ли, forget — забыть."""
        from shelter_core import speaker
        if action == "status":
            return {"available": speaker.available(), "enrolled": speaker.enrolled()}
        if action == "forget":
            speaker.forget()
            return {"enrolled": False}
        if not speaker.available():
            raise RuntimeError("модель узнавания голоса не установлена")
        if action == "enroll":
            result = speaker.enroll(self._record16k(max(8.0, min(20.0, seconds or 12.0))))
            return {"enrolled": True, **result}
        if action == "test":
            value = speaker.score(self._record16k(max(2.0, min(8.0, seconds or 4.0))))
            if value is None:
                raise RuntimeError("не расслышал — скажите фразу погромче или подлиннее")
            threshold = float(((self.config.get("wake") or {}).get("owner") or {}).get("threshold", 0.46))
            return {"score": round(value, 2), "owner": value >= threshold, "threshold": threshold}
        raise RuntimeError("неизвестное действие")

    def record_sample(self, seconds, target=""):
        """Записать образец с микрофона Джарвиса."""
        import sounddevice as sd
        seconds = max(5.0, min(20.0, seconds))
        device = (self.config.get("audio") or {}).get("device")
        rate = int(sd.query_devices(device, "input")["default_samplerate"])
        bus.publish("state", text="recording")
        audio = sd.rec(int(seconds * rate), samplerate=rate, channels=1, dtype="float32", device=device)
        sd.wait()
        return self._save_sample(audio[:, 0], rate, target)

    def import_sample(self, source, target=""):
        """Взять образец из файла (WAV, MP3, FLAC, OGG)."""
        if not source or not os.path.isfile(source):
            raise RuntimeError("файл не найден")
        import soundfile
        samples, rate = soundfile.read(source, dtype="float32", always_2d=False)
        return self._save_sample(samples, rate, target)

    def level(self):
        if self.cap is None:
            return {"rms": 0.0, "db": -90.0}
        window = self.cap.get_window(0.0, 0.15)
        rms = float(np.sqrt(np.mean(window ** 2))) if window.size else 0.0
        return {"rms": rms, "db": round(20 * np.log10(rms + 1e-9), 1)}
