"""Discord bot REST calls for an explicitly configured guild, user and channel."""
import json
import os
import re
import urllib.error
import urllib.request

from app_version import VERSION


SNOWFLAKE = re.compile(r"[0-9]{16,22}")
BASE = "https://discord.com/api/v10"


def _id(cfg, key):
    value = str(cfg.get(key) or "")
    if not SNOWFLAKE.fullmatch(value):
        raise ValueError(f"Заполните {key} в настройках Discord.")
    return value


def _request(cfg, route, payload=None):
    token = cfg.get("bot_token") or os.environ.get("SHELTER_DISCORD_BOT_TOKEN")
    if not token:
        raise ValueError("Укажите токен бота Discord.")
    headers = {"Authorization": "Bot " + token, "User-Agent": f"DiscordBot (https://github.com/IT-Shelter-Labs/shelter, {VERSION})",
               "Content-Type": "application/json"}
    request = urllib.request.Request(BASE + route, headers=headers,
                                     data=json.dumps(payload).encode() if payload is not None else None)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.loads(response.read(256_000))
    except urllib.error.HTTPError as error:
        if error.code == 404:
            try:
                body = json.loads(error.read(4096))
            except ValueError:
                body = {}
            if body.get("code") == 10065:  # Unknown Voice State.
                return None
        message = {401: "Discord отклонил токен бота.", 403: "Discord не разрешил боту доступ к каналу.",
                   404: "Discord не нашёл указанный сервер, канал или пользователя.",
                   429: "Discord ограничил частоту запросов. Повторите позже."}
        raise ValueError(message.get(error.code, f"Discord вернул ошибку {error.code}.")) from None
    except OSError:
        raise ValueError("Не удалось связаться с Discord.") from None


def voice_state(cfg):
    guild, user = _id(cfg, "guild_id"), _id(cfg, "user_id")
    result = _request(cfg, f"/guilds/{guild}/voice-states/{user}")
    if not result or not result.get("channel_id"):
        return None
    if any(type(result.get(key)) is not bool for key in ("self_mute", "self_deaf", "mute", "deaf")):
        raise ValueError("Discord не вернул полное состояние звука.")
    return {key: result[key] for key in ("self_mute", "self_deaf", "mute", "deaf")}


def voice_status(cfg):
    state = voice_state(cfg)
    if state is None:
        return "Вы сейчас вне голосового канала Discord."
    mic = "выключен сервером" if state["mute"] else "выключен" if state["self_mute"] else "включён"
    sound = "выключен сервером" if state["deaf"] else "выключен" if state["self_deaf"] else "включён"
    return f"Discord подтвердил: микрофон {mic}, звук {sound}."


def notify(cfg, text):
    channel, guild = _id(cfg, "channel_id"), _id(cfg, "guild_id")
    text = text.strip()
    if not 1 <= len(text) <= 1800:
        raise ValueError("Укажите текст сообщения Discord длиной до 1800 знаков.")
    result = _request(cfg, f"/channels/{channel}")
    if not result or result.get("guild_id") != guild:
        raise ValueError("Канал уведомлений не относится к настроенному серверу Discord.")
    result = _request(cfg, f"/channels/{channel}/messages", {"content": text, "allowed_mentions": {"parse": []}})
    if not result or result.get("channel_id") != channel or not result.get("id"):
        raise ValueError("Discord не подтвердил отправку сообщения.")
    return "Сообщение отправлено в настроенный канал Discord."


def voice_action(question):
    text = question.strip(" .!?")
    if re.fullmatch(r"(?:статус|состояние)(?: микрофона| звука)? в (?:discord|дискорде)", text, re.I):
        return "status", ""
    command = re.fullmatch(r"(выключи|включи|отключи|заглуши) (микрофон|звук) в (?:discord|дискорде)", text, re.I)
    if command:
        field = "mute" if command[2].lower() == "микрофон" else "deafen"
        return field, command[1].lower() != "включи"
    message = re.fullmatch(r"(?:отправь|напиши) в (?:discord|дискорд)(?:е)?[: ]+(.+)", text, re.I | re.S)
    return ("notify", message[1]) if message else None


def set_audio(config, action, desired):
    from shelter_core import pc
    cfg = config.get("discord") or {}
    if not cfg.get("guild_id") or not cfg.get("user_id"):
        pc.discord(action, config)
        return "Отправил горячую клавишу Discord. Текущее состояние неизвестно."
    state = voice_state(cfg)
    if state is None:
        return "Вы сейчас вне голосового канала Discord."
    key = "self_mute" if action == "mute" else "self_deaf"
    enforced = "mute" if action == "mute" else "deaf"
    if state[enforced]:
        return "Звук выключен сервером Discord."
    if state[key] != desired:
        pc.discord(action, config)
        from shelter_core import tasks
        import time
        for _ in range(3):
            tasks.check()
            time.sleep(.25)
            state = voice_state(cfg)
            if state is None or state[key] == desired:
                break
    if state is None or state[key] != desired:
        return "Отправил горячую клавишу, но Discord не подтвердил изменение."
    name = "Микрофон" if action == "mute" else "Звук"
    return f"{name} в Discord {'выключен' if desired else 'включён'}."
