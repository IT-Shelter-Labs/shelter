"""Loopback transport for the Shelter Factorio mod's typed commands."""

import json
import os
import re
import socket
import struct


IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,160}")
PLAYER = re.compile(r"[A-Za-z0-9_.-]{1,60}")
PREFIX = "SHELTER/1 "


def _read(sock, size):
    data = bytearray()
    while len(data) < size:
        part = sock.recv(size - len(data))
        if not part:
            raise ValueError("Factorio закрыл соединение RCON.")
        data.extend(part)
    return data


def _send(sock, request, kind, value):
    body = value.encode("utf-8") + b"\0\0"
    sock.sendall(struct.pack("<iii", len(body) + 8, request, kind) + body)


def _receive(sock):
    size, = struct.unpack("<i", _read(sock, 4))
    if not 10 <= size <= 65_536:
        raise ValueError("Неверный размер ответа Factorio RCON.")
    body = _read(sock, size)
    request, kind = struct.unpack_from("<ii", body)
    return request, kind, bytes(body[8:-2]).decode("utf-8", "replace")


def configured(config):
    return bool((config.get("factorio") or {}).get("player"))


def request(config, operation, *, recipe="", count=None, x=None, y=None):
    cfg = config.get("factorio") or {}
    player = cfg.get("player", "")
    port = cfg.get("rcon_port", 27015)
    password = os.environ.get("SHELTER_FACTORIO_PASSWORD") or cfg.get("rcon_password", "")
    if not isinstance(player, str) or not PLAYER.fullmatch(player):
        raise ValueError("Укажите имя игрока в настройках Factorio.")
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("Неверный порт Factorio RCON.")
    if not isinstance(password, str) or not password or len(password) > 512 or "\0" in password:
        raise ValueError("Укажите пароль RCON для своего сервера Factorio.")
    command = f"/shelter-bridge {player} {operation}"
    if operation in ("plan", "craft"):
        if not isinstance(recipe, str) or not IDENTIFIER.fullmatch(recipe):
            raise ValueError("Укажите ID рецепта Factorio.")
        if type(count) is not int or not 1 <= count <= 100:
            raise ValueError("Укажите число выполнений рецепта от 1 до 100.")
        command += f" {recipe} {count}"
    elif operation == "research":
        if not isinstance(recipe, str) or not IDENTIFIER.fullmatch(recipe):
            raise ValueError("Укажите ID технологии Factorio.")
        command += f" {recipe}"
    elif operation in ("build", "machine"):
        if any(type(value) is not int or abs(value) > 1_000_000 for value in (x, y)):
            raise ValueError("Укажите две целые координаты Factorio.")
        if operation == "machine":
            if not isinstance(recipe, str) or not IDENTIFIER.fullmatch(recipe):
                raise ValueError("Укажите ID рецепта Factorio.")
            command += f" {recipe}"
        command += f" {x} {y}"
    elif operation not in ("status", "stop"):
        raise ValueError("Неизвестная операция Factorio.")
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2) as sock:
            _send(sock, 1, 3, password)
            for _ in range(3):
                request_id, kind, _ = _receive(sock)
                if request_id == -1:
                    raise ValueError("Factorio отклонил пароль RCON.")
                if request_id == 1 and kind == 2:
                    break
            else:
                raise ValueError("Factorio не подтвердил подключение RCON.")
            _send(sock, 2, 2, command)
            request_id, kind, payload = _receive(sock)
    except OSError as error:
        raise ValueError("Factorio RCON не отвечает на этом компьютере.") from error
    if request_id != 2 or kind != 0 or not payload.startswith(PREFIX):
        raise ValueError("Сервер не ответил через мост Shelter. Проверьте версию мода.")
    result = json.loads(payload[len(PREFIX):])
    if not isinstance(result, dict):
        raise ValueError("Мод Factorio вернул неверные данные.")
    if not result.get("ok"):
        messages = {
            "player": "Игрок отсутствует на сервере.",
            "disabled": "Включите управление командой /shelter-remote в игре.",
            "busy": "Сначала завершите или остановите текущую задачу производства.",
            "recipe": "Рецепт недоступен для этой команды.",
            "research": "Игра не приняла технологию в очередь исследования.",
            "admin": "Для управления исследованиями нужны права администратора мира.",
            "blueprint": "Возьмите в курсор настроенный чертёж Factorio.",
            "blueprint_size": "Выберите чертёж до 120 объектов без плиток, размером до 48 на 48 клеток.",
            "position": "Укажите точку не дальше 24 клеток от персонажа.",
            "machine": "В пределах досягаемости должен быть один ваш сборочный автомат у указанных координат.",
            "assigned": "У автомата уже задан другой рецепт. Очистите его в игре, чтобы сохранить материалы.",
            "machine_recipe": "Factorio не подтвердила рецепт для этого автомата.",
        }
        raise ValueError(messages.get(result.get("error"), "Мод Factorio отклонил команду."))
    return result
