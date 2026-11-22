"""Strict game-only command grammar, shared by desktop speech and owner chat."""

from functools import lru_cache
import json
import os
from pathlib import Path
import re


NUMBERS = dict(zip("один два три четыре пять шесть семь восемь девять десять одиннадцать двенадцать тринадцать четырнадцать пятнадцать шестнадцать".split(), range(1, 17)))
NUMBERS.update(одну=1, одно=1, две=2)
NUMBERS.update(двух=2, трех=3, четырех=4, пяти=5, шести=6, семи=7, восьми=8,
               девяти=9, десяти=10, одиннадцати=11, двенадцати=12, тринадцати=13,
               четырнадцати=14, пятнадцати=15, шестнадцати=16)
ITEMS = {
    "oak_log": (r"дубов\w* (?:бревен|бревн\w*|дерев\w*|древесин\w*)", r"(?:дуб|бревен|бревн\w*|дерев(?:о|а|ьев)|древесин\w*)"),
    "spruce_log": (r"елов\w* (?:бревен|бревн\w*|древесин\w*)", r"ель"),
    "birch_log": (r"березов\w* (?:бревен|бревн\w*|древесин\w*)", r"берез\w*"),
    "stone": (r"камня|камень|каменн\w* блок\w*",), "cobblestone": (r"булыжник\w*", r"к[ао]б[бел]*л?стоун\w*"),
    "dirt": (r"земл\w*", r"гряз\w*"), "sand": (r"песок", r"песка"),
    "coal_ore": (r"угольн\w* руд\w*",), "coal": (r"уголь|угля",),
    "oak_planks": (r"дубов\w* дос(?:ки|ка|ок|ку)", r"дос(?:ки|ка|ок|ку) (?:дубов\w*|из дуба)"),
    "birch_planks": (r"березов\w* дос\w*",), "spruce_planks": (r"елов\w* дос\w*",),
    "planks": (r"(?:люб\w+ )?дос(?:ки|ка|ок|ку)",), "axe": (r"топор\w*",),
    "pickaxe": (r"кирк\w*",), "sword": (r"меч\w*",), "shovel": (r"лопат\w*",),
    "stick": (r"пал(?:ки|ка|ок|ку)",), "crafting_table": (r"верстак\w*",), "torch": (r"факел\w*",),
}
GAME_NAME = r"(?:майнкрафт[еа]?|minecraft)"
MOD_ITEM = r"[a-z0-9][a-z0-9_.-]{0,31}:[a-z0-9][a-z0-9_./-]{0,63}"
SCOPE = re.compile(r"(?:в\s+)?" + GAME_NAME, re.I)
HELP = "В Minecraft можно попросить: где ты находишься, иди за мной, телепортируйся ко мне, покажи инвентарь или подготовь и принеси четыре дубовые доски."
MODEL_SKILLS = ("status, position, nearby, game_mode, come, follow, guard, eat, fish, teleport, stop; navigate <x> <y> <z>; "
                "set_mode <survival|creative|adventure|spectator>; "
                "give|deliver|mine|craft|equip|obtain <item> <count>; build <wall|floor|line> <item> <count>. "
                "Составная цель: sequence <команда> | <команда> (до 5 действий, без follow и guard). "
                "item — английский ID Minecraft или группа planks, log, pickaxe, axe, shovel, sword. "
                "Для любых досок используй planks. Количество 1–16. give ищет предмет и рецепты, deliver готовит и приносит.")


@lru_cache(maxsize=4096)
def _item_words(text):
    from speech_text import morph
    analyzer = morph()
    words = re.findall(r"[\w]+", text.casefold().replace("ё", "е"))
    if analyzer:
        normalized = []
        for word in words:
            forms = analyzer.parse(word)
            form = next((p for p in forms if p.tag.POS in ("NOUN", "ADJF") and p.is_known), forms[0])
            normalized.append(form.normal_form.replace("ё", "е"))
        words = normalized
    return " ".join(words)


