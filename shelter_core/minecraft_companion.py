"""Optional Minecraft process, accessed only through the authenticated desktop core."""

from shelter_core.paths import ROOT_PATH

import ipaddress
import json
import os
from pathlib import Path
from collections import deque
import queue
import re
import shutil
import subprocess
import threading
import time
import unicodedata

from shelter_core import minecraft_intents as intents
from shelter_core.process_runtime import service_options

ROOT = ROOT_PATH
LOGIN_URL = "https://www.microsoft.com/link"
CHILD_ENV = set("PATH PATHEXT SYSTEMROOT WINDIR SYSTEMDRIVE COMSPEC TEMP TMP TMPDIR APPDATA LOCALAPPDATA USERPROFILE HOMEDRIVE HOMEPATH HOME LANG LC_ALL HTTP_PROXY HTTPS_PROXY NO_PROXY ALL_PROXY NODE_EXTRA_CA_CERTS".split())
ERRORS = {
    "connection_failed": "Не удалось подключиться. Проверьте адрес, порт и что мир открыт.",
    "kicked": "Сервер отключил напарника. Проверьте список доступа и что он входит другим игроком.",
    "auth_failed": "Не удалось войти. Проверьте, что для аккаунта напарника доступна Java Edition.",
    "same_account": "Вы вошли своим игровым аккаунтом. Сбросьте вход и используйте отдельный аккаунт напарника.",
    "version": "Эта версия сервера не поддерживается игровым клиентом напарника.",
    "busy": "Напарник занят. Проверьте очередь игровых задач.",
    "not_ready": "Сначала подключите напарника в разделе «Игры → Minecraft».",
    "owner_absent": "Я не вижу вас в мире. Проверьте имя владельца и подойдите ближе.",
    "owner_far": "Вы слишком далеко. Подойдите ближе ко мне.",
    "owner_left": "Действие остановлено: владелец слишком далеко или вышел из мира.",
    "not_found": "Не нашёл такой предмет или доступный блок поблизости.",
    "mod_item_unavailable": "Игровой клиент не видит этот ID в реестре. Проверьте ID и совместимость сервера с ванильным клиентом.",
    "need_tool": "Для этого блока мне нужен подходящий инструмент в инвентаре.",
    "no_recipe": "Не хватает материалов или для рецепта нужен верстак.",
    "not_enough": "В моём инвентаре нет столько предметов.",
    "no_space": "В инвентаре нет места.",
    "blocked": "Не получилось добраться до цели или выполнить действие.",
    "unconfirmed": "Сервер не подтвердил разрушение блока. Проверьте разрешения и состояние блока в игре.",
    "unsafe": "Этот блок не трогаю: рядом жидкость или сверху сыпучие блоки.",
    "stopped": "Остановился.", "timeout": "Время действия истекло. Я остановился.",
    "respawn": "Действие остановлено после гибели или возрождения.",
    "count": "Укажите количество от 1 до 16 за одну команду.",
    "item": "Назовите точный материал, например дубовые брёвна, землю или доски.",
    "need_logs": "Не удалось подобрать нужные брёвна: из них я делаю доски. Дайте их мне или подойдите к доступному дереву.",
    "craft_unconfirmed": "Сервер не подтвердил нужное количество после крафта. Проверьте мой инвентарь.",
    "give_unconfirmed": "Сервер не подтвердил передачу. Проверьте предметы рядом и мой инвентарь.",
    "teleport_denied": "Сервер не подтвердил телепорт. Нужны разрешённые команды и право телепорта у аккаунта напарника.",
    "mode_denied": "Сервер сохранил прежний режим. Для смены нужно право на команду gamemode.",
    "place_unconfirmed": "Сервер не подтвердил установку блока.",
    "no_plan": "Не нашёл выполнимую цепочку из доступных материалов, блоков, инструментов и рецептов.",
    "furnace_busy": "В печи уже есть предметы. Освободите её для этой задачи.",
    "missing_drop": "Сломал блоки, но нужное сырьё не появилось в моём инвентаре.",
    "no_food": "В моём инвентаре нет подходящей еды.",
    "eat_unconfirmed": "Сервер не подтвердил, что запас сытости вырос.",
    "fish_unconfirmed": "Улов не появился в моём инвентаре.",
    "bad_command": "Не получилось разобрать игровые параметры.",
}
CHAT_SIGNATURE = "Сервер прислал команду без проверяемой подписи. Используйте голос или разрешите чат своего локального мира в настройках Minecraft."
ITEM_LABELS = {
    "planks": "доски",
    "oak_log": "дубовые брёвна", "spruce_log": "еловые брёвна", "birch_log": "берёзовые брёвна",
    "oak_planks": "дубовые доски", "spruce_planks": "еловые доски", "birch_planks": "берёзовые доски",
    "stone": "камень", "cobblestone": "булыжник", "dirt": "земля", "sand": "песок", "coal": "уголь",
    "stick": "палки", "crafting_table": "верстак", "torch": "факелы",
}
SETTINGS_KEYS = ("host", "port", "owner", "auth", "chat", "ai_chat", "speak_chat", "trust_local_chat", "relay_replies")
JOB_OPERATIONS = {"come", "follow", "mine", "craft", "obtain", "give", "give_stock", "deliver", "teleport",
                  "guard", "equip", "build", "set_mode", "navigate", "eat", "fish", "sequence"}
