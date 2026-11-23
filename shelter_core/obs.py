"""OBS по голосу: «сохрани момент», «начни запись», «останови запись».

Работает через obs-websocket — он встроен в OBS 28 и новее. Включить:
OBS -> Сервис -> Настройки сервера WebSocket -> «Включить сервер», пароль
положить в переменную окружения OBS_PASSWORD (или выключить там аутентификацию).
«Сохрани момент» сохраняет буфер повтора: его нужно один раз включить в
OBS (Настройки -> Вывод -> Буфер повтора); если он выключен, Джарвис включит сам.

Трансляцию голосом не запускаем нарочно: ошибка распознавания не должна
выводить человека в эфир.
"""

import base64
import hashlib
import json
import os
import re
import time
import uuid

ACTIONS = {
    "replay": "SaveReplayBuffer",
    "record": "StartRecord",
    "stop": "StopRecord",
    "pause": "ToggleRecordPause",
    "pause_record": "PauseRecord",
    "resume": "ResumeRecord",
}
WORDS = {  # что может написать модель -> действие; порядок важен: «останови запись» — это stop
    "stop": "stop", "останов": "stop", "стоп": "stop", "законч": "stop", "выключи": "stop",
    "pause": "pause", "пауз": "pause",
    "replay": "replay", "момент": "replay", "повтор": "replay", "клип": "replay", "save": "replay",
    "сохрани": "replay",
    "record": "record", "запис": "record", "start": "record", "начни": "record",
}
NOT_RUNNING = 501          # код obs-websocket: вывод (запись, буфер) не запущен
ALREADY_RUNNING = 500
OUTPUT_DISABLED = 604


class ObsError(RuntimeError):
    pass


def _auth(password, auth):
    secret = base64.b64encode(hashlib.sha256((password + auth["salt"]).encode()).digest()).decode()
    return base64.b64encode(hashlib.sha256((secret + auth["challenge"]).encode()).digest()).decode()


class Client:
    def __init__(self, cfg):
        import websocket
        url = cfg.get("url", "ws://127.0.0.1:4455")
        self.events = {}
        try:
            self.ws = websocket.create_connection(url, timeout=3)
        except (OSError, websocket.WebSocketException, ValueError) as error:
            raise ObsError("OBS не отвечает — он запущен и включён сервер WebSocket?") from error
        try:
            self.identify(cfg)
        except Exception:
            self.close()
            raise

    def receive(self):
        from websocket import WebSocketException
        try:
            message = json.loads(self.ws.recv())
        except (ValueError, OSError, RuntimeError, WebSocketException) as error:
            raise ObsError("Связь с OBS прервалась.") from error
        if message.get("op") == 5:
            event = message.get("d") or {}
            self.events[event.get("eventType")] = event.get("eventData") or {}
        return message

    def identify(self, cfg):
        hello = self.receive()
        identify = {"rpcVersion": 1, "eventSubscriptions": 64}  # Outputs
        auth = (hello.get("d") or {}).get("authentication")
        if auth:
            password = os.environ.get(cfg.get("password_env", "OBS_PASSWORD"), "") or cfg.get("password", "")
            if not password:
                raise ObsError("OBS просит пароль: положите его в переменную OBS_PASSWORD")
            identify["authentication"] = _auth(password, auth)
        self.ws.send(json.dumps({"op": 1, "d": identify}))
        try:
            reply = self.receive()
        except Exception as error:
            raise ObsError("OBS не принял пароль") from error
        if reply.get("op") != 2:
            raise ObsError("OBS не принял подключение")

    def request(self, kind, data=None):
        request_id = uuid.uuid4().hex
        payload = {"requestType": kind, "requestId": request_id}
        if data:
            payload["requestData"] = data
        self.ws.send(json.dumps({"op": 6, "d": payload}))
        while True:
            message = self.receive()
            if message.get("op") == 7 and message["d"].get("requestId") == request_id:
                status = message["d"]["requestStatus"]
                return status.get("result", False), status.get("code", 0), message["d"].get("responseData") or {}

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def parse(text):
    text = str(text).strip().lower()
    for word, action in WORDS.items():
        if word in text:
            return action
    return None


