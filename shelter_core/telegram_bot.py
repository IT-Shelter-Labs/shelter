"""Свой Telegram-бот Джарвиса: просьбы текстом и голосом, подтверждения, статус, остановка.

Канал идёт через серверы Telegram, а выполняет всё ваш компьютер — он должен
быть включён. Бота создаёте вы у @BotFather; ключ бота хранится в настройках.
Слушает только сопряжённых владельцев: в окне Джарвиса получите код и
отправьте боту «/start 123456». Отозванный чат и чужие люди ничего не выполняют.

Повтор одного сообщения (Telegram переотправил после обрыва, перезапуск ядра)
не выполняется дважды: номер последнего обработанного обновления хранится
на диске, а сообщения фильтруются по update_id.
"""

from shelter_core.paths import ROOT_DIR

import json
import os
import tempfile
import threading
import time
import urllib.parse
import urllib.request

from shelter_core import bus
from shelter_core import companion_devices as devices

ROOT = ROOT_DIR
STATE = os.path.join(ROOT, "data", "telegram_state.json")
API = "https://api.telegram.org"
ANSWER_WINDOW = 180          # сколько ждать ответа на просьбу, чтобы отправить его в чат

_bot = None


def _load_state():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"offset": 0}


def _save_state(state):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=os.path.dirname(STATE), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(state, f)
    os.replace(temporary, STATE)


