"""Отдельный процесс для одного вызова плагина.

Читает из stdin {"entry": путь, "action": имя, "params": {...}, "context": {...}},
вызывает run(params, context) (или функцию action) и пишет в stdout одну строку
JSON {"ok": true, "result": ...} либо {"ok": false, "error": "..."}.
Падение, зависание или утечка памяти плагина остаются здесь: ядро Джарвиса
ждёт ответа с таймаутом и при необходимости завершает этот процесс.

Это не защищённая песочница: у процесса те же права, что у пользователя.
Ставьте только плагины, которым доверяете.
"""

import importlib.util
import json
import os
import sys
import traceback


def main():
    request = json.loads(sys.stdin.readline() or "{}")
    entry = request["entry"]
    sys.path.insert(0, os.path.dirname(entry))
    spec = importlib.util.spec_from_file_location("jarvis_plugin", entry)
    module = importlib.util.module_from_spec(spec)
    real_stdout = sys.stdout
    sys.stdout = sys.stderr                      # print() плагина — в журнал, не в протокол
    try:
        spec.loader.exec_module(module)
        function = getattr(module, request.get("action") or "run", None)
        if not callable(function) and not request.get("strict"):
            function = getattr(module, "run", None)
        if not callable(function):
            raise RuntimeError("в плагине нет функции run(params, context)")
        result = function(request.get("params") or {}, request.get("context") or {})
        json.dumps(result)
        reply = {"ok": True, "result": result}
    except BaseException as error:               # и SystemExit плагина — тоже ответ, а не тишина
        traceback.print_exc()
        reply = {"ok": False, "error": f"{type(error).__name__}: {error}"[:500]}
    sys.stdout = real_stdout
    print(json.dumps(reply), flush=True)          # только ASCII: кодировка консоли не важна


if __name__ == "__main__":
    main()