GAME_MODES = {"survival": "выживание", "creative": "творческий", "adventure": "приключение", "spectator": "наблюдатель"}


def validate(data):
    host = str(data.get("host") or "127.0.0.1").strip().lower()
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", host) or ".." in host:
            raise ValueError("Введите адрес сервера без протокола, пути и порта.") from None
    port = data.get("port", 25565)
    if isinstance(port, bool) or not str(port).isascii() or not str(port).isdigit() or len(str(port)) > 5 or not 1 <= int(port) <= 65535:
        raise ValueError("Порт должен быть числом от 1 до 65535.")
    owner = str(data.get("owner") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_]{3,16}", owner):
        raise ValueError("Введите свой игровой ник Java Edition: 3–16 латинских букв, цифр или подчёркиваний.")
    auth = str(data.get("auth") or "microsoft")
    if auth not in ("microsoft", "offline"):
        raise ValueError("Неизвестный способ входа.")
    if auth == "offline" and host not in ("127.0.0.1", "::1"):
        raise ValueError("Гостевой вход доступен только на тестовом сервере на этом компьютере.")
    name = "JarvisCompanion"
    if name.lower() == owner.lower():
        name = "JarvisHelper"
    return {"host": host, "port": int(port), "owner": owner, "auth": auth,
            "account": "jarvis-minecraft" if auth == "microsoft" else name,
            **{key: data.get(key) is True for key in ("chat", "ai_chat", "speak_chat")},
            "relay_replies": data.get("relay_replies") is not False,
            "trust_local_chat": host in ("127.0.0.1", "::1") and data.get("trust_local_chat") is True}


def lan_port(log):
    try:
        if time.time() - log.stat().st_mtime > 24 * 3600:
            return None
        with log.open("rb") as file:
            file.seek(max(0, log.stat().st_size - 256_000))
            text = file.read(256_000).decode("utf-8", "replace")
    except OSError:
        return None
    lines = re.split(r"(?im)^.*\[Server thread/INFO\]: Stopping server.*$", text)[-1]
    ports = re.findall(r"(?im)^.*\[(?:Server|Render) thread/INFO\]: (?:Started serving on|Local game hosted on port)\s+(\d{1,5})(?!\d)", lines)
    return int(ports[-1]) if ports and 1 <= int(ports[-1]) <= 65535 else None


def describe_position(result):
    x, y, z = result["position"]
    dimension = result.get("dimension")
    world = {"overworld": "Верхний мир", "the_nether": "Нижний мир", "the_end": "Край"}.get(
        dimension.removeprefix("minecraft:") if isinstance(dimension, str) else "")
    return f"Мои координаты: икс {x}, игрек {y}, зет {z}." + (f" {world}." if world else "")


