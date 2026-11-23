"""Loopback connector to the Factorio AI Companion dashboard API."""
import json
import os
import re
import urllib.error
import urllib.request


VERSION = "0.18.3"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("Сервер напарника перенаправил запрос.")


def _call(config, route, payload=None):
    cfg = config.get("factorio") or {}
    port = cfg.get("companion_port", 3210)
    token = cfg.get("companion_token") or os.environ.get("SHELTER_FACTORIO_COMPANION_TOKEN", "")
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("Неверный порт Factorio AI Companion.")
    if not isinstance(token, str) or not 32 <= len(token) <= 512 or any(char.isspace() for char in token):
        raise ValueError("Укажите токен локального сервера Factorio AI Companion.")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{route}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None,
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
    )
    try:
        with opener.open(request, timeout=6) as response:
            result = json.loads(response.read(2_000_000))
    except urllib.error.HTTPError as error:
        if error.code == 401:
            raise ValueError("Factorio AI Companion отклонил токен.") from None
        raise ValueError(f"Factorio AI Companion отклонил запрос (код {error.code}).") from None
    except (OSError, ValueError):
        raise ValueError("Factorio AI Companion не отвечает на этом компьютере.") from None
    if not isinstance(result, dict):
        raise ValueError("Factorio AI Companion вернул неверные данные.")
    if result.get("success") is False or result.get("error"):
        raise ValueError(str(result.get("message") or result.get("error") or "Игровое действие отклонено.")[:280])
    return result


def _state(config):
    data = _call(config, "/api/state")
    if data.get("version") != VERSION:
        raise ValueError(f"Для панели Shelter нужна версия Factorio AI Companion {VERSION}.")
    return data["game"], data["agent"]


def action(config, operation, *, text="", companion_id=None, request_id="", count=None):
    if not isinstance(operation, str):
        raise ValueError("Укажите действие напарника Factorio.")
    game, agent = _state(config)
    snapshot = game.get("snapshot") or {}
    roster = [{"id": item["id"], "name": item["name"],
               "jobs": [name for name, job in (item.get("queues") or {}).items() if job.get("active")]}
              for item in (snapshot.get("companions") or [])[:100] if type(item.get("id")) is int and isinstance(item.get("name"), str)]
    if operation == "status":
        messages = agent.get("messages") or []
        job = next((message for message in reversed(messages) if request_id and message.get("id") == request_id), None)
        return {"connected": bool(game.get("connected")), "enabled": bool(agent.get("enabled")),
                "busy": bool(agent.get("busy")), "queued": int(agent.get("queued") or 0), "companions": roster,
                "authenticated": (agent.get("account") or {}).get("type") == "chatgpt",
                "job": str(job.get("status", "")) if job else ""}
    if operation == "pause":
        _call(config, "/api/agent/pause", {})
        return {"ok": True}
    if operation == "resume":
        if (agent.get("account") or {}).get("type") != "chatgpt":
            raise ValueError("Войдите в ChatGPT в панели Factorio AI Companion.")
        _call(config, "/api/agent/resume", {})
        return {"ok": True}
    if not game.get("connected"):
        raise ValueError("Factorio AI Companion ещё не видит ваш игровой мир.")
    if operation == "spawn":
        if not isinstance(text, str) or len(text.strip()) > 60:
            raise ValueError("Имя напарника должно быть не длиннее 60 знаков.")
        used = {item["id"] for item in roster}
        new_id = next((index for index in range(1, 1001) if index not in used), None)
        if new_id is None:
            raise ValueError("Достигнут предел числа напарников.")
        result = _call(config, "/api/tools/call", {"name": "companion_spawn",
                                                  "args": {"companionId": new_id, "name": text.strip() or "Shelter"}})
        return {"ok": True, "id": new_id, "message": str(result.get("message") or "")[:280]}
    if operation in ("send", "gather", "follow", "stop"):
        if type(companion_id) is not int or companion_id not in {item["id"] for item in roster}:
            raise ValueError("Выберите напарника в игровом мире.")
    if operation == "send":
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 8000:
            raise ValueError("Введите задачу напарнику длиной до 8000 знаков.")
        result = _call(config, "/api/chat", {"message": text.strip(), "companionId": companion_id})
        if not isinstance(result.get("id"), str):
            raise ValueError("Сервер не подтвердил постановку задачи.")
        return {"request_id": result["id"]}
    tools = {"gather": "gather", "follow": "move_follow", "stop": "companion_stop"}
    if operation in tools:
        args = {"companionId": companion_id}
        if operation == "gather":
            if not isinstance(text, str) or not re.fullmatch(r"[a-z0-9_-]{1,160}", text):
                raise ValueError("Укажите ID ресурса для добычи.")
            if type(count) is not int or not 1 <= count <= 1000:
                raise ValueError("Укажите количество для добычи от 1 до 1000.")
            args.update(resource=text, count=count)
        if operation == "follow":
            if not isinstance(text, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,60}", text):
                raise ValueError("Укажите имя игрока для следования.")
            args["playerName"] = text
        _call(config, "/api/tools/call", {"name": tools[operation], "args": args})
        return {"ok": True}
    raise ValueError("Неизвестная операция Factorio AI Companion.")
