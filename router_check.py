"""«Что произойдёт, если сказать…» — проверка фразы настоящим маршрутизатором.

Повторяет порядок голосового цикла: «стоп» → смена персонажа → сценарий по
фразе → быстрые встроенные команды → нейросеть. Ничего не выполняет: быстрые
команды получают перехватчик инструментов, который только записывает вызов.
Несохранённый черновик проверяется отдельно от действующих сценариев.
"""

import difflib
import re

import scenarios

TOOL_TEXT = {
    "app": "открыть программу", "pc": "управление компьютером", "media": "музыка и видео", "home": "умный дом",
    "timer": "таймер или напоминание", "display": "окно Джарвиса", "avatar": "движение персонажа",
    "persona": "смена персонажа", "remember": "запомнить", "forget": "забыть", "timers": "список таймеров",
    "open_source": "открыть источник", "remember_project": "запомнить для проекта",
    "textops": "действие с выделенным текстом", "desktop": "мышь, клавиши и ввод текста",
}


def _norm(text):
    return re.sub(r"\s+", " ", str(text or "").lower().replace("ё", "е")).strip(" .,!?")


def _keyword_hit(keyword, text, words):
    if " " in keyword:
        return keyword in text
    if keyword.endswith("*"):
        return any(w.startswith(keyword[:-1]) for w in words)
    return keyword in words


def _all_matches(text, commands):
    """Все сценарии, чьи фразы подходят (голосовой поиск берёт первый)."""
    import voice
    words = text.split()
    hits = []
    for command in commands:
        single = voice.find_command(text, [command])
        if single is None:
            continue
        keyword = next((k for k in command.get("keywords", []) if _keyword_hit(k, text, words)), "")
        exact = text == keyword.rstrip("*") or (command.get("whole") and bool(keyword))
        hits.append({"scenario": command.get("scenario"), "name": command.get("description", ""),
                     "phrase": keyword, "exact": bool(exact)})
    return hits


