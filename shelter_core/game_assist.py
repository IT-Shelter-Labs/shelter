"""Local Factorio telemetry and opt-in game-screen assistance."""
from shelter_core.paths import ROOT_PATH

import json
import math
import os
import re
import time
import zipfile
from pathlib import Path

ROOT = ROOT_PATH
MOD = "shelter_factorio_0.2.0"
SNAPSHOT = "shelter-factorio.json"
FACTORIO = r"(?:factorio|факторио)"
HOI4 = r"(?:hoi\s*4|hearts of iron(?: iv| 4)?|хойк[аеу]|хои\s*4)"


def build_mod(destination, branch="2.0"):
    if branch not in ("2.0", "2.1"):
        raise ValueError("Выберите Factorio 2.0 или 2.1.")
    source = ROOT / "games" / "factorio" / MOD
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        info = json.loads((source / "info.json").read_text(encoding="utf-8"))
        info["factorio_version"] = branch
        archive.writestr(f"{MOD}/info.json", json.dumps(info, indent=2))
        archive.write(source / "control.lua", f"{MOD}/control.lua")
    return destination


def path_for(config):
    custom = (config.get("factorio") or {}).get("snapshot")
    if custom:
        return Path(custom)
    home = Path(os.environ["APPDATA"]) / "Factorio" if os.environ.get("APPDATA") else Path.home() / ".factorio"
    return home / "script-output" / SNAPSHOT


def build_hoi4_mod(destination):
    source = ROOT / "games" / "hoi4"
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(source).as_posix())
    return destination


def snapshot(path):
    if path.name.casefold() != SNAPSHOT:
        raise ValueError(f"Выберите файл {SNAPSHOT} из папки script-output.")
    try:
        with path.open("rb") as source:
            data = json.loads(source.read(512_000))
        age = max(0, int(time.time() - path.stat().st_mtime))
    except (OSError, ValueError):
        raise ValueError("Нет читаемых данных Factorio. Загрузите мир с модом и введите /shelter-export.") from None
    if not isinstance(data, dict) or data.get("format") != "shelter-factorio-1":
        raise ValueError("Экспорт Factorio выключен или файл относится к другой версии мода.")
    fields = ("player", "surface", "research")
    if any(not isinstance(data.get(key), str) or len(data[key]) > 120 for key in fields):
        raise ValueError("Файл Factorio содержит неверные данные.")
    if any(type(data.get(key)) not in (int, float) or not math.isfinite(data[key]) or abs(data[key]) > 10_000_000
           for key in ("x", "y", "progress")):
        raise ValueError("Файл Factorio содержит неверные координаты или прогресс.")
    inventory = data.get("inventory") or []
    if not isinstance(inventory, list):
        raise ValueError("Файл Factorio содержит неверный инвентарь.")
    inventory = sorted(({"name": item["name"], "count": item["count"]} for item in inventory if isinstance(item, dict)
                        and isinstance(item.get("name"), str) and len(item["name"]) <= 160
                        and type(item.get("count")) is int and 0 < item["count"] < 100_000_000),
                       key=lambda item: (-item["count"], item["name"]))
    job = data.get("job")
    if not (isinstance(job, dict) and isinstance(job.get("recipe"), str)
            and re.fullmatch(r"[a-zA-Z0-9_-]{1,160}", job["recipe"])
            and job.get("state") in ("waiting", "crafting", "stopped", "complete", "blocked", "timeout")
            and type(job.get("done")) is int and type(job.get("total")) is int
            and 0 <= job["done"] <= job["total"] <= 100):
        job = None
    return {**{key: data[key] for key in (*fields, "x", "y", "progress")}, "age": age, "inventory": inventory[:12],
            "job": {key: job[key] for key in ("recipe", "state", "done", "total")} if job else None}


def factorio_reply(question, config):
    data = snapshot(path_for(config))
    prefix = "По последнему снимку Factorio. " if data["age"] > 10 else ""
    if re.search(r"инвентар|рюкзак|предмет", question, re.I):
        parts = [f"{item['name']}: {item['count']}" for item in data["inventory"][:6]]
        return prefix + ("В инвентаре больше всего: " + ", ".join(parts) + "." if parts else "Инвентарь пуст.")
    research = (f"Исследуется {data['research']}, готово {min(100, max(0, data['progress'] * 100)):.0f}%."
                if data["research"] else "Активного исследования нет.")
    if re.search(r"исследован|технолог", question, re.I):
        return prefix + research
    return prefix + f"Вы на поверхности {data['surface']}, координаты {data['x']:.0f}, {data['y']:.0f}. {research}"


def answer(question, config, *, guest=False):
    text = " ".join(question.strip(" ,.?!").split())
    if re.search(FACTORIO, text, re.I) and re.search(r"^(?:(?:в|по) )?" + FACTORIO + r"[, :]|в " + FACTORIO + "$", text, re.I):
        if guest:
            return "Данные игры доступны только владельцу."
        try:
            return factorio_reply(text, config)
        except ValueError as error:
            return str(error)
    if not re.search(HOI4, text, re.I) or not re.search(r"^(?:посмотри|опиши|разбери|помоги|что видно|какие (?:у меня |мои )?дивизии)\b", text, re.I):
        return None
    if guest:
        return "Обзор игры доступен только владельцу."
    from shelter_core import llm
    from shelter_core import policy
    from shelter_core import screen

    model_config = config.get("llm") or {}
    if not policy.allowed(config, "screen") or not model_config.get("enabled") or model_config.get("vision") is False:
        return "Для обзора Hearts of Iron IV включите зрение и модель в настройках."
    try:
        shot = screen.snapshot(expected_title=r"Hearts of Iron (?:IV|4)\b")
        if not shot["image"]:
            return "Не удалось получить изображение Hearts of Iron IV."
        return llm.describe_image(text, shot, model_config)
    except (OSError, RuntimeError, ValueError) as error:
        print(f">> GAME VIEW  //  {type(error).__name__}")
        return "Откройте Hearts of Iron IV на переднем плане и проверьте настройки модели зрения."
