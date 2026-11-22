"""Персонажи: характер, обращение, голос и внешность — одной командой.

«Джарвис, стань аниме-тянкой» — и у ассистента другой характер (подсказка
модели), другой голос (свой образец для клона, запасной голос без видеокарты)
и вместо HUD-реактора на экране VRM-модель. «Стань Джарвисом» — обратно.

Встроенные персонажи лежат в personas/<id>/persona.json, свои — в
data/personas/<id>/persona.json (их создаёт приложение). Активный — в
data/persona.json: его пишет ядро, а не окно настроек, поэтому сохранение
настроек в приложении его не затирает.
"""

from shelter_core.paths import ROOT_DIR

import copy
import json
import hashlib
import math
import os
import re
import shutil
import threading
import tempfile

ROOT = ROOT_DIR
BUILTIN_DIR = os.path.join(ROOT, "personas")
USER_DIR = os.path.join(ROOT, "data", "personas")
ACTIVE_PATH = os.path.join(ROOT, "data", "persona.json")
DEFAULT_ID = "jarvis"
STARTER_ID = "pippa"
IMPORTED_PRESETS = {
    "pippa": "download-eb02cdc2e98a1137fe53",
    "akai": "download-32a7610b33558bcf9b45",
    "vain": "download-cc5ff9f75cee98a9f802",
    "manju": "download-4e1bf43f1c3bb75b6105",
    "tsukuyomi": "download-cd81161a86671cef6ede",
    "cute": "download-e9688b45e9108bcc8b35",
    "yamaneko": "download-f402175c2288813b0255",
    "miku": "download-fbfe680e64f8fa12a13a",
}
ID_RE = re.compile(r"^[a-z0-9_-]{1,40}$")

_lock = threading.Lock()
_storage_lock = threading.RLock()
_active = None              # словарь активного персонажа
_base = None                # конфиг до наложения персонажа (чтобы вернуться к Джарвису)


# ------------------------------------------------------------------ хранилище