def voice_action(question):
    body = re.sub(r"\s+[вис]?\s*(?:obs|обс)(?: studio)?[.?!]*$", "", question.strip(), flags=re.I)
    if body == question.strip():
        return None
    names = (
        (r"(?:статус|состояние)(?: записи)?", "status"),
        (r"(?:покажи |список )?сцен[ыа]?", "scenes"),
        (r"(?:покажи |список )?источники", "sources"),
        (r"(?:переключи на|выбери|включи) сцену (.+)", "scene"),
        (r"(?:выключи|отключи|заглуши) микрофон(?: (.+))?", "mute"),
        (r"(?:включи|верни) микрофон(?: (.+))?", "unmute"),
        (r"(?:скрой|выключи) источник (.+)", "hide"),
        (r"(?:покажи|включи) источник (.+)", "show"),
        (r"(?:начни|запусти) запись", "record"),
        (r"(?:останови|заверши) запись", "stop"),
        (r"(?:поставь запись на паузу|пауза записи)", "pause_record"),
        (r"продолжи запись", "resume"),
        (r"(?:сохрани момент|сохрани (?:клип|повтор))", "replay"),
    )
    for pattern, action in names:
        match = re.fullmatch(pattern, body, re.I)
        if match:
            arg = match[1] if match.lastindex else None
            return action + ("|" + arg.strip('«»"') if arg else "")
    return None


def _checked(client, kind, data=None):
    ok, code, result = client.request(kind, data)
    if not ok:
        raise ObsError(f"OBS отклонил операцию {kind} (код {code}).")
    return result


def _named(items, key, name):
    matches = [item for item in items if item.get(key, "").casefold() == name.casefold()]
    if len(matches) != 1:
        raise ObsError(f"Укажите точное имя из OBS: «{name}».")
    return matches[0]


def _scene_items(client):
    scene = _checked(client, "GetCurrentProgramScene")["currentProgramSceneName"]
    return scene, _checked(client, "GetSceneItemList", {"sceneName": scene})["sceneItems"]


def _wait_output(client, kind, active, paused=None):
    from shelter_core import tasks
    for attempt in range(12):
        tasks.check()
        if attempt:
            time.sleep(.15)
        status = _checked(client, kind)
        if status["outputActive"] == active and (paused is None or status["outputPaused"] == paused):
            return status
    return None


def _control(client, command, argument, cfg):
    if command == "status":
        record = _checked(client, "GetRecordStatus")
        ok, code, replay = client.request("GetReplayBufferStatus")
        if not ok and code != OUTPUT_DISABLED:
            raise ObsError(f"OBS не сообщил состояние буфера повтора (код {code}).")
        buffer = ("отключён в настройках" if code == OUTPUT_DISABLED
                  else "работает" if replay["outputActive"] else "выключен")
        scene = _checked(client, "GetCurrentProgramScene")["currentProgramSceneName"]
        recording = "на паузе" if record["outputPaused"] else "идёт" if record["outputActive"] else "выключена"
        return f"Сцена «{scene}». Запись {recording}. Буфер повтора {buffer}."
    if command in ("scenes", "scene"):
        scenes = _checked(client, "GetSceneList")["scenes"]
        if command == "scenes":
            return "Сцены OBS: " + ", ".join(item["sceneName"] for item in scenes) + "."
        scene = _named(scenes, "sceneName", argument)["sceneName"]
        _checked(client, "SetCurrentProgramScene", {"sceneName": scene})
        if _checked(client, "GetCurrentProgramScene")["currentProgramSceneName"] != scene:
            raise ObsError("OBS ещё не подтвердил переключение сцены.")
        return f"Выбрана сцена «{scene}»."
    if command in ("sources", "show", "hide"):
        scene, items = _scene_items(client)
        if command == "sources":
            return f"Источники сцены «{scene}»: " + ", ".join(item["sourceName"] for item in items) + "."
        item = _named(items, "sourceName", argument)
        payload = {"sceneName": scene, "sceneItemId": item["sceneItemId"]}
        enabled = command == "show"
        _checked(client, "SetSceneItemEnabled", {**payload, "sceneItemEnabled": enabled})
        if _checked(client, "GetSceneItemEnabled", payload)["sceneItemEnabled"] != enabled:
            raise ObsError("OBS ещё не подтвердил состояние источника.")
        return f"Источник «{item['sourceName']}» {'виден' if enabled else 'скрыт'} на сцене «{scene}»."
    name = argument or cfg.get("microphone", "")
    if not name:
        raise ObsError("Укажите имя микрофона из аудиомикшера OBS.")
    inputs = _checked(client, "GetInputList")["inputs"]
    audio = {"inputName": _named(inputs, "inputName", name)["inputName"]}
    muted = command == "mute"
    _checked(client, "SetInputMute", {**audio, "inputMuted": muted})
    if _checked(client, "GetInputMute", audio)["inputMuted"] != muted:
        raise ObsError("OBS ещё не подтвердил состояние микрофона.")
    return f"Микрофон «{audio['inputName']}» {'выключен' if muted else 'включён'} в OBS."