@lru_cache(maxsize=3)
def localized_items(version=""):
    """Use the installed Java client's translations; the bridge validates IDs against its own version."""
    root = Path(os.environ.get("APPDATA") or Path.home()) / ".minecraft"
    assets = root / "assets"
    indices = sorted((assets / "indexes").glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if re.fullmatch(r"\d+(?:\.\d+){1,2}", version):
        try:
            metadata = json.loads((root / "versions" / version / (version + ".json")).read_bytes())
            index = metadata["assetIndex"]["id"]
            if re.fullmatch(r"\d+(?:\.\d+)*", index):
                indices.insert(0, assets / "indexes" / (index + ".json"))
        except (OSError, ValueError, KeyError, TypeError):
            pass
    for path in indices:
        try:
            digest = json.loads(path.read_bytes())["objects"]["minecraft/lang/ru_ru.json"]["hash"]
            if not re.fullmatch(r"[a-f0-9]{40}", digest):
                continue
            labels = json.loads((assets / "objects" / digest[:2] / digest).read_bytes())
        except (OSError, ValueError, KeyError, TypeError):
            continue
        exact, normalized = {}, {}
        for key, label in labels.items():
            match = re.fullmatch(r"(?:block|item)\.minecraft\.([a-z0-9_]+)", key)
            if not match:
                continue
            item = match[1]
            for catalog, name in ((exact, label.casefold().replace("ё", "е")), (normalized, _item_words(label))):
                catalog[name] = item if name not in catalog or catalog[name] == item else ""
        return exact, normalized
    return {}, {}


def resolve_item(text, version=""):
    text = text.casefold().replace("ё", "е")
    for name, aliases in ITEMS.items():
        if any(re.fullmatch(alias, text) for alias in aliases):
            return name
    if re.search(r"[а-я]", text):
        exact, normalized = localized_items(version)
        return exact.get(text) or normalized.get(_item_words(text)) or ""
    return text.replace(" ", "_").removeprefix("minecraft:")


@lru_cache(maxsize=3)
def item_labels(version):
    return {item: label for label, item in localized_items(version)[0].items() if item}


def model_command(text):
    if isinstance(text, str) and text.startswith("sequence "):
        steps = text.removeprefix("sequence ").split("|")
        allowed = {"come", "navigate", "give", "deliver", "mine", "craft", "equip", "obtain", "build", "eat", "fish"}
        if not 2 <= len(steps) <= 5 or any(step.strip().startswith("sequence ") for step in steps):
            return None
        actions = [model_command(step.strip()) for step in steps]
        if all(action and action["op"] in allowed for action in actions):
            return {"op": "sequence", "actions": actions}
        return None
    parts = str(text).strip().lower().split()
    if len(parts) == 1 and parts[0] in {"status", "position", "nearby", "game_mode", "come", "follow", "guard", "eat", "fish", "teleport", "stop"}:
        return {"op": parts[0]}
    if len(parts) == 4 and parts[0] == "navigate" and all(re.fullmatch(r"-?\d{1,8}", n) for n in parts[1:]):
        return {"op": "navigate", **dict(zip("xyz", map(int, parts[1:])))}
    if len(parts) == 2 and parts[0] == "set_mode" and parts[1] in {"survival", "creative", "adventure", "spectator"}:
        return {"op": "set_mode", "mode": parts[1]}
    if len(parts) in (3, 4):
        op, item, count = parts[0], parts[-2].removeprefix("minecraft:"), parts[-1]
        if not re.fullmatch(r"[a-z0-9_]{1,48}|" + MOD_ITEM, item) or not re.fullmatch(r"(?:[1-9]|1[0-6])", count):
            return None
        command = {"op": op, "item": item, "count": int(count)}
        if len(parts) == 4 and op == "build" and parts[1] in {"wall", "floor", "line"}:
            return {**command, "shape": parts[1]}
        if len(parts) == 3 and op in {"give", "deliver", "mine", "craft", "equip", "obtain"}:
            return command
    return None


def scoped(text):
    cleaned = text.strip(" ,.?!:;")
    prefix = re.match(SCOPE.pattern + r"[\s,:]+", cleaned, re.I)
    if prefix:
        return cleaned[prefix.end():].strip()
    suffix = re.search(r"[\s,]+в\s+" + GAME_NAME + "$", cleaned, re.I)
    return cleaned[:suffix.start()].strip(" ,") if suffix else None


def parse(text, version=""):
    text = " ".join(re.sub(r"[,?!;]+|(?<![a-z0-9_])[.:]|[.:](?![a-z0-9_])", " ",
                           text.lower().replace("ё", "е")).split())
    text = " ".join(word for word in text.split() if word != "пожалуйста")
    text = re.sub(r"^(?:а |можешь (?:ли )?|не мог бы ты )", "", text)
    simple = {
        "stop": r"стоп|стой|остановись|прекрати(?: добычу| движение)?|перестань (?:копать|добывать|идти)|stop|stay",
        "guard": r"(?:защищай|защити|охраняй|прикрой) меня|(?:defend|guard|protect) me",
        "nearby": r"что (?:ты видишь вокруг|рядом с тобой)|какие мобы рядом|nearby",
        "eat": r"поешь|подкрепись|eat",
        "fish": r"порыбачь|полови рыбу|поймай рыбу|fish",
        "come": r"(?:подойди|иди|подбеги) (?:ко мне|сюда)|подойд[ие]|come(?: here| to me)?",
        "follow": r"(?:иди|пойдем|следуй|беги|ходи) за мной|следуй|follow(?: me)?",
        "teleport": r"(?:телепортируйся|телепортироваться|телепортнись|тепнись|тпшнись|телепортируй(?: себя)?)(?: прямо)? (?:ко мне|сюда)|teleport (?:to me|here)",
        "position": (
            r"(?:(?:скажи|назови|покажи|сообщи)(?: мне)? )?(?:(?:свои|твои) )?координаты"
            r"|(?:(?:скажи|покажи)(?: мне)? )?где (?:ты(?: сейчас)?(?: находишься| стоишь)?|находишься)(?: сейчас)?"
            r"|на каких координатах ты|какие у тебя координаты|where are you|coordinates"
            r"|(?:правда ли|верны ли|откуда ты взял) (?:твои |прошлые |эти )?координаты"
        ),
        "game_mode": (
            r"какой (?:у тебя )?(?:сейчас )?(?:игровой )?режим(?: у тебя)?(?: сейчас)?(?: выставлен| установлен| включен)?"
            r"|(?:ты )?в каком (?:игровом )?режиме (?:ты (?:сейчас )?)?(?:играешь|находишься)|(?:what is your )?game ?mode"
        ),
        "connection": r"ты (?:сейчас )?подключен(?:а)? к (?:игре|серверу|миру|майнкрафту)|are you connected to (?:the game|minecraft)",
        "status": r"(?:(?:покажи|показать)(?: мне)? )?(?:(?:свой|твой) )?инвентарь|что (?:у тебя )?в инвентаре|что (?:ты )?несешь|статус|inventory|status",
        "help": r"помощь|что ты умеешь|команды|help",
    }
    for operation, pattern in simple.items():
        if re.fullmatch(pattern, text):
            return {"op": operation}
    destination = re.fullmatch(r"(?:иди|подойди|перейди) (?:к координатам|на координаты) (-?\d{1,8}) (-?\d{1,8}) (-?\d{1,8})", text)
    if destination:
        return model_command("navigate " + " ".join(destination.groups()))
    modes = {"survival": r"выживани\w*|survival", "creative": r"творческ\w*|креатив\w*|creative",
             "spectator": r"наблюдател\w*|spectator", "adventure": r"приключени\w*|adventure"}
    for mode, pattern in modes.items():
        if re.fullmatch(r"(?:смен(?:и|ить)|поменяй|переключи|переключись|перейди|установи|поставь|включи|set|switch)"
                        r"(?: (?:свой|себе|игровой|режим|game|mode|to|на|в))* (?:" + pattern + r")(?: режим)?", text):
            return {"op": "set_mode", "mode": mode}
    building = re.fullmatch(r"(?:построй|поставь|build) (стену|ряд|линию|площадку|пол|wall|line|floor) (?:из |of )?(.+)", text)
    if building:
        material = parse("скрафти " + building[2], version)
        if material and material["op"] == "craft":
            shape = {"стену": "wall", "ряд": "line", "линию": "line", "площадку": "floor", "пол": "floor"}.get(building[1], building[1])
            return {**material, "op": "build", "shape": shape,
                    "count": material["count"] if re.search(r"\d|\b(?:" + "|".join(NUMBERS) + r")\b", building[2]) else 4}
    equip = re.fullmatch(r"(?:возьми в руку|экипируй|equip|hold) (.+)", text)
    if equip:
        selected = parse("дай " + equip[1], version)
        if selected and selected["op"] == "give":
            return {**selected, "op": "equip", "count": 1}
    delivery = re.fullmatch(r"(?:подготовь и принеси(?: мне)?|prepare and bring(?: me)?) (.+)", text)
    if delivery:
        result = parse("скрафти " + delivery[1], version)
        if result and result["op"] == "craft":
            return {**result, "op": "deliver"}
        return result if result and result["op"] == "invalid" else {"op": "invalid", "error": "item"}
    action = re.fullmatch(r"(добудь|добывай|добыть|достань|собери|накопай|выкопай|сломай|сруби|наруби|скрафти|сделай|создай|передай|отдай|дай|принеси|mine|collect|craft|give)(?: мне| me)? (.+)", text)
    if not action:
        return None
    verb, target = action.groups()
    operation = "craft" if verb in ("скрафти", "сделай", "создай", "craft") else "give" if verb in ("передай", "отдай", "дай", "принеси", "give") else "mine"
    parts = target.split()
    raw_count = next((part for part in (parts[0], parts[-1]) if (part.isascii() and part.isdigit()) or part in NUMBERS), None)
    count = 1
    if raw_count:
        count = NUMBERS[raw_count] if raw_count in NUMBERS else int(raw_count) if len(raw_count) <= 3 else 17
        parts.pop(0 if parts[0] == raw_count else -1)
    if not 1 <= count <= 16:
        return {"op": "invalid", "error": "count"}
    if len(parts) > 1 and parts[0] in ("блок", "блока", "блоков", "штук", "штуки", "штуку") and not resolve_item(" ".join(parts), version):
        parts.pop(0)
    target = " ".join(parts)
    item = resolve_item(target, version)
    if not raw_count and operation == "give" and (item == "planks" or item.endswith("_planks")):
        count = 4
    if item == "coal" and operation == "mine":
        item = "coal_ore"
    if operation == "mine" and (item == "planks" or item.endswith("_planks")) and verb not in ("сломай", "выкопай", "сруби", "наруби", "mine"):
        operation = "obtain"
    modded = bool(re.fullmatch(MOD_ITEM, item))
    if not modded and (not re.fullmatch(r"[a-z0-9_]{1,48}", item)
                       or (operation == "mine" and item == "bedrock")):
        return {"op": "invalid", "error": "item"}
    return {"op": operation, "item": item, "count": count}


def desktop(text, connected, *, allow_implicit=True, version=""):
    """Only known game intents route implicitly; ordinary requests stay on the desktop."""
    game = scoped(text)
    if game is not None:
        parsed = parse(game, version)
        if parsed and (parsed.get("error") != "item" or not connected):
            return parsed
        return None if connected else {"op": "help"}
    parsed = parse(text, version) if allow_implicit else None
    if not parsed or parsed["op"] in ("stop", "help", "invalid"):
        return None
    if not connected and (parsed["op"] == "game_mode" and not re.search(r"игровой|играешь|game", text, re.I)
                          or parsed["op"] not in ("game_mode", "connection")):
        return None
    return parsed