def _read(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: нужен JSON-объект")
    return data


def _folder(persona_id):
    for base in (USER_DIR, BUILTIN_DIR):
        folder = os.path.join(base, persona_id)
        if os.path.isfile(os.path.join(folder, "persona.json")):
            return folder
    return None


def get(persona_id, _seen=()):
    """Персонаж по id с абсолютными путями к файлам; None — нет такого."""
    if not ID_RE.fullmatch(str(persona_id or "")):
        return None
    folder = _folder(persona_id)
    if folder is None:
        return None
    persona = _read(os.path.join(folder, "persona.json"))
    redirect = persona.get("redirect")
    if redirect:
        if persona_id in _seen or len(_seen) > 8:
            return None
        return get(redirect, (*_seen, persona_id))
    persona["id"] = persona_id
    persona["builtin"] = _inside(folder, BUILTIN_DIR)
    persona["folder"] = folder
    styles = persona.get("appearances") or []
    style = next((s for s in styles if s["id"] == persona.get("appearance")), styles[0] if styles else None)
    if style:
        persona["appearance"] = style["id"]
        if not style.get("preview"):
            (persona.get("avatar") or {}).pop("preview", None)
        persona["avatar"] = {**(persona.get("avatar") or {}), **{k: style[k] for k in ("model", "preview", "credit") if k in style}}
    try:
        size = (_read(ACTIVE_PATH).get("sizes") or {}).get(persona_id)
        if type(size) in (int, float) and math.isfinite(size) and 0.2 <= size <= 4:
            persona.setdefault("avatar", {})["scale"] = size
    except (OSError, ValueError, AttributeError):
        pass
    return persona


def all_personas():
    ids = []
    for base in (BUILTIN_DIR, USER_DIR):
        if os.path.isdir(base):
            ids += [d for d in sorted(os.listdir(base)) if d not in ids and _folder(d)]
    result = []
    for persona_id in ids:
        try:
            persona = get(persona_id)
            if persona and persona["id"] == persona_id:
                result.append(persona)
        except (OSError, ValueError) as error:
            print(f"[persona] {persona_id}: {error}")
    current = active_id()
    installed = {p["id"] for p in result}
    hidden = {preset for preset, original in IMPORTED_PRESETS.items() if original in installed and preset != current}
    result = [p for p in result if p["id"] not in hidden]
    order = {STARTER_ID: 0, IMPORTED_PRESETS[STARTER_ID]: 0, DEFAULT_ID: 1, "anime": 2}
    return sorted(result, key=lambda p: (order.get(p["id"], 3), p.get("name", "")))


def resolve(persona, path):
    """Путь из persona.json: относительно папки персонажа, потом — корня проекта."""
    if not path:
        return ""
    if os.path.isabs(path):
        return path
    for base in (persona["folder"], ROOT):
        candidate = os.path.normpath(os.path.join(base, path))
        if os.path.exists(candidate):
            return candidate
    return os.path.normpath(os.path.join(persona["folder"], path))


def starter_id():
    for candidate in (IMPORTED_PRESETS[STARTER_ID], STARTER_ID):
        if get(candidate):
            return candidate
    return DEFAULT_ID


def active_id():
    try:
        value = _read(ACTIVE_PATH).get("active")
        if get(value):
            return value
    except (OSError, ValueError):
        pass
    return starter_id()


def _save_active(persona_id):
    with _storage_lock:
        try:
            state = _read(ACTIVE_PATH)
        except (OSError, ValueError):
            state = {}
        _write_json(ACTIVE_PATH, {**state, "active": persona_id})


def set_size(persona_id, size):
    if not ID_RE.fullmatch(str(persona_id)) or type(size) not in (int, float) or not math.isfinite(size) or not 0.2 <= size <= 4:
        raise ValueError("Размер: от 20 до 400 процентов")
    with _storage_lock:
        try:
            state = _read(ACTIVE_PATH)
        except (OSError, ValueError):
            state = {}
        sizes = state.get("sizes") if isinstance(state.get("sizes"), dict) else {}
        _write_json(ACTIVE_PATH, {**state, "sizes": {**sizes, persona_id: size}})


def _inside(path, folder):
    path, folder = os.path.realpath(path), os.path.realpath(folder)
    try:
        return os.path.commonpath((path, folder)) == folder
    except ValueError:
        return False


def _write_json(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _validate(data):
    if not isinstance(data, dict):
        raise ValueError("нужен объект персонажа")
    for key in ("voice", "avatar", "replace"):
        if key in data and not isinstance(data[key], dict):
            raise ValueError(f"{key}: нужен объект")
    for key in ("aliases", "animations", "appearances", "wake_words"):
        if key in data and not isinstance(data[key], list):
            raise ValueError(f"{key}: нужен список")
    if any(not isinstance(a, str) or len(a) > 120 for a in data.get("aliases", [])):
        raise ValueError("названия: строки до 120 знаков")
    if "wake_words" in data:
        words = data["wake_words"]
        if len(words) > 8 or any(not isinstance(w,str) or not re.fullmatch(r"[а-яёА-ЯЁ]+(?:[ -][а-яёА-ЯЁ]+){0,2}",w.strip()) or len(w)>48 for w in words):
            raise ValueError("Слова вызова: до 8 русских имён, каждое — до 48 знаков и трёх слов")
    for key in ("name", "title", "address", "system", "wake_reply", "switch_reply"):
        if key in data and (not isinstance(data[key], str) or len(data[key]) > 12000):
            raise ValueError(f"{key}: нужна строка до 12000 знаков")
    if data.get("gender", "m") not in ("m", "f"):
        raise ValueError("род: m или f")
    if any(not isinstance(k, str) or not isinstance(v, str) for k, v in data.get("replace", {}).items()):
        raise ValueError("замены: строки")
    if (data.get("voice") or {}).get("effect", "") not in ("", "robot"):
        raise ValueError("эффект голоса: обычный или робот")
    pitch = (data.get("voice") or {}).get("pitch", 1)
    if not isinstance(pitch, (int, float)) or not math.isfinite(pitch) or not 0.75 <= pitch <= 1.5:
        raise ValueError("высота голоса: от 0.75 до 1.5")
    avatar = data.get("avatar") or {}
    if avatar.get("type", "hud") not in ("hud", "vrm"):
        raise ValueError("облик: hud или vrm")
    if avatar.get("lips", "auto") not in ("auto", "audio", "off"):
        raise ValueError("артикуляция: auto, audio или off")
    if type(avatar.get("lip_delay", 0)) not in (int, float) or not math.isfinite(avatar.get("lip_delay", 0)) or not -.1 <= avatar.get("lip_delay", 0) <= .3:
        raise ValueError("задержка губ: от -0.1 до 0.3 секунды")
    for flag in ("reactions", "gaze", "idle_motion"):
        if type(avatar.get(flag, False)) is not bool:
            raise ValueError(flag + ": логическое значение")
    accessories = avatar.get("accessories", [])
    if not isinstance(accessories, list) or len(accessories) > 8:
        raise ValueError("не больше 8 аксессуаров")
    accessory_ids = set()
    for item in accessories:
        if not isinstance(item, dict) or not ID_RE.fullmatch(str(item.get("id", ""))) or item["id"] in accessory_ids:
            raise ValueError("у аксессуара нужен уникальный id")
        accessory_ids.add(item["id"])
        if item.get("bone") not in ("head", "chest", "leftHand", "rightHand") or type(item.get("enabled", True)) is not bool:
            raise ValueError("неверное крепление аксессуара")
        if item.get("builtin") not in (None, "glasses", "headphones", "halo") or not (item.get("builtin") or item.get("file")):
            raise ValueError("выберите встроенный аксессуар или GLB")
        for key, limit in (("position", 1), ("rotation", 180)):
            values = item.get(key)
            if not isinstance(values, list) or len(values) != 3 or any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > limit for v in values):
                raise ValueError("неверное смещение или поворот аксессуара")
        if type(item.get("scale")) not in (int, float) or not math.isfinite(item["scale"]) or not .05 <= item["scale"] <= 3:
            raise ValueError("масштаб аксессуара: 0.05–3")
    if avatar.get("walk", "natural") not in ("natural", "formal"):
        raise ValueError("походка: natural или formal")
    for key, low, high in (("scale", 0.2, 4), ("motion", 0, 1.5), ("bpm", 50, 200)):
        value = avatar.get(key, 1 if key != "bpm" else 120)
        if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"{key}: от {low} до {high}")
    if (avatar.get("framing", "portrait") not in ("portrait", "full")
            or avatar.get("desktop_framing", "full") not in ("portrait", "waist", "full")
            or avatar.get("fps", 30) not in (20, 30, 60)):
        raise ValueError("неверный ракурс или частота кадров")
    seen = set()
    styles = data.get("appearances", [])
    for style in styles:
        if not isinstance(style, dict) or not ID_RE.fullmatch(str(style.get("id", ""))) or not isinstance(style.get("name"), str) or not style.get("model"):
            raise ValueError("у облика нужны id, имя и модель")
        if style["id"] in seen:
            raise ValueError("id облика повторяется")
        seen.add(style["id"])
    if styles and data.get("appearance", styles[0]["id"]) not in seen:
        raise ValueError("нет такого облика")
    seen.clear()
    if len(data.get("animations", [])) > 256:
        raise ValueError("не больше 256 анимаций в одном персонаже")
    roles = set()
    for item in data.get("animations", []):
        if not isinstance(item, dict) or not ID_RE.fullmatch(str(item.get("id", ""))):
            raise ValueError("анимации: нужен уникальный id латиницей")
        if item["id"] in seen or item["id"] in ("wave", "nod", "bow", "dance", "stop"):
            raise ValueError("id анимации занят")
        seen.add(item["id"])
        if not isinstance(item.get("name", ""), str) or type(item.get("loop", False)) is not bool:
            raise ValueError("анимации: название — строка, повтор — логическое значение")
        if item.get("role", "") not in ("", "wave", "nod", "bow", "dance"):
            raise ValueError("неверная роль анимации")
        if item.get("role"):
            if item["role"] in roles:
                raise ValueError("на одну роль назначается одна анимация")
            roles.add(item["role"])
        phrases = item.get("phrases", [])
        if not isinstance(phrases, list) or not phrases or any(not isinstance(p, str) or not 1 <= len(p) <= 120 for p in phrases):
            raise ValueError("у анимации нужны голосовые фразы до 120 знаков")
        if not isinstance(item.get("file"), str) or not item["file"]:
            raise ValueError("выберите файл .vrma")