def chat_lines(text):
    words = " ".join("".join(" " if unicodedata.category(c) in {"Cc", "Cf"} or c == "§" else c for c in text).split())[:1024]
    limit = 120  # Up to two UTF-16 units per code point.
    while words:
        split = len(words) if len(words) <= limit else words.rfind(" ", 0, limit + 1)
        split = split if split > 0 else limit
        line = words[:split]
        yield "› " + line if line.startswith("/") else line
        words = words[split:].lstrip()


def describe_job(data):
    state, operation = data.get("state"), data.get("op")
    result = data.get("result")
    if state != "done" or not isinstance(result, dict):
        return ERRORS.get(str(result), ERRORS.get(str(state), ERRORS["blocked"]))
    label = ITEM_LABELS.get(result.get("item"), result.get("item", ""))
    if operation == "mine":
        text = f"Сломано блоков: {result['broken']}. Подобрано: {result['collected']} ({label})."
        return text + (" " + ERRORS.get(result.get("warning"), "") if result.get("warning") else "")
    if operation == "craft":
        return f"Создано: {result['count']} ({label})."
    if operation == "obtain":
        return f"В моём инвентаре: {result['count']} ({label})."
    if operation in ("give", "give_stock", "deliver"):
        return f"Выброшено рядом с вами: {result['count']} ({label}). Проверьте, что подобрали."
    if operation == "teleport":
        return f"Телепортировался к вам. {describe_position(result)}"
    if operation == "set_mode":
        return f"Сервер подтвердил режим: {GAME_MODES[result['mode']]}."
    if operation == "equip":
        return f"В руке: {label}."
    if operation == "navigate":
        return describe_position(result)
    if operation == "eat":
        return "Запас сытости полный." if result.get("full") else f"Поел. Запас сытости: {result['food']} из 20."
    if operation == "fish":
        return f"Улов в инвентаре: {label} ×{result['count']}."
    if operation == "build":
        text = f"Установлено блоков: {result['placed']} из {result['count']} ({label})."
        return text + (" " + ERRORS[result["warning"]] if result.get("warning") else "")
    if operation == "sequence":
        results = [describe_job({**entry, "state": "done"}) for entry in result["done"]]
        if result.get("warning"):
            results.append(ERRORS[result["warning"]])
        return f"Шаги плана ({len(result['done'])} из {result['total']}). " + " ".join(results)
    return "Я рядом."


