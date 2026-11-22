"""Local, owner-paired Minecraft companions for Paper and Fabric Carpet."""
from shelter_core.paths import ROOT_PATH

import json
import http.client
import re
import secrets
import shutil
import threading
import time
import zipfile
from pathlib import Path

ROOT = ROOT_PATH
PAPER_JAR = "shelter-npc-0.2.0.jar"
CARPET_SCRIPT = "sheltercompanion.sc"
_lock = threading.RLock()
_token = ""
_fabric = None
OPS = {"status", "spawn", "come", "follow", "stop", "remove"}
STATES = {
    "idle": "Напарник ещё не появился.",
    "ready": "Напарник в мире.",
    "spawning": "Сервер создаёт напарника.",
    "spawn_failed": "Сервер не создал напарника. Проверьте сообщения Carpet.",
    "name_taken": "Имя ShelterJarvis уже занято в мире.",
    "come": "Напарник идёт к вам.",
    "follow": "Напарник следует за вами.",
    "arrived": "Напарник подошёл.",
    "stopped": "Движение напарника остановлено.",
    "owner_offline": "Войдите на сервер своим аккаунтом.",
    "no_path": "Напарник не нашёл путь к вам.",
    "timeout": "Истекло время действия напарника.",
    "different_world": "Напарник остался в другом измерении.",
    "disconnected": "Подключите напарника снова.",
}


class PairingExpired(RuntimeError):
    pass


def _snapshot(data, platform):
    if not isinstance(data, dict) or data.get("state") not in STATES:
        raise ValueError("Invalid response")
    state = data["state"]
    coordinates = {axis: data[axis] for axis in "xyz" if type(data.get(axis)) in (int, float)
                   and abs(data[axis]) <= 30_000_000}
    mode = data.get("gameMode")
    return {**coordinates, "state": state, "message": STATES[state], "paired": state != "disconnected",
            "platform": platform, "kind": data.get("kind", "legacy" if platform == "paper" else "player"),
            "gameMode": mode if mode in ("survival", "creative", "adventure", "spectator") else ""}


def _request(op, token, body=b""):
    connection = http.client.HTTPConnection("127.0.0.1", 27846, timeout=1.8)
    try:
        connection.request("POST", f"/npc/{op}", body=body, headers={"Authorization": "Bearer " + token})
        response = connection.getresponse()
        if response.status == 401:
            raise PairingExpired("Код подключения больше не действует. Получите новый в игре.")
        if response.status != 200:
            raise RuntimeError("Сервер напарника сейчас занят. Попробуйте ещё раз.")
        return _snapshot(json.loads(response.read(4096)), "paper")
    except (OSError, ValueError, TypeError, http.client.HTTPException):
        raise RuntimeError("Локальный сервер напарника не отвечает. Проверьте Paper и ShelterNpc.") from None
    finally:
        connection.close()


def _carpet_directory(folder):
    if not isinstance(folder, str) or not folder:
        raise ValueError("Выберите папку scripts своего мира Fabric.")
    try:
        directory = Path(folder).resolve(strict=True)
        if directory.name.lower() != "scripts" or not (directory / CARPET_SCRIPT).is_file():
            raise ValueError("Сначала распакуйте мод в папку scripts своего мира Fabric.")
        state = directory / "sheltercompanion.data"
        if state.resolve().parent != directory:
            raise ValueError("Выберите обычную папку scripts без перенаправления данных.")
        state.mkdir(exist_ok=True)
        return state
    except OSError:
        raise ValueError("Папка scripts недоступна.") from None


def _carpet_request(directory, op, token, body=b""):
    identifier = secrets.token_hex(16)
    temporary = directory / (identifier + ".tmp")
    request, response = directory / "request.json", directory / "response.json"
    try:
        with temporary.open("x", encoding="utf-8") as file:
            json.dump({"op": op, "token": token, "text": body.decode("utf-8"), "id": identifier}, file)
        temporary.replace(request)
        deadline = time.monotonic() + 1.8
        while time.monotonic() < deadline:
            try:
                with response.open(encoding="utf-8") as file:
                    result = json.loads(file.read(4096))
                if isinstance(result, dict) and result.get("id") == identifier:
                    return _snapshot(result, "fabric")
            except (OSError, ValueError):
                pass
            time.sleep(0.055)
    except OSError:
        raise RuntimeError("Не удалось записать команду в папку мира Fabric.") from None
    finally:
        temporary.unlink(missing_ok=True)
        # A request without an answer must not execute if the world is unpaused later.
        request.unlink(missing_ok=True)
    raise RuntimeError("Мир Fabric не ответил. Проверьте, что он открыт и скрипт загружен.")


def _send(op, token, body=b""):
    return _carpet_request(_fabric, op, token, body) if _fabric else _request(op, token, body)


def package_jar(root, source, platform):
    if not source.is_file():
        raise RuntimeError("JAR расширения не найден. Проверьте комплект поставки Джарвиса.")
    destination = root / "data" / "game-mods" / platform / source.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix("." + secrets.token_hex(6) + ".tmp")
    try:
        shutil.copyfile(source, temporary)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return {"file": str(destination)}