def _asset_plan(persona, path, extension, limit):
    if not isinstance(path, str):
        raise ValueError("путь должен быть строкой")
    source = resolve(persona, path)
    if not os.path.isfile(source) or os.path.splitext(source)[1].lower() != extension:
        raise ValueError(f"нужен существующий файл {extension}: {path}")
    if os.path.getsize(source) > limit * 1024 * 1024:
        raise ValueError(f"файл больше {limit} МБ")
    return source


def _copy_asset(source, folder):
    if _inside(source, folder):
        return os.path.relpath(source, folder)
    with open(source, "rb") as f:
        digest = hashlib.file_digest(f, "sha256").hexdigest()[:16]
    target = os.path.join(folder, digest + os.path.splitext(source)[1].lower())
    if not os.path.exists(target):
        fd, temporary = tempfile.mkstemp(dir=folder, suffix=".tmp")
        os.close(fd)
        try:
            shutil.copyfile(source, temporary)
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return os.path.basename(target)


def save(data):
    """Создать или изменить своего персонажа. Встроенный сохраняется копией."""
    with _storage_lock:
        return _save(data)


def _save(data):
    _validate(data)
    persona_id = str(data.get("id") or "").lower()
    if not ID_RE.fullmatch(persona_id):
        raise ValueError("id: латиница, цифры, - и _, до 40 знаков")
    if os.path.isfile(os.path.join(BUILTIN_DIR, persona_id, "persona.json")):
        raise ValueError("встроенный персонаж защищён: сохраните копию с другим id")
    name = str(data.get("name") or "").strip()
    if not name:
        raise ValueError("у персонажа должно быть имя")
    folder = os.path.join(USER_DIR, persona_id)
    clean = copy.deepcopy({k: v for k, v in data.items() if k not in ("id", "builtin", "folder", "active")})
    clean["name"] = name
    context = {"folder": folder}
    assets = []
    for section, field, ext, limit in (("voice", "reference", ".wav", 32), ("avatar", "model", ".vrm", 128),
                                      ("avatar", "preview", ".png", 4)):
        if (clean.get(section) or {}).get(field):
            assets.append((clean[section], field, _asset_plan(context, clean[section][field], ext, limit)))
    for item in (clean.get("avatar") or {}).get("accessories", []):
        if item.get("file"):
            assets.append((item, "file", _asset_plan(context, item["file"], ".glb", 16)))
    for item in clean.get("animations", []):
        assets.append((item, "file", _asset_plan(context, item["file"], ".vrma", 32)))
    for style in clean.get("appearances", []):
        for key, ext, limit in (("model", ".vrm", 128), ("preview", ".png", 4)):
            if style.get(key):
                assets.append((style, key, _asset_plan(context, style[key], ext, limit)))
    # Проверить ВСЕ файлы до изменения существующих данных.
    os.makedirs(folder, exist_ok=True)
    for section, field, source in assets:
        section[field] = _copy_asset(source, folder)
    _write_json(os.path.join(folder, "persona.json"), clean)
    if "scale" in (clean.get("avatar") or {}):
        set_size(persona_id, clean["avatar"]["scale"])
    return get(persona_id)