def act(text, config):
    """Выполнить действие OBS -> (обычный_успех, фраза). ObsError — не вышло.

    Обычный успех в игре подтверждается звуком; особые случаи («буфер был
    выключен», «запись уже идёт») всегда проговариваются.
    """
    text = str(text).strip()
    command, _, argument = text.partition("|")
    command = command.lower()
    controls = ("status", "scenes", "scene", "sources", "show", "hide", "mute", "unmute")
    action = command if command in (*controls, *ACTIONS) else parse(text)
    if action is None:
        raise ObsError(f"не понял, что сделать в OBS: «{text}»")
    cfg = config.get("obs") or {}
    client = Client(cfg)
    try:
        if action in controls:
            return False, _control(client, action, argument.strip(), cfg)
        previous = None
        if action in ("pause", "pause_record", "resume"):
            previous = _checked(client, "GetRecordStatus")
            if not previous["outputActive"]:
                return False, "Запись сейчас не идёт."
            if action != "pause" and previous["outputPaused"] == (action == "pause_record"):
                return False, "Запись уже на паузе." if previous["outputPaused"] else "Запись уже идёт."
        if action == "replay":
            client.events.pop("ReplayBufferSaved", None)
        ok, code, data = client.request(ACTIONS[action])
        if ok:
            if action == "replay":
                deadline = time.monotonic() + 3
                while "ReplayBufferSaved" not in client.events and time.monotonic() < deadline:
                    client.receive()
                path = client.events.get("ReplayBufferSaved", {}).get("savedReplayPath")
                if not path:
                    raise ObsError("OBS принял запрос, но пока не подтвердил сохранение повтора.")
                return False, f"Момент сохранён: {path}"
            if action == "stop" and data.get("outputPath"):
                return False, f"Запись остановлена: {data['outputPath']}"
            paused = {"pause_record": True, "resume": False}.get(action)
            if action == "pause":
                paused = not previous["outputPaused"]
            status = _wait_output(client, "GetRecordStatus", action != "stop", paused)
            if status is None:
                if paused is not None:
                    raise ObsError("OBS не подтвердил паузу или продолжение. Проверьте кодировщик записи в настройках вывода OBS.")
                raise ObsError("OBS принял запрос, но ещё не подтвердил состояние записи.")
            if action in ("pause", "pause_record", "resume"):
                return False, "Запись на паузе." if status["outputPaused"] else "Запись продолжена."
            return True, "Запись пошла." if action == "record" else "Запись остановлена."
        if action == "replay" and code == NOT_RUNNING:
            _checked(client, "StartReplayBuffer")
            if _wait_output(client, "GetReplayBufferStatus", True) is None:
                raise ObsError("OBS ещё не подтвердил запуск буфера повтора.")
            return False, "Буфер повтора запущен. Для клипа повторите запрос, когда в буфере появится запись."
        if action == "replay" and code == OUTPUT_DISABLED:
            raise ObsError("Включите буфер повтора в OBS → Настройки → Вывод.")
        if action == "record" and code == ALREADY_RUNNING:
            return False, "Запись уже идёт, сэр."
        if action in ("stop", "pause") and code == NOT_RUNNING:
            return False, "Запись и так не идёт, сэр."
        raise ObsError(f"OBS ответил ошибкой {code}")
    finally:
        client.close()
