"""Простые команды без нейросети: ответ быстрее на 0.2–0.4 с и работает без Ollama.

Только однозначные фразы: «открой Firefox», «громкость на 30», «таймер на 5
минут», «выключи свет», «который час». Всё, что не узнали уверенно, уходит
модели как обычно.
"""

import datetime
import re
import json

from shelter_core import tools

UNITS = (("час", 3600), ("мин", 60), ("сек", 1))
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
          "сентября", "октября", "ноября", "декабря"]
WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]


def duration(text):
    """«пять минут», «полчаса», «1 час 20 минут», «90 секунд» -> секунды или None."""
    text = text.lower()
    if "полчаса" in text:
        return 1800
    if "полтора часа" in text:
        return 5400
    total = 0
    for chunk in re.split(r"(?<=[а-я])\s+(?=\d|[а-я]+\s+(?:час|мин|сек))", text):
        unit = next((seconds for word, seconds in UNITS if word in chunk), None)
        value = tools.number(chunk)
        if unit and value:
            total += value * unit
    return total or None


def plan(question, config):
    """Resolve a conjunction fully before executing any of its clauses."""
    from shelter_core import desktop_input
    if desktop_input.resolve(question): return None
    parts = re.split(r"\s*(?:,\s*)?\b(?:а затем|и затем|и потом|затем|потом|после этого|и)\b\s*", question, flags=re.I)
    if not 2 <= len(parts) <= 6:
        return None
    from shelter_core import personas
    if any(personas.find_switch(part.strip()) for part in parts):
        return None
    result = []
    from shelter_core import policy
    for part in parts:
        part = re.sub(r"^сначала\s+", "", part.strip(), flags=re.I)
        calls = []
        def collect(name, arg):
            if not policy.allowed(config, name):
                return "fail", "Эта возможность выключена в настройках, сэр."
            calls.append((name, arg))
            return "done", ""
        resolved = handle(part, config, collect, dry=True)
        if resolved is None or not calls:
            return None
        result.append((calls, resolved[0]))
    return result