class Companion:
    def __init__(self, root=ROOT):
        self.root = root
        self.lock = threading.RLock()
        self.process = None
        self.installer = None
        self.phase = "idle"
        self.error = self.code = self.last = ""
        self.info = {}
        self.request_id = 0
        self.pending = {}
        self.job_routes = {}
        self.job_history = deque(maxlen=8)
        self.chat_epoch = 0
        self.hello = None
        self.messages = None
        self.events = None
        self.relay_replies = True

    @property
    def settings_path(self):
        return self.root / "data" / "minecraft.json"

    def saved(self):
        try:
            data = json.loads(self.settings_path.read_text(encoding="utf-8"))
            return {key: data[key] for key in SETTINGS_KEYS if key in data}
        except (OSError, ValueError, TypeError):
            return {"host": "127.0.0.1", "port": 25565, "auth": "microsoft", "chat": True}

    def installed(self):
        return all((self.root / "minecraft" / "node_modules" / name / "package.json").is_file()
                   for name in ("mineflayer", "mineflayer-pathfinder"))

    def snapshot(self, *, poll=True):
        with self.lock:
            current = self.process
            ready = self.phase == "ready" and current is not None
        if poll and ready:
            try:
                info = self.request({"op": "status"}, current, timeout=0.6)
                with self.lock:
                    if current is self.process:
                        self.info = info
            except RuntimeError:
                pass
        with self.lock:
            result = {"phase": self.phase, "error": self.error, "code": self.code, "login_url": LOGIN_URL,
                      "last": self.last, "history": list(self.job_history), "info": self.info.copy(), "settings": self.saved(),
                      "installed": self.installed(), "node": bool(shutil.which("node"))}
        info = result["info"]
        if info.get("items"):
            labels = intents.item_labels(info.get("version", ""))
            info["itemLabels"] = {name: labels[name] for name, _ in info["items"] if name in labels}
        return result

    def _start(self, args, *, stdio=False):
        flags = service_options()
        flags.update({"stdin": subprocess.PIPE if stdio else subprocess.DEVNULL,
                      "stdout": subprocess.PIPE if stdio else subprocess.DEVNULL, "stderr": subprocess.DEVNULL})
        environment = {key: value for key, value in os.environ.items() if key.upper() in CHILD_ENV}
        return subprocess.Popen(args, cwd=self.root / "minecraft", text=True, encoding="utf-8", errors="replace",
                                bufsize=1, env=environment, **flags)

    def install(self):
        with self.lock:
            if self.process or self.installer:
                raise RuntimeError(ERRORS["busy"])
            node = shutil.which("node")
            if not node:
                raise RuntimeError("Установите Node.js 22 или новее и перезапустите Джарвиса.")
            cli = Path(node).parent / "node_modules" / "npm" / "bin" / "npm-cli.js"
            npm = [node, str(cli)] if cli.is_file() else [shutil.which("npm") or ""] if os.name != "nt" else []
            if not npm or not npm[0]:
                raise RuntimeError("Не найден npm. Установите Node.js вместе с npm.")
            self.installer = self._start([*npm, "ci", "--ignore-scripts", "--no-audit", "--no-fund"])
            self.phase, self.error = "installing", ""
            threading.Thread(target=self._wait_install, args=(self.installer,), daemon=True).start()

    def _wait_install(self, process):
        try:
            success = process.wait(timeout=180) == 0
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            success = False
        with self.lock:
            if self.installer is process:
                self.installer = None
                self.phase = "idle" if success else "error"
                self.error = "" if success else "Не удалось установить игровой клиент. Проверьте интернет и версию Node.js."

    def connect(self, data, config, events):
        settings = validate(data)
        node = shutil.which("node")
        if not node or not self.installed():
            raise RuntimeError("Сначала установите игровой клиент и Node.js 22 или новее.")
        with self.lock:
            if self.process or self.installer:
                raise RuntimeError(ERRORS["busy"])
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.settings_path.with_suffix(".tmp")
            temporary.write_text(json.dumps({key: value for key, value in settings.items() if key != "account"}, indent=2), encoding="utf-8")
            temporary.replace(self.settings_path)
            process = self._start([node, "bridge.mjs"], stdio=True)
            self.process = process
            self.hello = threading.Event()
            self.phase, self.error, self.code, self.last, self.info = "connecting", "", "", "", {}
            messages = queue.Queue(maxsize=6)
            ai_messages = queue.Queue(maxsize=2) if settings["ai_chat"] else None
            self.messages = messages
            self.relay_replies = settings["relay_replies"]
            self.events = events
            threading.Thread(target=self._read, args=(process, messages), daemon=True).start()
            threading.Thread(target=self._chat_loop, args=(process, messages, ai_messages, settings, events), daemon=True).start()
            if ai_messages is not None:
                threading.Thread(target=self._chat_ai_loop, args=(process, messages, ai_messages, config), daemon=True).start()
            threading.Thread(target=self._handshake, args=(process, settings, self.hello), daemon=True).start()

    def _handshake(self, process, settings, hello):
        try:
            if not hello.wait(timeout=10):
                raise RuntimeError("Игровой клиент не запустился. Проверьте версию Node.js и переустановите клиент.")
            self.request({"op": "connect", "settings": settings}, process, timeout=12)
            until = time.monotonic() + (300 if settings["auth"] == "microsoft" else 30)
            while time.monotonic() < until:
                with self.lock:
                    if self.process is not process or self.phase == "ready":
                        return
                    if self.error:
                        raise RuntimeError(self.error)
                time.sleep(0.25)
            self.disconnect(process, "Время подключения истекло. Проверьте порт или повторите вход Microsoft.")
        except RuntimeError as error:
            self.disconnect(process, str(error))

    def _read(self, process, messages):
        try:
            for line in process.stdout:
                if len(line) > 16000:
                    break
                try:
                    data = json.loads(line)
                    if isinstance(data, dict):
                        self._receive(process, messages, data)
                except (ValueError, KeyError, TypeError):
                    continue
        except OSError:
            pass
        finally:
            process.stdout.close()
            self.disconnect(process, "Игровое соединение закрыто. Проверьте адрес, порт, версию Node.js или доступ к миру.")

    def _receive(self, process, messages, data):
        with self.lock:
            if self.process is not process:
                return
            event = data.get("event")
            if event == "hello" and data.get("protocol") == 1:
                self.hello.set()
            if event == "auth":
                self.phase, self.code = "auth", data["code"]
            if event == "ready":
                self.phase, self.code, self.error = "ready", "", ""
                self.job_history.clear()
                self.info = {key: value for key, value in data.items() if key != "event"}
                print(f"[minecraft] connected, Java {self.info.get('version')}", flush=True)
            if event == "error":
                self.error = ERRORS.get(data.get("error"), ERRORS["connection_failed"])
            if event == "chat_signature":
                self.last = CHAT_SIGNATURE
                print("[minecraft] ignored owner chat: no verifiable signature", flush=True)
            if event == "job":
                route = self.job_routes.pop(data.get("id"), None)
                self.job_history.appendleft({"id": data.get("id"), "op": data.get("op"),
                                             "state": data.get("state"), "message": describe_job(data)})
                if data.get("state") not in ("replaced", "stopped"):
                    self.last = describe_job(data)
                    print(f"[minecraft] {data.get('op')}: {data.get('state')} — {self.last}", flush=True)
                    if route == "chat":
                        self._enqueue(messages, ("result", self.last, self.chat_epoch))
                    elif route == "desktop":
                        self._enqueue(messages, ("mirror", self.last, self.chat_epoch))
                        if self.events is not None:
                            self._enqueue(self.events, ("minecraft_speech", (process, self.chat_epoch, self.last)))
            if event == "chat":
                text = str(data.get("text") or "")[:200]
                parsed = intents.parse(intents.scoped(text) or text, self.info.get("version", ""))
                if parsed and parsed["op"] == "stop":
                    self.interrupt()
                    self._enqueue(messages, ("result", "Команда остановки принята.", self.chat_epoch))
                else:
                    self._enqueue(messages, ("chat", text, self.chat_epoch))
            if data.get("id") in self.pending and not event:
                self._enqueue(self.pending[data["id"]], data)

    @staticmethod
    def _enqueue(target, data):
        try:
            target.put_nowait(data)
        except queue.Full:
            pass

    def request(self, payload, process=None, *, timeout=2, wait=True, route=None, epoch=None):
        answer = queue.Queue(maxsize=1)
        with self.lock:
            process = self.process if process is None else process
            if process is None or self.process is not process:
                raise RuntimeError(ERRORS["not_ready"])
            if epoch is not None and epoch != self.chat_epoch:
                raise RuntimeError(ERRORS["stopped"])
            self.request_id += 1
            identifier = self.request_id
            if wait:
                self.pending[identifier] = answer
            if route:
                self.job_routes[identifier] = route
            try:
                process.stdin.write(json.dumps({**payload, "id": identifier}, ensure_ascii=False) + "\n")
                process.stdin.flush()
            except (OSError, ValueError):
                self.pending.pop(identifier, None)
                self.job_routes.pop(identifier, None)
                raise RuntimeError(ERRORS["connection_failed"]) from None
        if not wait:
            return {}
        try:
            reply = answer.get(timeout=timeout)
            if not reply.get("ok"):
                raise RuntimeError(ERRORS.get(reply.get("error"), ERRORS["connection_failed"]))
            return reply.get("result", {})
        except (queue.Empty, RuntimeError) as error:
            with self.lock:
                self.job_routes.pop(identifier, None)
            if isinstance(error, RuntimeError):
                raise
            raise RuntimeError("Игровой клиент не ответил вовремя.") from None
        finally:
            with self.lock:
                self.pending.pop(identifier, None)

    def disconnect(self, process=None, error=""):
        with self.lock:
            current = self.process
            if not current or process is not None and current is not process:
                return
            if not error:
                try:
                    self.request({"op": "quit"}, current, wait=False)
                except RuntimeError:
                    pass
            self.process = None
            for target in self.pending.values():
                self._enqueue(target, {"ok": False, "error": "not_ready"})
            self.job_routes.clear()
            self.chat_epoch += 1
            self.info, self.code = {}, ""
            self.messages = self.events = None
            self.phase = "error" if error else "idle"
            self.error = (self.error or error) if error else ""
        try:
            current.stdin.close()
            current.wait(timeout=0.6)
        except (OSError, subprocess.TimeoutExpired):
            current.kill()
            current.wait(timeout=2)

    def close(self):
        with self.lock:
            installer, self.installer = self.installer, None
        if installer:
            installer.kill()
            installer.wait(timeout=2)
        self.disconnect()

    def interrupt(self):
        with self.lock:
            if self.phase == "ready":
                self.chat_epoch += 1
                self.job_routes.clear()
                if self.messages:
                    try:
                        while True:
                            self.messages.get_nowait()
                    except queue.Empty:
                        pass
                try:
                    self.request({"op": "stop"}, wait=False)
                except RuntimeError:
                    pass

    def execute(self, parsed, process=None, *, chat=False, epoch=None):
        if not parsed or parsed["op"] == "help":
            return intents.HELP
        operation = parsed["op"]
        if operation == "invalid":
            return ERRORS[parsed["error"]]
        route = ("chat" if chat else "desktop") if operation in JOB_OPERATIONS else None
        print(f"[minecraft] {'chat' if chat else 'desktop'}: {operation}", flush=True)
        if operation in ("game_mode", "connection") and self.phase != "ready":
            return ERRORS["not_ready"]
        request = {"op": "status"} if operation in ("game_mode", "connection") else parsed
        result = self.request(request, process, route=route, epoch=epoch)
        if operation == "game_mode":
            mode = GAME_MODES.get(result.get("gameMode"))
            return f"Мой игровой режим в Minecraft: {mode}." if mode else "Сервер пока не сообщил мой игровой режим."
        if operation == "connection":
            return f"Я в мире Minecraft. {describe_position(result)}"
        if operation == "position":
            return describe_position(result)
        if operation == "nearby":
            entities = ", ".join(sorted({entry["name"] for entry in result["nearby"]}))
            return f"Рядом вижу: {entities}." if entities else "Поблизости никого не вижу."
        if operation == "status":
            labels = intents.item_labels(result.get("version", ""))
            items = ", ".join(f"{labels.get(name, ITEM_LABELS.get(name, name))} ×{count}" for name, count in result["items"]) or "пусто"
            return f"Инвентарь: {items}."
        if operation == "stop":
            return "Остановился." if result["stopped"] else "Я уже стою."
        if result.get("queued"):
            return f"Задача в очереди. Место: {result['queued']}."
        return {"come": "Иду к вам.", "follow": "Иду за вами.", "mine": "Начинаю добычу.",
                "craft": "Проверяю материалы и начинаю крафт.", "give": "Ищу предмет или способ его получить.",
                "give_stock": "Подхожу, чтобы передать предмет.",
                "deliver": "Подготовлю предметы, подойду и передам их.",
                "obtain": "Ищу материалы и составляю план добычи.",
                "teleport": "Запрашиваю телепорт у сервера.",
                "set_mode": "Запрашиваю смену игрового режима у сервера.",
                "guard": "Остаюсь рядом и защищаю вас от враждебных мобов.",
                "equip": "Проверяю инвентарь и беру предмет в руку.",
                "eat": "Проверяю запас еды.",
                "fish": "Ищу место для рыбалки.",
                "navigate": "Иду к указанным координатам.",
                "sequence": "Начинаю выполнять план по шагам.",
                "build": "Проверяю материалы и место для постройки."}[operation]

    def game_context(self, session):
        if not session:
            return {}
        process, epoch = session
        try:
            state = self.request({"op": "status"}, process, epoch=epoch, timeout=0.8)
            with self.lock:
                if session != self.reply_session():
                    return {}
                return {**state, "lastConfirmedResult": self.last}
        except RuntimeError:
            return {"connection": "connected; awaiting server state"} if session == self.reply_session() else {}

    def reply_session(self):
        with self.lock:
            return (self.process, self.chat_epoch) if self.phase == "ready" and self.process else None

    def relay(self, session, reply, *, game=False):
        with self.lock:
            if self.messages and session == self.reply_session() and (game or self.relay_replies):
                self._enqueue(self.messages, ("mirror", reply, self.chat_epoch))

    def _chat_loop(self, process, messages, ai_messages, settings, events):
        last_reply = 0
        while self.process is process:
            try:
                kind, value, epoch = messages.get(timeout=0.3)
            except queue.Empty:
                continue
            if self.process is not process or epoch != self.chat_epoch:
                continue
            parsed = None
            try:
                if kind in ("result", "mirror"):
                    reply = value
                elif value == "open_inventory":
                    reply = ("Для !inv установите ShelterInventory на свой сервер Paper и привяжите мой ник. "
                             "Файл и инструкция есть в Игры → Minecraft → Инвентарь в игре. "
                             "!jarvis инвентарь показывает список.")
                else:
                    parsed = intents.parse(intents.scoped(value) or value, self.info.get("version", ""))
                    if (not parsed or parsed.get("error") == "item") and ai_messages is not None:
                        self._enqueue(ai_messages, (value, epoch))
                        continue
                    reply = self.execute(parsed, process, chat=True, epoch=epoch)
            except RuntimeError as error:
                reply = str(error) if parsed and str(error) in ERRORS.values() else "Не получилось выполнить команду. Проверьте панель Minecraft."
            try:
                for line in chat_lines(reply):
                    time.sleep(max(0, 0.75 - (time.monotonic() - last_reply)))
                    self.request({"op": "say", "text": line}, process, epoch=epoch)
                    last_reply = time.monotonic()
                if kind != "mirror" and settings["speak_chat"]:
                    events.put(("minecraft_speech", (process, epoch, reply)))
            except RuntimeError:
                continue

    def _chat_ai_loop(self, process, messages, ai_messages, config):
        """Conversation I/O must not delay owner commands or their results."""
        history = []
        while self.process is process:
            try:
                text, epoch = ai_messages.get(timeout=0.3)
            except queue.Empty:
                continue
            if self.process is not process or epoch != self.chat_epoch:
                continue
            try:
                from shelter_core import live_facts
                reply = live_facts.answer(text, config)
                if reply is None:
                    state = self.game_context((process, epoch))
                    reply = self._chat_reply({**config, "_minecraft_state": state, "_minecraft_actions": bool(state)}, text, history)
                    if reply.startswith("!action "):
                        action = intents.model_command(reply.removeprefix("!action "))
                        reply = (self.execute(action, process, chat=True, epoch=epoch) if action else
                                 "Не удалось подобрать действие. Уточните предмет или цель.")
            except (RuntimeError, OSError, ValueError):
                reply = "Разговорная модель не ответила. Игровые команды по-прежнему доступны."
            else:
                if self.process is process and epoch == self.chat_epoch:
                    history = (history + [{"role": "user", "content": text}, {"role": "assistant", "content": reply}])[-6:]
            if self.process is process and epoch == self.chat_epoch:
                self._enqueue(messages, ("result", reply, epoch))

    @staticmethod
    def _chat_reply(config, text, history):
        from shelter_core import llm
        from shelter_core import llm_connections
        from shelter_core import personas

        if not (config.get("llm") or {}).get("enabled"):
            return "Разговорная модель выключена в Джарвисе. Игровые команды работают."
        model = llm_connections.resolve(config.get("llm") or {})
        model = {**model, "think": False, "max_tokens": 180}
        name = personas.active().get("name", "Джарвис")
        prompt = (f"Ты {name}, напарник в Minecraft. Отвечай коротко, обычным текстом на языке игрока. "
                  "Тебе недоступны экран, ОС, чужие данные, инструменты и память рабочего стола.")
        if state := config.get("_minecraft_state"):
            prompt += (" Текущее состояние взято из игры: " + json.dumps(state, ensure_ascii=False) +
                       ". Отвечай про мир только по этим данным.")
        if config.get("_minecraft_actions"):
            prompt += (" Для явной просьбы выполнить поддерживаемое действие "
                       "верни ровно одну строку !action <команда>. Возможности: " + intents.MODEL_SKILLS +
                       " Не вызывай действие для вопросов, отрицаний и цитат. Результат сообщит игра.")
        else:
            prompt += " Возможности этого подключения ограничены движением и чтением координат через готовые команды."
        messages = [{"role": "system", "content": prompt}, *history, {"role": "user", "content": text}]
        reply = ""
        until = time.monotonic() + 16
        pieces = llm._provider(model)(messages, model, 8)
        try:
            for piece in pieces:
                reply += piece
                if len(reply) >= 440 or time.monotonic() >= until:
                    break
        finally:
            pieces.close()
        reply = " ".join(reply.split())
        limit = 440 if reply.startswith("!action ") and config.get("_minecraft_actions") else 160
        return reply[:limit] or "Не успел ответить. Попробуйте ещё раз."

    def api(self, data, config, events):
        operation = data.get("op")
        if operation == "package_inventory":
            from shelter_core.minecraft_npc import package_jar
            source = self.root / "games" / "minecraft-inventory" / "distribution" / "shelter-inventory-0.1.0.jar"
            return package_jar(self.root, source, "paper")
        if operation == "install":
            self.install()
        elif operation == "connect":
            self.connect(data, config, events)
        elif operation == "disconnect":
            self.disconnect()
        elif operation == "stop":
            self.interrupt()
        elif operation == "cancel_job":
            identifier = data.get("jobId")
            if type(identifier) is not int or not 1 <= identifier < 2**53:
                raise ValueError("Выберите игровую задачу.")
            if not self.request({"op": "cancel_job", "jobId": identifier})["stopped"]:
                raise RuntimeError("Эта игровая задача уже завершилась.")
        elif operation == "inventory_action":
            action = intents.model_command(f"{data.get('action')} {data.get('item')} {data.get('count')}")
            if not action or action["op"] not in {"equip", "give"}:
                raise ValueError("Выберите предмет и количество от 1 до 16.")
            if dict(self.snapshot()["info"].get("items", ())).get(action["item"], 0) < action["count"]:
                raise RuntimeError(ERRORS["not_enough"])
            self.execute({**action, **({"op": "give_stock"} if action["op"] == "give" else {})})
        elif operation == "set_mode":
            action = intents.model_command(f"set_mode {data.get('mode')}")
            if not action:
                raise ValueError("Выберите игровой режим.")
            self.execute(action)
        elif operation == "guard":
            self.execute({"op": "guard"})
        elif operation == "logout":
            with self.lock:
                if self.process is not None:
                    raise RuntimeError("Сначала отключите напарника.")
                directory = self.root / "data" / "minecraft-auth"
                if directory.resolve() != directory.absolute() or directory.is_symlink():
                    raise RuntimeError("Не удалось безопасно сбросить вход Minecraft.")
                if directory.is_dir():
                    shutil.rmtree(directory)
                self.phase, self.error = "idle", ""
        elif operation == "lan":
            folder = Path(os.environ.get("APPDATA") or Path.home()) / ".minecraft"
            return {"port": lan_port(folder / "logs" / "latest.log")}
        else:
            raise ValueError("Неизвестное действие Minecraft.")
        return self.snapshot(poll=False)


MINECRAFT = Companion()