def explain(phrase, config, draft=None, semantic=False):
    """-> {route, title, detail, scenario?, calls, alternatives, warnings, ambiguous}."""
    import voice
    import personas
    text = _norm(phrase)
    result = {"phrase": phrase, "route": "llm", "title": "", "detail": "", "scenario": None, "calls": [],
              "alternatives": [], "warnings": [], "ambiguous": False, "match": ""}
    if not text:
        result.update(route="empty", title="Введите фразу")
        return result
    words = [w for w in (config.get("wake") or {}).get("words") or ["джарвис"]]
    heard, _cmd, rest = voice.match(text, words, [])
    if heard:
        text = _norm(rest)
        result["detail"] = "Обращение услышано. "
        if not text:
            result.update(route="wake", title="Джарвис откликнется и будет ждать команду")
            return result
    if text in voice.STOP_WORDS:
        result.update(route="stop", title="Остановит речь и закроет Джарвиса",
                      detail=result["detail"] + "Без разговора «стоп» ставит на паузу то, что играет.")
        return result

    items = scenarios.load(config) if draft is None else _with_draft(config, draft)
    commands = scenarios.as_commands(items)

    target = personas.find_switch(text)
    if target:
        name = (personas.get(target) or {}).get("name", target)
        result.update(route="persona", title=f"Сменит персонажа на «{name}»", calls=[{"tool": "persona", "arg": target}])
        return result

    hits = _all_matches(text, commands)
    if hits:
        first = hits[0]
        item = next((i for i in items if i["id"] == first["scenario"]), None)
        result.update(route="scenario", scenario=first["scenario"], match="точно" if first["exact"] else "по слову",
                      title=f"Запустит сценарий «{item['name'] if item else first['name']}»",
                      detail=result["detail"] + f"Совпала фраза «{first['phrase']}»" + ("" if first["exact"] else
                             " — как отдельное слово в просьбе"))
        if item:
            result["plan"] = scenarios.plan(item)["steps"]
            if item.get("confirm"):
                result["detail"] += f". Сначала спросит: «{item['confirm']}»"
        if len(hits) > 1:
            result["ambiguous"] = True
            result["alternatives"] = [{"scenario": h["scenario"], "name": h["name"], "phrase": h["phrase"]} for h in hits[1:]]
            result["warnings"].append("Фраза подходит к нескольким сценариям — сработает первый в списке. "
                                      "Уточните фразы, чтобы не было неоднозначности.")
        return result

    import fastpath
    calls = []

    def collect(name, arg):
        calls.append({"tool": name, "arg": arg, "text": TOOL_TEXT.get(name, name)})
        return "done", ""

    try:
        raw = str(phrase).strip()
        # Preserve dictated case and punctuation in a preview, just as at runtime.
        start = raw.lower().find(rest) if heard else -1
        request = raw[start:start + len(rest)] if start >= 0 else text if heard else raw
        handled = fastpath.handle(request, config, run_tool=collect, dry=True)
    except Exception as error:
        handled = None
        result["warnings"].append(f"Встроенные команды не проверены: {error}")
    if handled is not None:
        reply, _acted = handled
        result.update(route="builtin", calls=calls,
                      title="Выполнит встроенную команду: " + ", ".join(c["text"] for c in calls) if calls else "Ответит сразу, без нейросети",
                      detail=result["detail"] + (f"Ответ: «{reply}»" if reply else ""))
        if any(c["tool"] == "pc" and c["arg"].startswith("close") for c in calls):
            result["detail"] += " Закроет окно этой программы (как крестик), а не Джарвиса."
        return result

    if not (config.get("llm") or {}).get("enabled", True):
        result.update(route="none", title="Не поймёт: нейросеть выключена, и команды с такой фразой нет")
    else:
        result.update(route="llm", title="Передаст нейросети: она ответит или выберет действие сама",
                      detail=result["detail"] + "Это дольше и зависит от модели. Для частой просьбы сделайте сценарий.")
        if semantic:
            import desktop_intent
            import json
            intent = desktop_intent.classify(request, config)
            if intent["decision"] == "execute":
                result.update(route="semantic", title="Поняла действие по смыслу: " + intent["command"]["operation"],
                    calls=[{"tool":"desktop", "arg":json.dumps(intent["command"],ensure_ascii=False), "text":TOOL_TEXT["desktop"]}],
                    detail="Проверен разбор намерения. При разговоре основная модель ещё должна выбрать этот инструмент. Ничего не выполнено.")
            elif intent["decision"] == "clarify":
                result.update(route="semantic", title="Нужно уточнение", detail=intent["question"], ambiguous=True)
            else:
                result["detail"] += " Смысловой разбор не нашёл просьбы к мыши, клавиатуре или полю ввода."
    phrases = {p: i for i in items for p in i.get("phrases") or []}
    close = difflib.get_close_matches(text, [p.rstrip("*") for p in phrases], n=3, cutoff=0.72)
    for phrase in close:
        item = phrases.get(phrase) or phrases.get(phrase + "*")
        if item:
            result["alternatives"].append({"scenario": item["id"], "name": item["name"], "phrase": phrase})
    if result["alternatives"]:
        result["warnings"].append("Похоже на фразу сценария, но не совпало — возможно, распознавание ошибётся так же.")
    return result


def _with_draft(config, draft):
    items = [i for i in scenarios.load(config) if i["id"] != draft.get("id")]
    return [scenarios.normalize(draft)] + items


def conflicts(config, draft=None):
    """Пересечения: одна фраза у двух сценариев, фраза = имя персонажа или обращение."""
    import personas
    items = scenarios.load(config) if draft is None else _with_draft(config, draft)
    wake = {_norm(w) for w in (config.get("wake") or {}).get("words") or []}
    owners = {}
    found = []
    for item in items:
        if item.get("enabled", True):
            for phrase in item.get("phrases") or []:
                owners.setdefault(phrase.rstrip("*"), []).append(item)
    for item in items:
        if not item.get("enabled", True):
            continue
        for phrase in item.get("phrases") or []:
            key = phrase.rstrip("*")
            for other in owners.get(key, []):
                if other["id"] != item["id"]:
                    found.append({"scenario": item["id"], "phrase": phrase,
                                  "text": f"«{phrase}» уже есть в сценарии «{other['name']}»"})
            if any(w and (key == w or key.startswith(w + " ")) for w in wake):
                found.append({"scenario": item["id"], "phrase": phrase,
                              "text": f"«{phrase}» начинается с обращения — Джарвис примет её за своё имя"})
            if personas.find_switch(key):
                found.append({"scenario": item["id"], "phrase": phrase,
                              "text": f"«{phrase}» — это смена персонажа; сценарий не сработает"})
            if key in ("стоп", "хватит", "замолчи", "отмена", "достаточно"):
                found.append({"scenario": item["id"], "phrase": phrase,
                              "text": f"«{phrase}» занята: она останавливает Джарвиса"})
    if draft is not None:
        found = [f for f in found if f["scenario"] == draft.get("id")]
    return found
