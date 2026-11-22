"""Умный дом: «Джарвис, выключи свет», «включи чайник», «яркость на половину».

Модель пишет тег [home: устройство | действие], здесь он превращается в запрос
к нужной системе. Действия: on, off, toggle, set N (яркость/уровень в процентах,
для термостата — градусы).

Поддерживаются:
  homeassistant — Home Assistant (REST API, долгоживущий токен). Через него
                  работают Tuya, Xiaomi, Zigbee, Sonoff и сотни других брендов.
  yandex        — Умный дом Яндекса (api.iot.yandex.net, OAuth-токен):
                  розетки, лампы, чайники, подключённые к Алисе.
  tuya          — Tuya напрямую по локальной сети (pip install tinytuya,
                  нужны id, ip и local_key устройства).
  webhook       — любой HTTP-адрес на включение и выключение (ESPHome,
                  Shelly, самодельные устройства, IFTTT).

Токены берутся из переменных окружения, в config.yaml только их имена.
"""

import netfix  # noqa: F401 — локальное мимо системного прокси
import difflib
import json
import os
import re
import threading
import urllib.request
import tasks
import policy

_devices = []          # [{"name", "aliases", "via", ...}]
_lock = threading.Lock()


class AmbiguousDevice(LookupError):
    pass


class StateUnverified(RuntimeError):
    pass


def needs_confirmation(name):
    device = find(name)
    if device is None:
        raise LookupError(f"Не знаю устройства «{name}», сэр.")
    entities = device.get("entities") or [device.get("entity", "")]
    return bool(device.get("confirm")) or any(e.split(".")[0] in ("lock", "climate", "water_heater", "script", "scene") for e in entities)


def _http(method, url, token=None, body=None, timeout=6):
    tasks.check()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
    return json.loads(raw) if raw.strip() else {}


def _token(cfg, default_env):
    return os.environ.get(cfg.get("token_env", default_env), "") or cfg.get("token", "")


def _norm(text):
    return re.sub(r"\s+", " ", re.sub(r"[^\w ]+", " ", str(text).lower().replace("ё", "е"))).strip()


# ---------------------------------------------------------- Home Assistant

HA_DOMAINS = ("light", "switch", "fan", "climate", "cover", "media_player",
              "input_boolean", "humidifier", "vacuum", "water_heater", "lock", "scene", "script")


def _ha_discover(cfg):
    states = _http("GET", cfg.get("url", "http://homeassistant.local:8123").rstrip("/") + "/api/states",
                   _token(cfg, "HA_TOKEN"))
    found = []
    for state in states:
        entity = state.get("entity_id", "")
        name = (state.get("attributes") or {}).get("friendly_name")
        if name and entity.split(".")[0] in HA_DOMAINS:
            attrs = state.get("attributes") or {}
            found.append({"name": name, "via": "homeassistant", "entity": entity,
                          "min_temp": attrs.get("min_temp"), "max_temp": attrs.get("max_temp")})
    return found


def _ha_act(device, action, value, cfg):
    url = cfg.get("url", "http://homeassistant.local:8123").rstrip("/")
    token = _token(cfg, "HA_TOKEN")
    entities = device.get("entities") or [device["entity"]]
    for index, entity in enumerate(entities):
        domain = entity.split(".")[0]
        body = {"entity_id": entity}
        if domain in ("scene", "script"):
            service, domain_call = "turn_on", domain
        elif action == "set" and domain == "climate":
            service, domain_call = "set_temperature", "climate"
            low, high = device.get("min_temp"), device.get("max_temp")
            if low is None or high is None or not float(low) <= value <= float(high):
                raise ValueError("Температура вне разрешённого диапазона устройства или диапазон неизвестен.")
            body["temperature"] = value
        elif action == "set" and domain == "light":
            service, domain_call = "turn_on", "light"
            body["brightness_pct"] = max(1, min(100, int(value)))
        elif action == "set" and domain == "fan":
            service, domain_call = "set_percentage", "fan"
            body["percentage"] = max(0, min(100, int(value)))
        elif action == "set" and domain == "cover":
            service, domain_call = "set_cover_position", "cover"
            body["position"] = max(0, min(100, int(value)))
        elif action == "set" and domain == "media_player":
            service, domain_call = "volume_set", "media_player"
            body["volume_level"] = max(0, min(100, int(value))) / 100
        elif domain == "cover":
            service, domain_call = {"on": "open_cover", "off": "close_cover"}.get(action, "toggle"), "cover"
        elif domain == "lock":
            service, domain_call = {"on": "lock", "off": "unlock"}.get(action, "lock"), "lock"
        else:
            service = {"on": "turn_on", "off": "turn_off", "set": "turn_on"}.get(action, "toggle")
            domain_call = "homeassistant"
        try:
            _http("POST", f"{url}/api/services/{domain_call}/{service}", token, body)
        except OSError:
            if index:
                raise StateUnverified("Часть устройств уже получила команду, остальные не ответили. Проверьте состояние в Home Assistant.") from None
            raise
        if domain not in ("scene", "script"):
            try:
                state = _http("GET", f"{url}/api/states/{entity}", token)
                if state.get("state") in (None, "unknown", "unavailable"):
                    raise ValueError("состояние неизвестно")
                expected = ({"on": "locked", "off": "unlocked"} if domain == "lock" else
                            {"on": "open", "off": "closed"} if domain == "cover" else
                            {"on": "on", "off": "off"} if domain in ("light", "switch", "fan", "input_boolean") else {})
                if action in expected and state["state"] != expected[action]:
                    raise ValueError("состояние ещё не изменилось")
            except (OSError, ValueError):
                raise StateUnverified("Команда отправлена, но состояние устройства не подтверждено. Проверьте его в Home Assistant.") from None


