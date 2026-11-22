"""Проверка подключений из окна — отдельно от сохранения и только на чтение.

Окно присылает значения из формы (ещё не сохранённые): проверяем, что сервис
отвечает и что доступ есть, ничего не включая и не выключая. Ответ без
секретов: только итог, число найденных устройств и понятная причина ошибки.
"""

import urllib.error


def _reason(error):
    if isinstance(error, urllib.error.HTTPError):
        return {401: "неверный токен или нет доступа", 403: "доступ запрещён — у токена нет прав",
                404: "по этому адресу нет нужного API"}.get(error.code, f"сервис ответил ошибкой {error.code}")
    text = str(getattr(error, "reason", error))
    if "timed out" in text or "timeout" in text:
        return "сервис не ответил вовремя — проверьте адрес и что он включён"
    if "getaddrinfo" in text or "Name or service" in text:
        return "адрес не найден в сети"
    if "refused" in text.lower() or "10061" in text:
        return "соединение отклонено — сервис выключен или другой порт"
    return text[:200]


def test(data, config):
    kind = str(data.get("kind") or "")
    from shelter_core import smarthome
    try:
        if kind == "homeassistant":
            url = str(data.get("url") or "").rstrip("/")
            token = str(data.get("token") or "")
            if not url.startswith(("http://", "https://")):
                return {"ok": False, "text": "Адрес должен начинаться с http:// или https://"}
            if not token:
                return {"ok": False, "text": "Нужен долгосрочный токен доступа"}
            found = smarthome._ha_discover({"url": url, "token": token})
            return {"ok": True, "text": f"Home Assistant отвечает. Устройств для голоса: {len(found)}",
                    "items": [d["name"] for d in found[:12]]}
        if kind == "yandex":
            token = str(data.get("token") or "")
            if not token:
                return {"ok": False, "text": "Нужен OAuth-токен с правом iot:control"}
            found = smarthome._yandex_discover({"token": token})
            return {"ok": True, "text": f"Умный дом Яндекса отвечает. Устройств: {len(found)}",
                    "items": [d["name"] for d in found[:12]]}
        if kind == "obs":
            from shelter_core import obs
            client = obs.Client({"url": str(data.get("url") or "ws://127.0.0.1:4455"),
                                 "password": str(data.get("password") or "")})
            try:
                ok, _code, info = client.request("GetVersion")
            finally:
                client.close()
            return {"ok": bool(ok), "text": f"OBS {info.get('obsVersion', '')} отвечает, WebSocket {info.get('obsWebSocketVersion', '')}"}
        if kind == "telegram":
            from shelter_core import telegram_bot
            token = str(data.get("token") or "")
            if ":" not in token:
                return {"ok": False, "text": "Ключ бота выглядит как 123456:ABC… — его выдаёт @BotFather"}
            return telegram_bot.check(token)
        return {"ok": False, "text": "Для этого подключения проверки пока нет"}
    except Exception as error:   # сеть, токен, OBS — любая причина возвращается человеку
        return {"ok": False, "text": _reason(error)}
