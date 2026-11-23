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
import queue
import tempfile
import threading
import urllib.parse
import urllib.request
import uuid

from shelter_core import companion_devices as devices

ROOT = ROOT_DIR
STATE = os.path.join(ROOT, "data", "telegram_state.json")
API = "https://api.telegram.org"
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
        self.pending = {}
        self.confirmations = {}
        self.completed = queue.SimpleQueue()
        self.lock = threading.Lock()
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
            print(f"[telegram] не отправить: {type(error).__name__}")

    # --------------------------------------------------------- входящие
    def handle(self, update):
        """Одно обновление Telegram. Возвращает, что сделано (для тестов)."""
        if "callback_query" in update:
            return "устаревшая кнопка"
        message = update.get("message") or {}
        chat = (message.get("chat") or {}).get("id")
        if chat is None:
            return "пусто"
        if (message.get("chat") or {}).get("type", "private") != "private":
            return "чужой"
        text = str(message.get("text") or "").strip()
        sender = message.get("from") or {}
        if text.startswith("/start"):
            code = text.removeprefix("/start").strip()
            try:
                devices.pair_chat(code, chat, "Telegram " + (sender.get("username") or sender.get("first_name") or ""))
            except ValueError as error:
                self.send(chat, f"Не подключено: {error}. Код — в окне Джарвиса: Подключения → Telegram.")
                return "код неверный"
            self.send(chat, "Подключено. Пишите или отправляйте голосовые. /help — команды и настройки.")
            return "подключено"
        device = devices.chat_device(chat)
        if device is None:
            self.send(chat, "Этот чат не подключён к Джарвису. Получите код в окне Джарвиса и отправьте «/start код».")
            return "чужой"
        if text == "/stop":
            with self.lock:
                running = self.pending.get(chat)
                if running:
                    running["cancelled"].set()
                if chat in self.confirmations:
                    self.confirmations[chat][1].clear()
            if running:
                self.events.put(("telegram_stop", (device["id"], running["id"])))
            self.send(chat, "Запросил остановку вашей задачи." if running else "В этом чате нет задачи.")
            return "стоп"
        if text == "/status":
            self.send(chat, self.status())
            return "статус"
        if text == "/help":
            self.send(chat, "/status — состояние\n/stop — остановить свой запрос\n/scenarios — список сценариев\n/run ID — запустить сценарий\n/voice on или off — голосовые ответы\n/notify on или off — уведомления о таймерах и напоминаниях ПК")
            return "помощь"
        if text == "/scenarios":
            from shelter_core import scenarios
            items = [item for item in scenarios.load(self.config) if item.get("enabled", True)]
            self.send(chat, "\n".join(f"{item['name']} · /run {item['id']}" for item in items[:30]) or "Нет доступных сценариев.")
            return "сценарии"
        if text in ("/voice on", "/voice off"):
            self.state.setdefault("voice", {})[device["id"]] = text.endswith(" on")
            _save_state(self.state)
            self.send(chat, "Добавлю голос к тексту ответа." if text.endswith(" on") else "Ответы будут текстовыми.")
            return "голос"
        if text in ("/notify on", "/notify off"):
            with self.lock:
                self.state.setdefault("notify", {})[device["id"]] = text.endswith(" on")
                _save_state(self.state)
            self.send(chat, "Таймеры и напоминания ПК будут приходить сюда." if text.endswith(" on") else "Уведомления выключены.")
            return "уведомления"
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
        device = devices.chat_device(chat)
        if not device:
            return "чужой"
        from shelter_core import assistant_store as store
        from shelter_core import policy, remote_audio

        with self.lock:
            if chat in self.pending:
                request = None
            else:
                request = {"id": uuid.uuid4().hex, "cancelled": threading.Event()}
                self.pending[chat] = request
                known = self.confirmations.get(chat)
                if not known or known[0] != device["id"]:
                    self.confirmations[chat] = (device["id"], policy.Confirmations())
                confirm = self.confirmations[chat][1]
        if request is None:
            self.send(chat, "Сначала дождитесь ответа или отправьте /stop.")
            return "занят"
        owner = (device["id"], request["id"])
        target = None
        if self.state.get("voice", {}).get(owner[0]):
            try:
                remote_audio.open_stream(*owner)
                target = dict(zip(("device", "request"), owner))
            except ValueError:
                pass

        def paired():
            return (devices.chat_device(chat) or {}).get("id") == owner[0]

        def complete(reply, error, status):
            with self.lock:
                if self.pending.get(chat) is request:
                    self.pending.pop(chat)
            self.completed.put((chat, paired, target, reply, error, status))

        delivery = {"owner": owner, "complete": complete, "confirmations": confirm,
                    "active": lambda: paired() and not request["cancelled"].is_set()}
        try:
            session = store.paired_session(owner[0])
            self.events.put(("typed", {"text": text[:16000], "session_id": session,
                                       "delivery": delivery, "remote": target}))
        except Exception:
            remote_audio.finish_target(target)
            complete("", "Не удалось создать запрос.", "failed")
        return "передано"

    def transcribe(self, voice):
        """Голосовое Telegram (OGG/Opus) -> текст тем же распознаванием, что и микрофон."""
        try:
            info = self.call("getFile", wait=15, file_id=voice["file_id"])
            if int(info.get("file_size") or 0) > 5_000_000:
                return ""
            with urllib.request.urlopen(f"{API}/file/bot{self.token}/{info['file_path']}", timeout=30) as response:
                raw = response.read(5_000_001)
            if len(raw) > 5_000_000:
                return ""
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
            print(f"[telegram] голосовое не распознано: {type(error).__name__}")
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
    def send_voice(self, chat, target):
        import base64
        import io
        import math
        from itertools import groupby
        import numpy as np
        import soundfile
        from scipy.signal import resample_poly
        from shelter_core import remote_audio

        chunks = []
        cursor = 0
        while True:
            result = remote_audio.read(target["device"], target["request"], after=cursor, wait=0)
            if result.get("error"):
                return
            chunks.extend(result["chunks"])
            if result["done"]:
                break
            if result["after"] == cursor:
                return
            cursor = result["after"]
        if not chunks:
            return
        audio = []
        for rate, batch in groupby(chunks, key=lambda chunk: chunk["rate"]):
            raw = b"".join(base64.b64decode(chunk["pcm"]) for chunk in batch)
            samples = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768
            divisor = math.gcd(rate, 48000)
            audio.append(resample_poly(samples, 48000 // divisor, rate // divisor))
        output = io.BytesIO()
        soundfile.write(output, np.concatenate(audio), 48000, format="OGG", subtype="OPUS")
        boundary = uuid.uuid4().hex
        prefix = (f'--{boundary}\r\nContent-Disposition: form-data; name="chat_id"\r\n\r\n{chat}\r\n'
                  f'--{boundary}\r\nContent-Disposition: form-data; name="voice"; filename="shelter.ogg"\r\n'
                  'Content-Type: audio/ogg\r\n\r\n').encode()
        payload = prefix + output.getvalue() + f"\r\n--{boundary}--\r\n".encode()
        request = urllib.request.Request(f"{API}/bot{self.token}/sendVoice", data=payload,
                                         headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        with urllib.request.urlopen(request, timeout=20) as response:
            response.read(65_536)

    # ------------------------------------------------------------- потоки
    def poll(self):
        while not self.stop_event.is_set():
            try:
                # Длинный опрос: Telegram держит запрос до 25 с, пока нет сообщений.
                updates = self.call("getUpdates", wait=40, offset=int(self.state.get("offset", 0)) + 1, timeout=25,
                                    allowed_updates=["message", "callback_query"])
            except Exception as error:
                print(f"[telegram] нет связи: {type(error).__name__}")
                self.stop_event.wait(10)
                continue
            for update in updates:
                # Сначала сдвигаем offset и сохраняем: при сбое обработки повтора всё равно не будет.
                self.state["offset"] = max(int(self.state.get("offset", 0)), int(update["update_id"]))
                _save_state(self.state)
                try:
                    self.handle(update)
                except Exception as error:
                    print(f"[telegram] сообщение не обработано: {type(error).__name__}")

    def deliver(self):
        while not self.stop_event.is_set():
            try:
                chat, paired, target, reply, error, status = self.completed.get(timeout=1)
            except queue.Empty:
                continue
            if not paired():
                continue
            message = "Задача остановлена." if status == "cancelled" else error or reply or "Готово."
            self.send(chat, message)
            if target and status == "done" and paired():
                try:
                    self.send_voice(chat, target)
                except Exception as voice_error:
                    print(f"[telegram] голос не отправлен: {type(voice_error).__name__}")

    def reminder(self, item, missed):
        prefix = "Пропущено: " if missed else ""
        subject = "Таймер" if item.get("kind") == "timer" else "Напоминание"
        label = (item.get("label") or "").strip()
        message = prefix + subject + (f" · {label}" if label else "")
        with self.lock:
            enabled = self.state.get("notify", {}).copy()
        for device in devices.devices():
            if device["kind"] == "telegram" and not device["revoked"] and enabled.get(device["id"]):
                chat, owner = device["chat"], device["id"]

                def paired(chat=chat, owner=owner):
                    with self.lock:
                        active = self.state.get("notify", {}).get(owner)
                    return active and (devices.chat_device(chat) or {}).get("id") == owner

                self.completed.put((chat, paired, None, message, "", "done"))

    def start(self):
        for target, name in ((self.poll, "telegram"), (self.deliver, "telegram-out")):
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


def reminder(item, missed):
    if _bot is not None:
        _bot.reminder(item, missed)


def check(token):
    """Проверка ключа бота из окна: имя бота, без сохранения."""
    bot = Bot({"telegram": {"token": token}}, None)
    me = bot.call("getMe", wait=10)
    return {"ok": True, "text": f"Бот @{me.get('username')} отвечает. Получите код и отправьте ему «/start код»."}
