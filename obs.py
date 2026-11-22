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
import uuid

ACTIONS = {
    "replay": "SaveReplayBuffer",
    "record": "StartRecord",
    "stop": "StopRecord",
    "pause": "ToggleRecordPause",
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


class ObsError(RuntimeError):
    pass


def _auth(password, auth):
    secret = base64.b64encode(hashlib.sha256((password + auth["salt"]).encode()).digest()).decode()
    return base64.b64encode(hashlib.sha256((secret + auth["challenge"]).encode()).digest()).decode()


class Client:
    def __init__(self, cfg):
        import websocket
        url = cfg.get("url", "ws://127.0.0.1:4455")
        try:
            self.ws = websocket.create_connection(url, timeout=3)
        except OSError as error:
            raise ObsError("OBS не отвечает — он запущен и включён сервер WebSocket?") from error
        hello = json.loads(self.ws.recv())
        identify = {"rpcVersion": 1}
        auth = (hello.get("d") or {}).get("authentication")
        if auth:
            password = os.environ.get(cfg.get("password_env", "OBS_PASSWORD"), "") or cfg.get("password", "")
            if not password:
                raise ObsError("OBS просит пароль: положите его в переменную OBS_PASSWORD")
            identify["authentication"] = _auth(password, auth)
        self.ws.send(json.dumps({"op": 1, "d": identify}))
        try:
            reply = json.loads(self.ws.recv())
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
            message = json.loads(self.ws.recv())
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


def act(text, config):
    """Выполнить действие OBS -> (обычный_успех, фраза). ObsError — не вышло.

    Обычный успех в игре подтверждается звуком; особые случаи («буфер был
    выключен», «запись уже идёт») всегда проговариваются.
    """
    action = parse(text)
    if action is None:
        raise ObsError(f"не понял, что сделать в OBS: «{text}»")
    client = Client(config.get("obs") or {})
    try:
        ok, code, _ = client.request(ACTIONS[action])
        if ok:
            return True, {"replay": "Момент сохранён, сэр.", "record": "Запись пошла, сэр.",
                          "stop": "Запись остановлена, сэр.", "pause": "Готово, сэр."}[action]
        if action == "replay" and code == NOT_RUNNING:
            client.request("StartReplayBuffer")
            return False, "Буфер повтора был выключен — включил. Моменты смогу сохранять через пару секунд, сэр."
        if action == "record" and code == ALREADY_RUNNING:
            return False, "Запись уже идёт, сэр."
        if action in ("stop", "pause") and code == NOT_RUNNING:
            return False, "Запись и так не идёт, сэр."
        raise ObsError(f"OBS ответил ошибкой {code}")
    finally:
        client.close()