class Bot:
    def __init__(self, config, events):
        self.config = config
        self.events = events
        self.token = str(((config.get("telegram") or {}).get("token")) or os.environ.get("JARVIS_TELEGRAM_TOKEN", ""))
        self.state = _load_state()
        self.stop_event = threading.Event()
        self.waiting = {}         # chat -> время последней просьбы: туда идут ответы и итоги
        self.threads = []

    # ------------------------------------------------------------- Bot API
    def call(self, method, wait=35, **params):
        data = urllib.parse.urlencode({k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v)
                                       for k, v in params.items()}).encode()
        request = urllib.request.Request(f"{API}/bot{self.token}/{method}", data=data)
        with urllib.request.urlopen(request, timeout=wait) as response:
            reply = json.loads(response.read())
        if not reply.get("ok"):
            raise RuntimeError(reply.get("description") or "Telegram ответил ошибкой")
        return reply["result"]

    def send(self, chat, text, buttons=None):
        params = {"chat_id": chat, "text": text[:4000]}
        if buttons:
            params["reply_markup"] = {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in buttons]]}
        try:
            self.call("sendMessage", wait=15, **params)
        except Exception as error:
            print(f"[telegram] не отправить: {error}")

    # --------------------------------------------------------- входящие
    def handle(self, update):
        """Одно обновление Telegram. Возвращает, что сделано (для тестов)."""
        if "callback_query" in update:
            query = update["callback_query"]
            chat = query["message"]["chat"]["id"]
            if devices.chat_device(chat) is None:
                return "чужой"
            try:
                self.call("answerCallbackQuery", wait=10, callback_query_id=query["id"])
            except Exception:
                pass
            return self.request(chat, {"yes": "да", "no": "нет"}.get(query.get("data"), ""))
        message = update.get("message") or {}
        chat = (message.get("chat") or {}).get("id")
        if chat is None:
            return "пусто"
        text = str(message.get("text") or "").strip()
        sender = message.get("from") or {}
        if text.startswith("/start"):
            code = text.removeprefix("/start").strip()
            try:
                devices.pair_chat(code, chat, "Telegram " + (sender.get("username") or sender.get("first_name") or ""))
            except ValueError as error:
                self.send(chat, f"Не подключено: {error}. Код — в окне Джарвиса: Подключения → Telegram.")
                return "код неверный"
            self.send(chat, "Подключено. Пишите или отправляйте голосовые — выполнит ваш компьютер. /stop — остановить, /status — состояние.")
            return "подключено"
        device = devices.chat_device(chat)
        if device is None:
            self.send(chat, "Этот чат не подключён к Джарвису. Получите код в окне Джарвиса и отправьте «/start код».")
            return "чужой"
        if text == "/stop":
            self.events.put(("interrupt", None))
            self.send(chat, "Остановил текущую задачу.")
            return "стоп"
        if text == "/status":
            self.send(chat, self.status())
            return "статус"
        if message.get("voice") and (self.config.get("telegram") or {}).get("voice", True):
            text = self.transcribe(message["voice"])
            if not text:
                self.send(chat, "Не разобрал голосовое — попробуйте ещё раз или напишите текстом.")
                return "не разобрал"
            self.send(chat, f"Услышал: «{text}»")
        if not text:
            return "пусто"
        return self.request(chat, text)

    def request(self, chat, text):
        if not text:
            return "пусто"
        from shelter_core import assistant_store as store
        self.waiting[chat] = time.time()
        self.events.put(("typed", {"text": text[:16000], "session_id": store.session_for()}))
        return "передано"

    def transcribe(self, voice):
        """Голосовое Telegram (OGG/Opus) -> текст тем же распознаванием, что и микрофон."""
        try:
            info = self.call("getFile", wait=15, file_id=voice["file_id"])
            if int(info.get("file_size") or 0) > 5_000_000:
                return ""
            with urllib.request.urlopen(f"{API}/file/bot{self.token}/{info['file_path']}", timeout=30) as response:
                raw = response.read()
            import io
            import numpy as np
            import soundfile
            from shelter_core import asr
            samples, rate = soundfile.read(io.BytesIO(raw), dtype="float32", always_2d=False)
            if samples.ndim > 1:
                samples = samples.mean(axis=1)
            if rate != 16000:
                from scipy.signal import resample_poly
                divisor = int(np.gcd(16000, rate))
                samples = resample_poly(samples, 16000 // divisor, rate // divisor).astype(np.float32)
            return asr.transcribe(samples)
        except Exception as error:
            print(f"[telegram] голосовое не распознано: {error}")
            return ""

    def status(self):
        from shelter_core.audio import LISTENING, SPEAKING, THINKING
        state = "говорит" if SPEAKING.is_set() else "думает" if THINKING.is_set() else "слушает" if LISTENING.is_set() else "ждёт"
        try:
            from shelter_core import scenarios
            last = scenarios.recent()[:1]
        except Exception:
            last = []
        text = f"Джарвис в сети, сейчас {state}."
        if last:
            text += f"\nПоследний сценарий: «{last[0]['name']}» — {last[0]['status']}"
        return text

    # ------------------------------------------------- исходящие (итоги)
    def forward(self, event):
        now = time.time()
        chats = [c for c, t in self.waiting.items() if now - t < ANSWER_WINDOW]
        if not chats:
            return
        kind = event.get("kind")
        text, buttons = "", None
        if kind == "reply":
            text = event.get("text") or ""
            from shelter_core.policy import CONFIRMATIONS
            if CONFIRMATIONS.active():
                buttons = [("Да", "yes"), ("Нет", "no")]
        elif kind == "scenario" and not event.get("step") and event.get("status") in ("done", "partial", "failed", "cancelled", "skipped"):
            labels = {"done": "выполнено", "partial": "выполнено с ошибками", "failed": "не выполнено", "cancelled": "остановлено", "skipped": "не запущено"}
            text = f"«{event.get('name')}»: {labels[event['status']]}" + (f" — {event['error']}" if event.get("error") else "")
        elif kind == "error":
            text = "Ошибка: " + str(event.get("text") or "")
        if text:
            for chat in chats:
                self.send(chat, text, buttons)

    # ------------------------------------------------------------- потоки
    def poll(self):
        while not self.stop_event.is_set():
            try:
                # Длинный опрос: Telegram держит запрос до 25 с, пока нет сообщений.
                updates = self.call("getUpdates", wait=40, offset=int(self.state.get("offset", 0)) + 1, timeout=25,
                                    allowed_updates=["message", "callback_query"])
            except Exception as error:
                print(f"[telegram] нет связи: {error}")
                self.stop_event.wait(10)
                continue
            for update in updates:
                # Сначала сдвигаем offset и сохраняем: при сбое обработки повтора всё равно не будет.
                self.state["offset"] = max(int(self.state.get("offset", 0)), int(update["update_id"]))
                _save_state(self.state)
                try:
                    self.handle(update)
                except Exception as error:
                    print(f"[telegram] сообщение не обработано: {error}")

    def listen_bus(self):
        subscriber, _recent = bus.subscribe()
        try:
            while not self.stop_event.is_set():
                try:
                    event = subscriber.get(timeout=1)
                except Exception:
                    continue
                self.forward(event)
        finally:
            bus.unsubscribe(subscriber)

    def start(self):
        for target, name in ((self.poll, "telegram"), (self.listen_bus, "telegram-out")):
            thread = threading.Thread(target=target, name=name, daemon=True)
            thread.start()
            self.threads.append(thread)

    def stop(self):
        self.stop_event.set()


def start(config, events):
    global _bot
    cfg = config.get("telegram") or {}
    if not cfg.get("enabled") or not (cfg.get("token") or os.environ.get("JARVIS_TELEGRAM_TOKEN")) or _bot is not None:
        return None
    _bot = Bot(config, events)
    _bot.start()
    print(">> TELEGRAM  //  бот слушает сопряжённые чаты")
    return _bot


def stop():
    global _bot
    if _bot is not None:
        _bot.stop()
        _bot = None


def check(token):
    """Проверка ключа бота из окна: имя бота, без сохранения."""
    bot = Bot({"telegram": {"token": token}}, None)
    me = bot.call("getMe", wait=10)
    return {"ok": True, "text": f"Бот @{me.get('username')} отвечает. Получите код и отправьте ему «/start код»."}