def handle(question, config, run_tool=None, dry=False):
    """(реплика, действие_выполнено) или None — тогда дальше думает модель.

    dry — проверка фразы в окне: ничего не выполнять, только понять, что было бы."""
    q = question.lower().strip(" .!?,").replace("ё", "е")
    if run_tool is None:
        if dry:
            run_tool = lambda name,arg:("done","")
        else:
            from shelter_core.main import run_tool as execute
            run_tool = lambda name, arg: execute(config, name, arg)

    def invoke(name, arg, success):
        outcome, reply = run_tool(name, arg)
        return (success if outcome == "done" else reply), outcome == "done"

    from shelter_core import desktop_input
    desktop = desktop_input.resolve(question)
    if desktop:
        outcome,reply=run_tool("desktop",json.dumps(desktop,ensure_ascii=False))
        return reply,outcome=="done"

    # «Стань аниме-тянкой», «верни Джарвиса» — смена персонажа.
    from shelter_core import personas
    from shelter_core import avatar_motion
    if re.fullmatch(r"(?:а |ну )?(?:что (?:ты )?умеешь|что ты можешь|какие у тебя (?:возможности|функции)|расскажи (?:о своих возможностях|что ты умеешь)|умеешь)(?: делать)?", q):
        from shelter_core import policy
        labels = [("app", "открывать программы и сайты"), ("pc", "управлять окнами и громкостью"),
                  ("timer", "ставить таймеры и напоминания"), ("memory", "запоминать важное по вашей просьбе"),
                  ("weather", "узнавать погоду"), ("media", "управлять музыкой")]
        enabled = [label for name, label in labels if policy.allowed(config, name)]
        if (config.get("llm") or {}).get("enabled"):
            enabled.insert(0, "отвечать на вопросы")
        person = config.get("persona") or personas.active()
        address = person.get("address", "сэр")
        if not enabled:
            return f"Сейчас мои действия отключены, {address}. Включите нужные возможности в настройках.", False
        return f"Я могу {', '.join(enabled[:4])}, {address}. Свои команды и сочетания действий можно добавить в разделе «Команды».", False
    # Жесты и переходы — только у персонажа с 3D-моделью; у Джарвиса фразу разбирает модель.
    has_body = (config.get("ui") or {}).get("mode") == "avatar"
    # Вопрос о помощнике — разговор, а не команда собрать сводку всех систем.
    if re.fullmatch(r"(?:(?:ну|че|что|а) )?(?:как (?:у тебя )?дела|как ты|как поживаешь|как твои дела)(?: у тебя)?", q):
        person = config.get("persona") or personas.active()
        ready = "готова" if person.get("gender") == "f" else "готов"
        return f"Всё хорошо, {person.get('address', 'сэр')}. Я здесь и {ready} помочь. А у вас как дела?", False
    size = avatar_motion.resize_command(q)
    if size is not None and has_body:
        outcome, reply = run_tool("avatar", json.dumps({"action": "resize", **size}))
        return reply, outcome == "done"
    # «Работай без окна», «режим кругляша», «покажи окно» — как показываться.
    from shelter_core import display
    presence = display.presence_command(q)
    if presence:
        return invoke("display", presence[0], presence[1])
    mode = display.mode_command(q)
    if mode:
        return invoke("display", "mode | " + mode[0], mode[1])
    destination = avatar_motion.movement(q)
    if destination and has_body:
        return invoke("avatar", json.dumps({"action": "move", **destination}), "Возвращаюсь на исходное место." if destination["position"] == "home" else "Перехожу.")
    if destination:
        # Обычный Джарвис тоже переезжает: окно HUD — на другой монитор или в угол.
        # Угол не назван («на второй монитор») — встать как обычно на том мониторе.
        position = "bottom-right" if destination["position"] == "home" else destination["position"] if re.search(r"угол|углу|лев|прав|верх|низ|центр|середин", q) else ""
        return invoke("display", f"move | {destination['monitor']} | {position}", "Перехожу, сэр.")
    motion = avatar_motion.command(q, personas.active()) if has_body else None
    if motion:
        return invoke("avatar", json.dumps({"action": motion["animation"], **{k: v for k, v in motion.items() if k != "animation"}}), "Хорошо.")
    target = personas.find_switch(q)
    if target:
        if target == personas.active()["id"]:
            return f"Я и так {personas.get(target).get('name', '')}, " + ("хозяин." if personas.get(target).get("gender") == "f" else "сэр."), False
        if dry:
            run_tool("persona", target)
            return f"Сменю персонажа на «{personas.get(target).get('name', target)}».", True
        from shelter_core.main import switch_persona
        return switch_persona(config, target), True

    match = re.fullmatch(r"запомни(?: для проекта)?[,: ]+(.+)", question.strip(), re.I)
    if match:
        return invoke("remember_project" if "для проекта" in q[:25] else "remember", match[1], "Запомнил, сэр.")
    if q in ("что ты обо мне знаешь", "что ты помнишь обо мне", "моя память"):
        from shelter_core import policy
        if not policy.allowed(config, "memory"):
            return "Память выключена в настройках, сэр.", False
        from shelter_core import memory
        facts = memory.facts()
        return ("Я помню: " + "; ".join(facts[-8:]) if facts else "Вы пока не просили меня ничего запомнить, сэр."), False
    match = re.fullmatch(r"забудь(?: про)?[,: ]+(.+)", question.strip(), re.I)
    if match:
        return invoke("forget", match[1], "Забыл, сэр.")

    if re.fullmatch(r"(который час|сколько (сейчас )?времени|сколько время)", q):
        return f"Сейчас {datetime.datetime.now():%H:%M}, сэр.", False
    if re.fullmatch(r"(какое сегодня число|какой сегодня день|какое сегодня число и день)", q):
        now = datetime.datetime.now()
        return f"Сегодня {WEEKDAYS[now.weekday()]}, {now.day} {MONTHS[now.month - 1]}, сэр.", False

    match = re.fullmatch(r"(?:поставь |заведи |включи )?таймер на (.+)", q)
    if match:
        seconds = duration(match.group(1))
        if seconds:
            return invoke("timer", str(seconds), f"Таймер на {match.group(1)}, сэр.")

    match = re.fullmatch(r"(?:сделай |поставь )?громкость (?:на )?(.+?)(?: процентов| процента| процент)?", q)
    if match and tools.number(match.group(1)) is not None:
        value = max(0, min(100, tools.number(match.group(1))))
        return invoke("pc", f"volume | {value}", f"Громкость {value} процентов, сэр.")

    match = re.fullmatch(r"(включи|выключи|погаси|зажги|включить|выключить) (.+)", q)
    if match:
        from shelter_core import smarthome
        if smarthome.enabled(config):
            action = "off" if match.group(1).startswith(("выкл", "пога")) else "on"
            try:
                device = smarthome.find(match.group(2))
            except smarthome.AmbiguousDevice as error:
                return str(error), False
            if device:
                return invoke("home", f"{device['name']} | {action}", f"Готово, {device['name']}, сэр.")

    if q in ("какие таймеры", "какие у меня таймеры", "какие у меня напоминания"):
        return invoke("timers", "", "")
    if q in ("отмени выключение", "отмени перезагрузку"):
        return invoke("pc", "cancel", "Выключение отменено, сэр.")
    match = re.fullmatch(r"(выключи|перезагрузи) компьютер(?: через (.+))?", q)
    if match:
        return invoke("pc", ("shutdown" if match[1] == "выключи" else "restart")
                      + " | " + str(duration(match[2]) if match[2] else 60), "Готово, сэр.")
    match = re.fullmatch(r"напомни через (.+?) (.+)", q)
    if match:
        # Split at a time unit, keeping the complete reminder label.
        timed = re.match(r"(.+?(?:секунд\w*|минут\w*|час\w*))\s+(.+)", q.removeprefix("напомни через "))
        if timed and duration(timed[1]):
            return invoke("timer", f"{duration(timed[1])} | {timed[2]}", "Напомню, сэр.")
    # Текст в любой программе: «исправь выделенное», «переведи это», «вставь».
    match = re.fullmatch(r"(исправь|переведи|сократи|объясни|подготовь ответ|ответь|прочитай)(?: на)? (?:выделенное|выделенный текст|это|выделение)(?: вслух)?", q)
    if match:
        op = {"исправь": "fix", "переведи": "translate", "сократи": "shorten", "объясни": "explain",
              "подготовь ответ": "reply", "ответь": "reply", "прочитай": "read"}[match[1]]
        outcome, reply = run_tool("textops", op)
        return reply, outcome == "done"
    if q in ("вставь", "замени", "вставь результат", "замени выделенное", "вставь исправленное", "вставь перевод"):
        return invoke("textops", "apply", "Заменил, сэр.")
    # Видео на весь экран: выйти — Esc, войти — F11 (раньше «сверни/разверни …» — про окно).
    if re.fullmatch(r"(?:выйди|выйти|выход|убери|выключи|сверни)(?: из)? (?:полноэкранн\w*|полн\w* экран\w*|весь экран)(?: режим\w*)?", q):
        return invoke("pc", "fullscreen | off", "Готово, сэр.")
    if re.fullmatch(r"(?:сделай|разверни|открой|включи)(?: на)? (?:весь экран|полноэкранный(?: режим)?)", q):
        return invoke("pc", "fullscreen | on", "Готово, сэр.")
    # Воспроизведение в любом плеере и в браузере.
    media_action = next((action for pattern, action in (
        (r"(?:поставь )?(?:на )?пауз[ауы]?|останови (?:видео|музыку|воспроизведение)", "pause"),
        (r"(?:продолжи|продолжай|сними с паузы|включи дальше)(?: видео| музыку| воспроизведение)?", "play"),
        (r"(?:следующ\w*|переключи)(?: трек| песн\w*| видео| серию)?", "next"),
        (r"предыдущ\w*(?: трек| песн\w*| видео| серию)?", "previous")) if re.fullmatch(pattern, q)), None)
    if media_action:
        return invoke("media", media_action, "Готово, сэр.")
    # «Сверни все окна» — это рабочий стол, а не окно с названием «все окна».
    if re.fullmatch(r"(?:сверни|скрой|убери|спрячь) (?:все|всё)(?: окна| программы| приложения| вкладки)?"
                    r"|(?:покажи|открой|верни) рабочий стол|(?:разверни|верни|восстанови|покажи) (?:все |обратно )?окна(?: обратно)?", q):
        return invoke("pc", "desktop", "Готово, сэр.")
    if re.fullmatch(r"закрой (?:все|всё)(?: окна| программы| приложения)?", q):
        return "Закрывать всё разом не стану, сэр: можно потерять несохранённое. Могу свернуть все окна.", False
    match = re.fullmatch(r"(сверни|закрой|разверни) (.+)", q)
    if match:
        return invoke("pc", {"сверни": "minimize", "закрой": "close", "разверни": "maximize"}[match[1]]
                      + " | " + match[2], "Готово, сэр.")

    # «Открой источник» — страница, по которой Джарвис только что ответил из интернета.
    match = re.fullmatch(r"(?:открой|покажи) (?:мне )?(источник|ссылку|первую ссылку|сайт|страницу|статью|википедию)", q)
    if match:
        sources = list(tools.SOURCES)
        if not sources:
            return "Источников пока нет — сначала спросите что-нибудь из интернета, сэр.", False
        title, url = sources[0]
        if "википед" in match[1]:
            title, url = next((s for s in sources if s[0].startswith("Википедия")), sources[0])
        if dry:
            run_tool("open_source", url)
            return f"Открою «{title}».", True
        import os
        os.startfile(url)
        return f"Открываю «{title.removeprefix('Википедия ')}», сэр.", True

    match = re.fullmatch(r"(?:открой|запусти) (.+)", q)
    if match:
        target = match.group(1)
        norm = tools._norm(target)
        app = tools.find_app(target)
        # Только уверенное совпадение: название, известный псевдоним, браузер или сайт.
        confident = (norm in tools.APP_ALIASES or norm in tools.BROWSER_WORDS or norm in tools.SITES
                     or (app and norm in tools._norm(app["name"])))
        if confident:
            return invoke("app", target, f"Открываю {target}, сэр.")
    return None