def delete(persona_id):
    with _storage_lock:
        return _delete(persona_id)


def _delete(persona_id):
    persona = get(persona_id)
    if persona is None:
        raise ValueError("нет такого персонажа")
    if not _inside(persona["folder"], USER_DIR):
        raise ValueError("встроенного персонажа удалить нельзя")
    # Варианты, которые ссылаются на этого персонажа, остались бы без модели и голоса.
    for base in (USER_DIR, BUILTIN_DIR):
        for other in (os.listdir(base) if os.path.isdir(base) else []):
            try:
                if other != persona_id and _read(os.path.join(base, other, "persona.json")).get("redirect") == persona_id:
                    raise ValueError(f"на этого персонажа ссылается «{other}» — сначала удалите или измените его")
            except (OSError, ValueError) as error:
                if "ссылается" in str(error):
                    raise
    was_active = active_id() == persona_id
    shutil.rmtree(persona["folder"])
    if was_active:
        _save_active(starter_id())


# ------------------------------------------------------------------ применение

def apply(config, persona=None):
    """Наложить персонажа на конфиг (изменяет config на месте, возвращает персонажа).

    Джарвис (id jarvis) — это ваш config.yaml и настройки приложения как есть.
    """
    global _active, _base
    with _lock:
        if _base is None:
            _base = {path: _copy(_get(config, path)) for path in PATHS}
        persona = persona or get(active_id()) or get(DEFAULT_ID) or {"id": DEFAULT_ID, "name": "Джарвис"}
        # Ключи меняются на месте: потоки ядра держат ссылки на вложенные словари.
        for path, value in _base.items():
            _set(config, path, _copy(value))
        if persona["id"] != DEFAULT_ID:
            if persona.get("system"):
                _set(config, ("llm", "system"), persona["system"])
            voice = persona.get("voice") or {}
            if voice.get("reference"):
                _set(config, ("tts", "clone", "reference"), os.path.relpath(resolve(persona, voice["reference"]), ROOT))
                _set(config, ("tts", "clone", "reference_text"), voice.get("reference_text", ""))
            if voice.get("silero"):
                _set(config, ("tts", "speaker"), voice["silero"])
            if voice.get("piper"):
                _set(config, ("tts", "piper", "voice"), voice["piper"])
            if (persona.get("avatar") or {}).get("type") == "vrm":
                _set(config, ("ui", "mode"), "avatar")
            elif (persona.get("avatar") or {}).get("type") == "hud":
                _set(config, ("ui", "mode"), "hud")
            if persona.get("wake_reply"):
                actions = _get(config, ("wake", "actions"))
                for action in actions if isinstance(actions, list) else []:
                    if action.get("type") == "say":
                        action["text"] = persona["wake_reply"]
                        action.pop("file", None)        # своя запись Джарвиса — не её голос
        _set(config, ("wake", "words"), call_words(persona, config))
        config["persona"] = public(persona)
        _active = persona
        return persona


