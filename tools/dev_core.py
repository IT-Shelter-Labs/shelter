"""Тестовый стенд ядра для разработки окна в браузере (npm run dev:bridge).

Настоящий ControlServer, настоящие сценарии, маршрутизатор, наборы и проверки
подключений, но без микрофона, распознавания и синтеза голоса. Действия шагов
не выполняются, а печатаются, так что «Пробный запуск» ничего не открывает.
Данные — в отдельной папке (первый аргумент): сценарии, резервные копии и
настройки окна не трогают data/ пользователя; копируются только для чтения.

    .venv/Scripts/python tools/dev_core.py <папка-стенда> [порт=8771]
"""

import json
import os
import queue
import shutil
import sys
import threading
import time
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
SANDBOX = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "logs", "dev-core"))
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8771
os.makedirs(SANDBOX, exist_ok=True)

from shelter_core import netfix  # noqa: F401,E402
from shelter_core import bus  # noqa: E402
from shelter_core import main  # noqa: E402
from shelter_core import actions  # noqa: E402
from shelter_core import scenarios  # noqa: E402
from shelter_core import triggers  # noqa: E402
from shelter_core import tasks  # noqa: E402
from shelter_core import secrets_store  # noqa: E402
from shelter_core import assistant_store  # noqa: E402
from shelter_core import personas  # noqa: E402
from shelter_core import control as control_module  # noqa: E402
from shelter_core.control import ControlServer  # noqa: E402

settings_copy = os.path.join(SANDBOX, "settings.json")
if not os.path.exists(settings_copy) and os.path.exists(main.SETTINGS_PATH):
    shutil.copy(main.SETTINGS_PATH, settings_copy)
main.SETTINGS_PATH = settings_copy
assistant_store.PATH = Path(SANDBOX) / 'assistant.sqlite3'
control_module.TOKEN_PATH = os.path.join(SANDBOX, 'control.token')
personas.USER_DIR = os.path.join(SANDBOX, 'personas')
personas.ACTIVE_PATH = os.path.join(SANDBOX, 'persona.json')
scenarios.STORE = os.path.join(SANDBOX, "scenarios.json")
scenarios.BACKUPS = os.path.join(SANDBOX, "backups")
triggers.STATE = os.path.join(SANDBOX, "triggers.json")
from shelter_core import companion_devices  # noqa: E402
from shelter_core import plugins_manager  # noqa: E402
companion_devices.STORE = os.path.join(SANDBOX, "companion_devices.json")
plugins_manager.DIR = os.path.join(SANDBOX, "plugins")
plugins_manager.STATE = os.path.join(SANDBOX, "plugins", "state.json")

config = main.load_config()
config.setdefault("control", {})["port"] = PORT
personas.apply(config)


def fake_persona(current_config, persona_id):
    persona = personas.get(persona_id)
    if persona is None:
        raise ValueError('нет такого персонажа')
    personas.apply(current_config, persona)
    personas._save_active(persona_id)
    bus.publish('persona', persona=personas.public(persona))
    return persona.get('switch_reply') or persona['name']


main.switch_persona = fake_persona


def fake_tool(name, arg):
    print(f"[стенд] инструмент {name}: {arg}")
    time.sleep(0.4)
    if name == "app" and "нет-такой" in arg:
        return "fail", f"Не нашёл программу «{arg}»"
    return "done", arg


real_run_action = actions.run_action


def fake_action(action):
    kind = action.get("type")
    if kind == "scenario":
        return real_run_action(action)
    print(f"[стенд] действие {kind}: {json.dumps(action, ensure_ascii=False)[:160]}")
    tasks.check()
    time.sleep(0.3)


actions.run_action = fake_action

# Шаги, которые исполнитель сценариев делает сам (громкость, клавиши, окна, медиа),
# на стенде тоже только печатаются: проверка окна не должна трогать компьютер.
real_run_step = scenarios._run_step
SAFE = {"wait", "scenario", "say", "overlay", "close", "ask", "tool", "plugin", "if", "repeat"}