# ------------------------------------------------------------ Яндекс

YANDEX_API = "https://api.iot.yandex.net/v1.0"


def _yandex_discover(cfg):
    info = _http("GET", f"{YANDEX_API}/user/info", _token(cfg, "YANDEX_IOT_TOKEN"))
    rooms = {room["id"]: room["name"] for room in info.get("rooms", [])}
    found = []
    for device in info.get("devices", []):
        caps = [c.get("type", "") + ":" + str((c.get("parameters") or {}).get("instance", ""))
                for c in device.get("capabilities", [])]
        aliases = []
        if device.get("room") in rooms:
            aliases.append(f"{device['name']} в {rooms[device['room']]}")
        found.append({"name": device["name"], "aliases": aliases, "via": "yandex",
                      "id": device["id"], "caps": caps})
    return found


def _yandex_act(device, action, value, cfg):
    caps = device.get("caps") or ["devices.capabilities.on_off:on"]
    if action == "set":
        instance = next((c.split(":")[1] for c in caps if c.startswith("devices.capabilities.range")
                         and c.split(":")[1] in ("brightness", "temperature", "volume", "humidity", "open")),
                        "brightness")
        capability = {"type": "devices.capabilities.range",
                      "state": {"instance": instance, "value": value}}
    else:
        if action == "toggle":
            state = _http("GET", f"{YANDEX_API}/devices/{device['id']}", _token(cfg, "YANDEX_IOT_TOKEN"))
            current = next((c["state"]["value"] for c in state.get("capabilities", [])
                            if c.get("type") == "devices.capabilities.on_off" and c.get("state")), False)
            target = not current
        else:
            target = action == "on"
        capability = {"type": "devices.capabilities.on_off", "state": {"instance": "on", "value": target}}
    result = _http("POST", f"{YANDEX_API}/devices/actions", _token(cfg, "YANDEX_IOT_TOKEN"),
                   {"devices": [{"id": device["id"], "actions": [capability]}]})
    for item in result.get("devices", []):
        for cap in item.get("capabilities", []):
            status = ((cap.get("state") or {}).get("action_result") or {}).get("status")
            if status == "ERROR":
                raise RuntimeError("Яндекс отказал: " + str(cap["state"]["action_result"].get("error_message", "")))
            if status != "DONE":
                raise StateUnverified("Яндекс принял запрос, но выполнение ещё не подтверждено.")
    if not result.get("devices"):
        raise StateUnverified("Яндекс не подтвердил выполнение команды.")


# ------------------------------------------------------------- Tuya

def _tuya_act(device, action, value, cfg):
    try:
        import tinytuya
    except ImportError as error:
        raise RuntimeError("для Tuya нужен пакет tinytuya: pip install tinytuya") from error
    kind = tinytuya.BulbDevice if device.get("kind") == "bulb" else tinytuya.OutletDevice
    unit = kind(device["id"], device.get("ip", "Auto"), device["key"])
    unit.set_version(float(device.get("version", 3.3)))
    unit.set_socketTimeout(3)
    switch = int(device.get("switch", 1))
    if action == "set" and device.get("kind") == "bulb":
        result = unit.set_brightness_percentage(max(1, min(100, int(value))))
        if isinstance(result, dict) and result.get("Error"):
            raise RuntimeError("Tuya: " + str(result["Error"]))
        return
    if action == "toggle":
        status = unit.status() or {}
        if status.get("Error") or str(switch) not in (status.get("dps") or {}):
            raise RuntimeError("Tuya: состояние неизвестно, переключение отменено")
        action = "off" if (status.get("dps") or {}).get(str(switch)) else "on"
    result = unit.turn_on(switch=switch) if action in ("on", "set") else unit.turn_off(switch=switch)
    if isinstance(result, dict) and result.get("Error"):
        raise RuntimeError("Tuya: " + str(result["Error"]))