def _package(platform):
    directory = ROOT / "data" / "game-mods" / "minecraft-1.21.11" / platform
    if platform == "paper":
        source = ROOT / "games" / "minecraft-npc" / "distribution" / PAPER_JAR
        if not source.is_file():
            raise RuntimeError("JAR плагина не найден. Соберите его по инструкции в docs/MINECRAFT.md.")
        destination = directory / PAPER_JAR
    else:
        source = ROOT / "games" / "minecraft-carpet" / CARPET_SCRIPT
        destination = directory / "shelter-carpet-1.21.11.zip"
    directory.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix("." + secrets.token_hex(6) + ".tmp")
    try:
        if platform == "paper":
            shutil.copyfile(source, temporary)
        else:
            with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.write(source, f"scripts/{CARPET_SCRIPT}")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return {"file": str(destination)}


def api(data, config):
    global _token, _fabric
    op = data.get("op")
    platform = data.get("platform", "paper")
    neo_forge = ROOT / "bin" / "minecraft" / "jarvis-companion-neoforge-1.21.1.jar"
    if op == "package" and platform == "neoforge":
        # The supplied source tree carries its own license. Its build is local to this workspace.
        return package_jar(ROOT, neo_forge, "neoforge-1.21.1")
    if platform not in ("paper", "fabric"):
        raise ValueError("Выберите Paper или Fabric.")
    if not isinstance(op, str):
        raise ValueError("Неизвестная команда напарника.")
    if op == "package":
        return _package(platform)
    if op == "ask":
        from shelter_core.minecraft_companion import Companion
        from shelter_core.minecraft_intents import parse, scoped
        prompt = data.get("text")
        if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 200:
            raise ValueError("Напишите сообщение напарнику до 200 символов.")
        with _lock:
            current = _token
            state = _send("status", current) if current else {"state": "disconnected"}
        if "x" not in state:
            raise RuntimeError("Сначала подключите и вызовите напарника в мире.")
        parsed = parse(scoped(prompt) or prompt)
        if parsed:
            reply = voice(parsed)
        else:
            try:
                reply = Companion._chat_reply({**config, "_minecraft_state": _world_context(state)}, prompt.strip(), [])
            except (RuntimeError, ValueError, OSError):
                raise RuntimeError("Разговорная модель не ответила. Проверьте настройки чата.") from None
        with _lock:
            if _token == current:
                _send("say", current, reply.encode("utf-8"))
        return {"reply": reply}
    with _lock:
        if op == "pair":
            if _token:
                raise RuntimeError("Сначала отключите текущего напарника.")
            if platform == "fabric":
                directory = _carpet_directory(data.get("folder"))
                token = secrets.token_hex(32)
                status = _carpet_request(directory, "pair", token)
                if not status["paired"]:
                    raise RuntimeError("Выполните /sheltercompanion pair в игре, затем повторите подключение.")
                _fabric, _token = directory, token
                return status
            token = data.get("token")
            if not isinstance(token, str) or not re.fullmatch(r"[a-f0-9]{64}", token):
                raise ValueError("Вставьте код из команды /shelternpc pair.")
            status = _request("status", token)
            _fabric, _token = None, token
            return status
        if op == "disconnect":
            if _token:
                try:
                    _send("remove", _token)
                finally:
                    _token, _fabric = "", None
            return {"paired": False}
        if op not in OPS:
            raise ValueError("Неизвестная команда напарника.")
        local_mod = {"neoforge_available": neo_forge.is_file()} if op == "status" else {}
        if not _token:
            return {**local_mod, "paired": False, "state": "disconnected", "message": STATES["disconnected"]}
        try:
            status = _send(op, _token)
        except PairingExpired:
            _token, _fabric = "", None
            raise
        if not status["paired"]:
            _token, _fabric = "", None
        return {**status, **local_mod}


def interrupt():
    if not _token:
        return
    try:
        api({"op": "stop"}, {})
    except RuntimeError:
        pass


def voice(parsed):
    op = {"position": "status", "status": "status", "connection": "status", "game_mode": "status",
          "come": "come", "follow": "follow", "stop": "stop"}.get(parsed["op"])
    if not op:
        return "Напарник без отдельного аккаунта умеет подходить, следовать, останавливаться и сообщать координаты."
    state = api({"op": op}, {})
    if parsed["op"] in {"position", "connection"} and all(axis in state for axis in "xyz"):
        return f"Я в мире Minecraft. Мои координаты: {state['x']:.0f}, {state['y']:.0f}, {state['z']:.0f}."
    if parsed["op"] == "game_mode" and "x" in state:
        from shelter_core.minecraft_companion import GAME_MODES
        mode = GAME_MODES.get(state.get("gameMode"))
        return f"Мой игровой режим в Minecraft: {mode}." if mode else "У персонажа Paper нет отдельного игрового режима."
    return state["message"]


def paired():
    return bool(_token)


def reply_session():
    return _token


def _world_context(state):
    if "x" not in state:
        return {}
    return {"connection": "connected", "position": [state[axis] for axis in "xyz"],
            "gameMode": state.get("gameMode") or None, "adapter": state.get("platform") or "paper"}


def game_context(session):
    with _lock:
        if session and _token == session:
            try:
                return _world_context(_send("status", session))
            except RuntimeError:
                return {}
    return {}


def relay(session, text):
    if not session or not text.strip():
        return

    def send():
        with _lock:
            if _token == session:
                try:
                    speech = " ".join(text.split()).encode("utf-8")[:1024].decode("utf-8", "ignore")
                    _send("say", session, speech.encode("utf-8"))
                except RuntimeError:
                    pass

    threading.Thread(target=send, name="minecraft-companion-chat", daemon=True).start()