PATHS = [("llm", "system"), ("tts", "clone", "reference"), ("tts", "clone", "reference_text"),
         ("tts", "speaker"), ("tts", "piper", "voice"), ("ui", "mode"), ("wake", "actions"), ("wake", "words")]
_MISSING = object()


def _copy(value):
    return value if value is _MISSING else copy.deepcopy(value)


def _get(config, path):
    node = config
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return _MISSING
        node = node[key]
    return node


def _set(config, path, value):
    node = config
    for key in path[:-1]:
        node = node.setdefault(key, {})
    if value is _MISSING:
        node.pop(path[-1], None)
    elif path[-1] in ("actions", "words") and isinstance(node.get(path[-1]), list) and isinstance(value, list):
        node[path[-1]][:] = value
    else:
        node[path[-1]] = value


def public(persona):
    """То, что видят приложение и окно персонажа (без лишних путей)."""
    avatar = dict(persona.get("avatar") or {})
    avatar["accessories"] = [dict(item, **({"file": resolve(persona, item["file"])} if item.get("file") else {})) for item in avatar.get("accessories", [])]
    if avatar.get("model"):
        avatar["model"] = resolve(persona, avatar["model"])
    if avatar.get("preview"):
        avatar["preview"] = resolve(persona, avatar["preview"])
    voice = dict(persona.get("voice") or {})
    if voice.get("reference"):
        voice["reference"] = resolve(persona, voice["reference"])
    animations = [dict(item, file=resolve(persona, item["file"])) for item in persona.get("animations", [])]
    styles = [{**s, **{k: resolve(persona, s[k]) for k in ("model", "preview") if s.get(k)}} for s in persona.get("appearances", [])]
    return {k: v for k, v in {**persona, "avatar": avatar, "voice": voice, "animations": animations, "appearances": styles}.items() if k != "folder"}


def active():
    return _active or {"id": DEFAULT_ID, "name": "Джарвис"}


def call_words(persona, config):
    custom = persona.get("wake_words") or []
    if custom:
        return list(dict.fromkeys(w.strip().lower().replace("ё","е") for w in custom))
    base = list((config.get("wake") or {}).get("words") or ["джарвис"])
    if persona.get("id") == DEFAULT_ID:
        return base
    names = re.findall(r"[а-яё]+", str(persona.get("name", "")).lower())
    if not names:
        return base
    name = names[0].replace("ё","е")
    return [name, "пипа"] if name == "пиппа" else [name]


def runtime_call_words(config):
    with _lock:
        return list((config.get("wake") or {}).get("words") or ["джарвис"])


def ensure_model(persona):
    """Встроенная модель аниме-персонажа не входит в установщик — докачать при первом превращении."""
    model = (persona.get("avatar") or {}).get("model", "")
    if not model or os.path.exists(resolve(persona, model)):
        return

    def fetch():
        try:
            from shelter_core import setup_tool
            setup_tool.install_avatar()
            from shelter_core import bus
            bus.publish("persona", persona=public(persona))      # окно перечитает модель
        except Exception as error:
            print(f"[persona] модель не скачалась: {error}")
    if os.path.normpath(model) == os.path.normpath("models/avatars/anime.vrm"):
        threading.Thread(target=fetch, name="avatar-download", daemon=True).start()