# ----------------------------------------------------------- Webhook

def _webhook_act(device, action, value, cfg):
    url = device.get(action) or device.get("on" if action == "set" else "toggle")
    if not url:
        raise RuntimeError(f"у «{device['name']}» нет адреса для «{action}»")
    url = str(url).replace("{value}", str(int(value or 0)))
    method = str(device.get("method", "POST")).upper()   # Shelly и Tasmota — GET, ESPHome — POST
    request = urllib.request.Request(url, method=method,
                                     data=b"" if method == "POST" else None)
    urllib.request.urlopen(request, timeout=6).read()


ADAPTERS = {"homeassistant": _ha_act, "yandex": _yandex_act, "tuya": _tuya_act, "webhook": _webhook_act}
DISCOVERY = {"homeassistant": _ha_discover, "yandex": _yandex_discover}


# ------------------------------------------------------------ общее

def enabled(config):
    cfg = config.get("smarthome") or {}
    return bool(cfg.get("enabled")) and bool(cfg.get("devices") or any(
        (cfg.get(name) or {}).get("auto") for name in DISCOVERY))


def load(config):
    """Собрать список устройств: из config.yaml и (по желанию) из HA и Яндекса."""
    global _devices
    cfg = config.get("smarthome") or {}
    devices = [dict(device) for device in cfg.get("devices") or [] if device.get("name")]
    for system, discover in DISCOVERY.items():
        sub = cfg.get(system) or {}
        if not sub.get("auto"):
            continue
        try:
            known = {_norm(d["name"]) for d in devices}
            devices += [d for d in discover(sub) if _norm(d["name"]) not in known]
        except Exception as error:
            print(f"[home] {system}: не получить список устройств — {error}")
    with _lock:
        _devices = devices
    if devices:
        print(f">> SMART HOME  //  устройств: {len(devices)}")
    return devices


def names():
    """Названия устройств для подсказки модели."""
    with _lock:
        return [d["name"] for d in _devices]


def _alias_table():
    with _lock:
        table = {}
        for device in _devices:
            for alias in [device["name"]] + list(device.get("aliases") or []):
                key = _norm(alias)
                if key:
                    table.setdefault(key, {})[id(device)] = device
    return table


def _unique_device(devices):
    unique = {id(device): device for device in devices}
    if len(unique) != 1:
        names = sorted({d["name"] for d in unique.values()})
        raise AmbiguousDevice("Уточните устройство: " + ", ".join(names) + ".")
    return next(iter(unique.values()))


def _approximate_device(wanted, table):
    ranked = sorted(((difflib.SequenceMatcher(None, wanted, key).ratio(), key) for key in table),
                    key=lambda pair: pair[0], reverse=True)
    if not ranked or ranked[0][0] < 0.75:
        return None
    candidates = [device for score, key in ranked if ranked[0][0] - score < 0.12 for device in table[key].values()]
    device = _unique_device(candidates)
    if any(e.startswith(("lock.", "climate.", "water_heater.")) for e in
           (device.get("entities") or [device.get("entity", "")])):
        return None
    return device


def find(name):
    wanted = _norm(name)
    table = _alias_table()
    if not wanted or not table:
        return None
    if wanted in table:
        return _unique_device(table[wanted].values())
    partial = [device for key in table if wanted in key or key in wanted for device in table[key].values()]
    if partial:
        return _unique_device(partial)
    return _approximate_device(wanted, table)


_ACTIONS = {word: action for action, words in (
    ("on", "on включи включить зажги зажечь"),
    ("off", "off выключи выключить отключи отключить погаси погасить закрой закрыть"),
    ("toggle", "toggle переключи переключить")) for word in words.split()}


def parse_action(text):
    """«on», «включи», «set 50», «50», «половина» -> (действие, число|None)."""
    from tools import number_exact
    text = str(text).lower().strip().replace(",", ".")
    if text in _ACTIONS:
        return _ACTIONS[text], None
    value = number_exact(text.removeprefix("set "))
    if value is not None:
        return "set", value
    raise ValueError("Неизвестное действие устройства")


def act(name, action_text, config):
    """Выполнить действие. Возвращает название устройства; бросает исключение при неудаче."""
    tasks.check()
    policy.require(config, "home")
    if not enabled(config):
        raise PermissionError("Умный дом выключен в настройках.")
    device = find(name)
    if device is None:
        raise LookupError(f"устройство «{name}» не найдено")
    action, value = parse_action(action_text)
    via = device.get("via", "homeassistant")
    adapter = ADAPTERS.get(via)
    if adapter is None:
        raise RuntimeError(f"неизвестная система «{via}»")
    tasks.check()
    adapter(device, action, value, (config.get("smarthome") or {}).get(via) or {})
    return device["name"]