def fake_step(step, context):
    if step.get("type") in SAFE:
        return real_run_step(step, context)
    print(f"[стенд] шаг {step.get('type')}: {json.dumps(step, ensure_ascii=False)[:160]}")
    tasks.check()
    time.sleep(0.3)
    return "стенд: не выполнялось"


scenarios._run_step = fake_step
scenarios.configure(config, run_tool=fake_tool, switch_persona=lambda pid: fake_persona(config, pid))

events = queue.Queue()
runner = actions.ActionRunner()
main.RUNNER = runner
state = {"listening": False, "speaking": False, "thinking": False}


def status():
    return {"version": "0.1.0-alpha.1-dev", **state, "voice": "piper", "clone_ready": None, "asr": "gigaam",
            "wake_engine": "kws", "persona": personas.public(personas.active()),
            "echo": None, "llm": {"enabled": True, "model": "стенд", "provider": "ollama"}, "in_game": False,
            "mic": "Микрофон (стенд)", "wake_word": config['wake']['words'][0], "workers": {"vosk": {"state": "running", "error": ""}},
            "confirming": False, "executing": runner._current is not None, "task": runner.current_label,
            "queued": runner._jobs.qsize(), "recognizing": False, "platform": sys.platform}


class Cap:          # индикатор уровня микрофона в окне: на стенде — тишина
    stream = None
    echo = None
    sample_rate = 16000
    buffer_len = 64000

    def get_window(self, before, after):
        import numpy as np
        return np.zeros(int((before + after) * self.sample_rate), dtype=np.float32)


control = ControlServer(config, events, Cap(), status)
control.start()
triggers.start(events, config)


class Dev(BaseHTTPRequestHandler):
    """Настройки окна (вместо Rust): config.yaml + копия settings.json стенда."""

    def log_message(self, *args):
        pass

    def _send(self, payload):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        import yaml
        with open(os.path.join(ROOT, "config.yaml"), encoding="utf-8") as f:
            defaults = yaml.safe_load(f) or {}
        try:
            with open(settings_copy, encoding="utf-8") as f:
                user = secrets_store.decode(json.load(f))
        except (OSError, ValueError):
            user = {}
        user["onboarded"] = True
        self._send({"defaults": defaults, "user": user})

    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        with open(settings_copy, "w", encoding="utf-8") as f:
            json.dump(data.get("user") or {}, f, ensure_ascii=False, indent=2)
        self._send({"ok": True})


dev = ThreadingHTTPServer(("127.0.0.1", PORT + 1), Dev)
threading.Thread(target=dev.serve_forever, daemon=True).start()
print(f">> DEV CORE  //  127.0.0.1:{PORT} (настройки {PORT + 1}), данные: {SANDBOX}", flush=True)

while True:
    kind, payload = events.get()
    if kind == "scenario":
        item = scenarios.get(str(payload.get("id", "")))
        if item:
            runner.submit([{"type": "scenario", "id": item["id"], "source": payload.get("source", "кнопка"),
                            "run": payload.get("run"), "speak_errors": False}], key="scenario:" + item["id"], label=item["name"])
    elif kind == "interrupt":
        runner.cancel_current()
        scenarios.cancel()
    elif kind in ("typed", "ask"):
        text = payload.get("text") if isinstance(payload, dict) else str(payload)
        bus.publish("query", text=text, session_id=(payload or {}).get("session_id") if isinstance(payload, dict) else None)
        state["thinking"] = True
        time.sleep(0.6)
        state["thinking"] = False
        bus.publish("reply", text=f"Стенд: получил «{text}». Настоящее ядро ответило бы здесь.",
                    session_id=(payload or {}).get("session_id") if isinstance(payload, dict) else None)
    elif kind == "command":
        print(f"[стенд] команда: {payload.get('description')}")