def switch(config, persona_id):
    """Сменить персонажа на лету. Возвращает нового персонажа."""
    persona = get(persona_id)
    if persona is None:
        raise ValueError("нет такого персонажа")
    ensure_model(persona)
    _save_active(persona_id)
    return apply(config, persona)


# ------------------------------------------------------------------ речь персонажа

# Готовые фразы ядра написаны от лица Джарвиса — для персонажа-девушки в женском роде.
FEMININE = {w: w + "а" for w in (
    "расслышал", "запомнил", "забыл", "сделал", "отменил", "скопировал", "помнил", "включил", "выключил",
    "замолчал", "понял", "открыл", "закрыл", "поставил", "напечатал", "сохранил", "отправил", "проверил",
    "увидел", "нашёл", "нашел", "смог", "готов", "рад")}
FEMININE.update({"нашёл": "нашла", "нашел": "нашла", "смог": "смогла"})

ADDRESS_FORMS = {      # «сэр» в готовых фразах Джарвиса -> обращение персонажа
    "сэр": "nomn", "сэра": "gent", "сэру": "datv", "сэром": "ablt", "сэре": "loct",
}


def _address_form(address, case):
    if case == "nomn" or " " in address:
        return address
    try:
        from shelter_core import speech_text
        return speech_text._inflect(address, {case, "sing"}, {"NOUN"}) or address
    except Exception:
        return address


def rewrite(text):
    """Готовые фразы ядра («Готово, сэр.») — словами активного персонажа."""
    persona = active()
    if not text or persona["id"] == DEFAULT_ID:
        return text
    address = (persona.get("address") or "").strip()
    if address and address.lower() != "сэр":
        def repl(match):
            word = match.group(0)
            spoken = _address_form(address, ADDRESS_FORMS[word.lower()])
            return spoken[:1].upper() + spoken[1:] if word[:1].isupper() else spoken
        text = re.sub(r"(?<![а-яё])(сэр|сэра|сэру|сэром|сэре)(?![а-яё])", repl, text, flags=re.I)
    replace = dict(FEMININE) if persona.get("gender") == "f" else {}
    replace.update(persona.get("replace") or {})
    for old, new in replace.items():
        text = re.sub(r"(?<![а-яё])" + re.escape(old) + r"(?![а-яё])",
                      lambda m, new=new: new[:1].upper() + new[1:] if m.group(0)[:1].isupper() else new,
                      text, flags=re.I)
    return text


# ------------------------------------------------------------------ голосовая команда

SWITCH_VERBS = r"(?:стань|тань|станет|с\s?тан[а-я]*|становись|превратись(?: в)?|переключись(?: на)?|включи(?: режим)?|режим|смени(?:сь)?(?: на)?|верни(?:сь)?(?: к)?)"


def switch_requested(text):
    """A name/call is not permission for a model to replace the active persona."""
    value = str(text).lower().replace("ё", "е").strip(" ,.!?")
    if re.search(r"\b(?:не|нельзя|запрещаю)\b", value):
        return False
    strong = r"(?:стань|тань|становись|превратись|переключись|смени(?:сь)?|верни(?:сь)?)"
    return bool(re.match(r"^(?:пожалуйста\s+)?(?:давай\s+)?" + strong + r"\b", value) or
                re.match(r"^(?:я\s+)?хочу\s+(?:сменить|поменять|переключить)\s+(?:персонажа|образ|тебя)\b", value) or
                (re.match(r"^(?:включи|режим)\b", value) and find_switch(value)))


def _stems(persona):
    names = [persona.get("name", "")] + list(persona.get("aliases") or [])
    out = []
    for name in names:
        words = re.findall(r"[а-яёa-z]+", name.lower().replace("ё", "е"))
        if words:
            # «аниме-тянкой», «джарвисом»: сравниваем по началу каждого слова.
            out.append([w[:max(3, len(w) - 2)] if len(w) > 4 else w for w in words])
    return out


