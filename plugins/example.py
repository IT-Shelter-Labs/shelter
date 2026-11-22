"""Минимальный пример пользовательского действия Jarvis."""


def run(params, context):
    message = params.get("message", "Плагин работает")
    print(f"[plugin example] {message}")
    return {"project_dir": context["project_dir"]}

