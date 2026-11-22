"""Необязательная интеграция Jarvis с VTube Studio.

VTube Studio остаётся владельцем модели, трекинга и always-on-top окна. Jarvis
только запускает программу (по желанию) и вызывает заранее настроенные hotkey:
например, ``jarvis_listening`` и ``jarvis_speaking``. Так работает любая
Live2D-модель, а не одна зашитая в проекте.
"""

import json
import copy
import os
import subprocess
import threading
import uuid
import time


ROOT = os.path.dirname(os.path.abspath(__file__))
TOKEN_PATH = os.path.join(ROOT, "secrets", "vtube_studio_token.json")
DEFAULT_URL = "ws://127.0.0.1:8001"


class AvatarController:
    """Тонкий, необязательный клиент VTube Studio Public API.

    Модуль намеренно не влияет на ассистента, если ``ui.mode`` не равен
    ``vtube_studio`` или библиотека websocket-client не установлена.
    """

    def __init__(self):
        self.config = {}
        self._process = None
        self._lock = threading.Lock()
        self._visible = False
        self._busy = False
        self._last_tick = 0
        self._motion_until = 0
        self._motion_id = ""
        self._seated = False
        self._dialogue_visible = False

    @property
    def enabled(self):
        return self.config.get("mode") in ("vtube_studio", "avatar")

    @property
    def builtin(self):
        """Своё окно персонажа (VRM в приложении «Джарвис») вместо HUD."""
        return self.config.get("mode") == "avatar"

    @property
    def motion_active(self):
        return self.builtin and (self._seated or bool(self._motion_id) and time.monotonic() < self._motion_until)

    def configure(self, config):
        ui = config.get("ui") or {}
        persona = config.get("persona") or {}
        previous = (self.config.get("mode"), (self.config.get("persona") or {}).get("id"),
                    (self.config.get("persona") or {}).get("model"))
        self.config = {
            "mode": ui.get("mode", "hud"),
            "vtube": ui.get("vtube_studio") or {},
            "persona": {"id": persona.get("id"), "name": persona.get("name"),
                        "model": (persona.get("avatar") or {}).get("model", ""),
                        "options": copy.deepcopy({**(persona.get("avatar") or {}), **(ui.get("avatar") or {})}),
                        "always": bool((ui.get("avatar") or {}).get("always", False))},
        }
        import personas
        if ui.get("lite"):
            self.config["persona"]["options"]["fps"] = 24
        for item in self.config["persona"]["options"].get("accessories", []):
            if item.get("file"):
                item["file"] = personas.resolve(persona, item["file"])
        current = (self.config["mode"], self.config["persona"]["id"], self.config["persona"]["model"])
        if previous != current:
            self._seated = False
            import avatar_motion
            import bus
            avatar_motion.BEAT.stop()
            self._motion_until = 0
            self._motion_id = ""
            bus.publish("avatar_motion", animation="stop")
        self._last_tick = 0
        self.tick(config)
        if self.builtin and self.config["persona"]["always"]:
            self.start(dialogue=False)
        elif not self.builtin:
            self._publish("hide")
        vtube = self.config["vtube"]
        if self.enabled and vtube.get("autostart"):
            self.start()

    def update_options(self, config, options):
        allowed = {"always", "click_through", "hide_busy"}
        if not isinstance(options, dict) or not options or set(options) - allowed or any(type(v) is not bool for v in options.values()):
            raise ValueError("настройки окна: always, click_through, hide_busy — логические значения")
        config.setdefault("ui", {}).setdefault("avatar", {}).update(options)
        self.refresh_options(config)

    def refresh_options(self, config):
        self.configure(config)
        if self.builtin:
            self._publish("hide" if self._busy or not self._visible else "show")

    def _publish(self, state):
        import bus
        if state == "hide":
            import plugin_extensions
            plugin_extensions.react("hide")  # invalidate an in-flight reaction
        bus.publish("avatar", state=state, **self.config.get("persona", {}))

    def tick(self, config):
        """Не закрывать диалог из-за скрытия модели поверх полноэкранного приложения."""
        import time
        if not self.builtin or time.monotonic() - self._last_tick < 1:
            return
        self._last_tick = time.monotonic()
        if self._motion_id and time.monotonic() >= self._motion_until:
            self._motion_id = ""
            import bus
            import avatar_motion
            avatar_motion.BEAT.stop()
            bus.publish("avatar_motion", animation="stop", preserve_seat=self._seated)
        if self._visible and not self._seated and not self._dialogue_visible and not self.config["persona"]["always"] and time.monotonic() >= self._motion_until:
            self._visible = False
            self._publish("hide")
        import gaming
        busy = bool(self.config["persona"]["options"].get("hide_busy", True)) and gaming.busy(config)
        if busy != self._busy:
            self._busy = busy
            self._publish("hide" if busy else "show" if self._visible else "hide")

    def hold_motion(self, seconds, motion_id=""):
        self._motion_id = motion_id
        self._motion_until = time.monotonic() + seconds
        self._visible = self._seated or self._motion_until > time.monotonic() or self._dialogue_visible or self.config["persona"]["always"]
        if self._visible and not self._busy:
            self._publish("show")
        elif not self._visible:
            self._publish("hide")

    def set_seated(self, value):
        self._seated = bool(value)
        if value:
            self._visible = True
            if not self._busy:
                self._publish("show")

    def finish_motion(self, motion_id):
        if motion_id and motion_id == self._motion_id:
            self.hold_motion(0)

    def hide(self):
        if self.builtin and not self.config["persona"]["always"]:
            self._dialogue_visible = False
            if self._seated or time.monotonic() < self._motion_until:
                return
            self._visible = False
            self._publish("hide")

    def dismiss(self):
        """«Исчезни»: убрать персонажа сразу — даже «всегда на экране», сидящего
        или посреди танца. Вернётся при следующем обращении или «появись»."""
        if not self.builtin:
            return
        import avatar_motion
        avatar_motion.BEAT.stop()
        self._motion_until = 0
        self._motion_id = ""
        self._dialogue_visible = False
        self._visible = False
        self._publish("hide")

    def start(self, dialogue=True):
        """Запустить VTube Studio, если путь задан и процесса ещё нет."""
        if not self.enabled:
            return False
        if self.builtin:
            self._dialogue_visible = self._dialogue_visible or dialogue
            self._visible = True
            if not self._busy:
                self._publish("show")
            return True
        if self._process is not None and self._process.poll() is None:
            return True
        path = self.config["vtube"].get("path")
        if not path:
            print("[avatar] укажите путь к VTubeStudio.exe в настройках")
            return False
        if not os.path.isfile(path):
            print(f"[avatar] не найден VTube Studio: {path}")
            return False
        self._process = subprocess.Popen(
            [path], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        print("[avatar] VTube Studio запущен")
        return True

    def _load_token(self):
        try:
            with open(TOKEN_PATH, encoding="utf-8") as file:
                return json.load(file).get("token", "")
        except (OSError, ValueError):
            return ""

    def _save_token(self, token):
        os.makedirs(os.path.dirname(TOKEN_PATH), exist_ok=True)
        with open(TOKEN_PATH, "w", encoding="utf-8") as file:
            json.dump({"token": token}, file)

    @staticmethod
    def _request(socket, message_type, data=None):
        request = {
            "apiName": "VTubeStudioPublicAPI",
            "apiVersion": "1.0",
            "requestID": str(uuid.uuid4()),
            "messageType": message_type,
        }
        if data is not None:
            request["data"] = data
        socket.send(json.dumps(request))
        response = json.loads(socket.recv())
        if response.get("messageType") == "APIError":
            error = response.get("data", {}).get("message", "неизвестная ошибка")
            raise RuntimeError(error)
        return response.get("data") or {}

    def _authenticated_socket(self):
        try:
            import websocket
        except ImportError as error:
            raise RuntimeError("установите websocket-client для VTube Studio") from error

        vtube = self.config["vtube"]
        socket = websocket.create_connection(vtube.get("url", DEFAULT_URL), timeout=2)
        token = self._load_token()
        if not token:
            # VTube Studio покажет одноразовый диалог доверия к плагину.
            data = self._request(socket, "AuthenticationTokenRequest", {
                "pluginName": "Jarvis",
                "pluginDeveloper": "Jarvis contributors",
                "pluginIcon": "",
            })
            token = data.get("authenticationToken", "")
            if not token:
                socket.close()
                raise RuntimeError("VTube Studio не выдал токен плагина")
            self._save_token(token)

        data = self._request(socket, "AuthenticationRequest", {
            "pluginName": "Jarvis",
            "pluginDeveloper": "Jarvis contributors",
            "pluginIcon": "",
            "authenticationToken": token,
        })
        if not data.get("authenticated"):
            socket.close()
            raise RuntimeError("VTube Studio отклонил токен Jarvis")
        return socket

    def trigger(self, reaction):
        """Выполнить именованный hotkey текущей модели без остановки Jarvis."""
        if not self.enabled:
            return False
        if self.builtin:
            if not self._busy and self._visible:
                self._publish(reaction)
                if self.config["persona"]["options"].get("reactions", True):
                    import plugin_extensions
                    plugin_extensions.react(reaction)
            return True
        hotkey = self.config["vtube"].get("reactions", {}).get(reaction)
        if not hotkey:
            return False
        with self._lock:
            socket = None
            try:
                socket = self._authenticated_socket()
                self._request(socket, "HotkeyTriggerRequest", {"hotkeyID": hotkey})
                return True
            except Exception as error:
                print(f"[avatar] реакция {reaction} не отправлена: {error}")
                return False
            finally:
                if socket is not None:
                    socket.close()


AVATAR = AvatarController()

