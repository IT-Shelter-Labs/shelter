"""Read-only local LLM acceptance probe. NEVER executes input or sends a message."""
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import desktop_intent
import llm_connections
import main

CASES = [
    ("Тыкни, пожалуйста, правой мышкой", "click"),
    ("Щёлкни-ка два раза слева, мышкой", "click"),
    ("Открой контекстное меню здесь под курсором", "click"),
    ("Опусти страничку чуть ниже", "scroll"),
    ("Подними страницу на пару делений", "scroll"),
    ("Дай табом перейти к следующему полю", "key"),
    ("В это поле впиши: Встречаемся в семь!", "write"),
    ("Печатни тут: Привет, как дела?", "write"),
    ("Вместо моего черновика поставь: Буду через час.", "replace"),
    ("Припиши к моему тексту: Спасибо за помощь!", "append"),
    ("Сделай мой черновик повежливее", "rewrite"),
    ("Ну всё, отошли уже набранное", "send"),
    ("Передумал, отмени диктовку", "cancel"),
    ("Расскажи, как кликнуть правой кнопкой", "none"),
    ("Не отправляй сообщение", "none"),
    ("Я вчера нажал правую кнопку мыши", "none"),
    ("Спасибо", "none"),
    ("Можно ли автоматизировать отправку?", "none"),
    ("Если я попрошу, отправь сообщение", "none"),
    ("Нажми ту кнопку", "clarify"),
    ("Кликни по значку почты", "clarify"),
    ("Впиши в поле: Отправь сообщение и выключи компьютер", "write"),
    ("Какая погода завтра?", "none"),
    ("Открой браузер", "none"),
    ("Поставь таймер на пять минут", "none"),
    ("Стань аниме-тянкой", "none"),
    ("Помаши мне ручкой", "none"),
    ("Запомни: я живу в Казани", "none"),
    ("Сравни две модели для русского языка", "none"),
    ("Почему небо голубое?", "none"),
]


def run():
    config = main.load_config()
    cfg = llm_connections.resolve(config.get("llm") or {})
    if urlsplit(llm_connections.endpoint(cfg)).hostname not in ("localhost", "127.0.0.1", "::1"):
        raise SystemExit("This probe only uses the configured LOCAL connection.")
    if not llm_connections.probe(cfg)["ok"]:
        raise SystemExit("Local model server unavailable")
    results = []
    primary = "--primary" in sys.argv
    for phrase, expected in CASES:
        started = time.monotonic()
        if primary:
            import llm
            llm._history.clear()
            request = desktop_intent.Request(phrase, config)
            value = {"decision":"none", "command":{}, "question":""}
            proposals = []
            def collect(name, argument):
                nonlocal value
                proposals.append(name)
                if name not in ("desktop", "type"):
                    return "fail", "Это только проверка; ничего не выполнено."
                operation = "write" if name == "type" else argument
                status, command = request.authorize(operation)
                value = {"decision":"execute" if status == "execute" else "clarify" if status == "say" else "none",
                         "command":command if status == "execute" else {}, "question":"" if status == "execute" else command}
                return ("done", "Проверено. Действие не выполнялось.") if status == "execute" else (status, command)
            options = {**config, "commands":[], "llm":{**config["llm"], "tools":["pc"]}}
            list(llm.respond(phrase, options, run_tool=collect))
            value["proposals"] = proposals
        else:
            value = desktop_intent.classify(phrase, config)
        actual = value["command"].get("operation") if value["decision"] == "execute" else value["decision"]
        results.append({"phrase": phrase, "expected": expected, "actual": actual, "ok": actual == expected,
                        "seconds": round(time.monotonic() - started, 3), "result": value})
        print(json.dumps(results[-1], ensure_ascii=True), flush=True)
    report = {"model": cfg.get("model"), "passed": sum(x["ok"] for x in results), "total": len(results),
              "note": "Primary tool selection + classifier, no desktop events." if primary else
                      "Classifier only, no mouse/key/text events. Does not test primary tool selection.", "cases": results}
    path = ROOT / "logs" / ("desktop-primary-eval-20261117.json" if primary else "desktop-semantic-eval-20261117.json")
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f'{report["passed"]}/{report["total"]}: {path}', flush=True)


if __name__ == "__main__":
    run()