def find_switch(text):
    """«стань аниме-тянкой» -> id персонажа; None — это не команда смены."""
    q = text.lower().replace("ё", "е").replace("-", " ")
    if re.search(r"\b(?:не|нельзя|запрещаю)\b", q):
        return None
    match = re.fullmatch(r"\s*(?:пожалуйста\s+)?(?:давай\s+)?" + SWITCH_VERBS + r"\s+(?:снова\s+|обратно\s+|в\s+|на\s+|к\s+)?(.+?)\s*[.!]?\s*", q)
    if not match:
        return None
    target = re.sub(r"\bнемо\s*тян", "аниме тян", match.group(1))
    words = [w for w in re.findall(r"[а-яa-z]+", target) if w not in {"пожалуйста", "снова", "обратно"}]
    personas = all_personas()
    exact = " ".join(words)
    for persona in personas:
        if persona.get("builtin") and exact in (persona.get("switch_forms") or ()):
            return persona["id"]
    best = None
    for persona in personas:
        for stem, full in zip(_stems(persona), _names(persona)):
            joined = "".join(words)
            joined_stem, joined_name = "".join(stem), "".join(full)
            compact = len(words) == 1 and len(joined) <= len(joined_name) + 3 and (joined.startswith(joined_stem) or _close(joined, joined_name))
            if len(words) != len(stem) and not compact:
                continue
            tail = words[-len(stem):]
            exact = all(w.startswith(s) for w, s in zip(tail, stem))
            # Распознавание ошибается в букве: «джарлисом» — это «джарвисом».
            fuzzy = not exact and all(_close(w, n) for w, n in zip(tail, full))
            if exact or fuzzy or compact:
                # При равенстве свой персонаж важнее встроенного: «аниме-тянка» —
                # тот, кого человек сам так назвал, а не Юки по умолчанию.
                score = (len(stem) + (0.5 if exact else 0), not persona.get("builtin"))
                if best is None or score > best[1]:
                    best = (persona["id"], score)
    return best[0] if best else None


def _names(persona):
    names = [persona.get("name", "")] + list(persona.get("aliases") or [])
    return [re.findall(r"[а-яёa-z]+", n.lower().replace("ё", "е")) for n in names
            if re.findall(r"[а-яёa-z]+", n.lower())]


def _close(word, name):
    """Похожи ли слово из речи и имя (без падежного окончания)."""
    import difflib
    if len(name) < 5:
        return False                    # «тян», «юки» — только точно, иначе ловит что попало
    return difflib.SequenceMatcher(None, word[:len(name)], name).ratio() >= 0.8


def short_name(name):
    """«Яманэко — белая», «Пиппа — блондинка» -> имя без приписки варианта модели."""
    return re.split(r"\s+[—–-]\s+", str(name or ""), maxsplit=1)[0].strip() or str(name or "")


def character_lines(name, gender="f", address="хозяин"):
    """Характер и фразы для нового персонажа — живые, как у Юки, а не «Теперь я X.»."""
    who = short_name(name)
    if gender == "f":
        return {
            "system": f"Ты {who} — милая и жизнерадостная аниме-девушка, личная помощница хозяина. "
                      f"О себе говоришь в женском роде, к пользователю обращаешься «{address}». Ты заботливая, "
                      "немного озорная и искренне радуешься, когда получается помочь, но отвечаешь точно и по делу: "
                      "отлично разбираешься в компьютерах, играх и технике. Твой ответ будет озвучен, поэтому обычно "
                      "говори по-русски одной-тремя короткими фразами, без эмодзи и без описаний действий в звёздочках. "
                      "Без флирта и пошлостей. Выдумывать факты нельзя: не уверена — так и скажи.",
            "switch_reply": f"Хорошо, {address}! Теперь я {who}, ваша помощница. Чем займёмся?",
            "wake_reply": f"Да, {address}?",
        }
    return {
        "system": f"Ты {who} — личный помощник хозяина. О себе говоришь в мужском роде, к пользователю "
                  f"обращаешься «{address}». Ты дружелюбный, внимательный и отвечаешь точно и по делу: разбираешься "
                  "в компьютерах, играх и технике. Твой ответ будет озвучен, поэтому обычно говори по-русски одной-тремя "
                  "короткими фразами, без эмодзи и без описаний действий в звёздочках. Выдумывать факты нельзя: "
                  "не уверен — так и скажи.",
        "switch_reply": f"Готово, {address}! Теперь я {who}, к вашим услугам.",
        "wake_reply": f"Слушаю, {address}.",
    }
