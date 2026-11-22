"""Explicit, independent connections for speech and image generation."""
import base64
import io
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

import llm_connections
import tasks

ROOT = Path(__file__).resolve().parent
ALIBABA_WORKSPACE = re.compile(r"[a-z0-9-]+\.(?:ap-southeast-1|cn-beijing)\.maas\.aliyuncs\.com")
ALIBABA_IMAGE_WORKSPACE = re.compile(
    r"[a-z0-9-]+\.(?:ap-southeast-1|us-east-1|cn-beijing|cn-hongkong|eu-central-1|ap-northeast-1)\.maas\.aliyuncs\.com"
)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _read(url, data=None, key="", *, limit, timeout):
    headers = {"Content-Type": "application/json"} if data is not None else {}
    if key:
        headers["Authorization"] = "Bearer " + key
    request = urllib.request.Request(url, data=json.dumps(data).encode("utf-8") if data is not None else None,
                                     headers=headers)
    tasks.check()
    try:
        handlers = [NoRedirect()]
        if urllib.parse.urlsplit(url).hostname in ("127.0.0.1", "::1", "localhost"):
            handlers.append(urllib.request.ProxyHandler({}))
        with urllib.request.build_opener(*handlers).open(request, timeout=timeout) as response:
            parts = bytearray()
            while True:
                tasks.check()
                chunk = response.read1(min(65536, limit + 1 - len(parts)))
                if not chunk:
                    return bytes(parts)
                parts.extend(chunk)
                if len(parts) > limit:
                    raise ValueError("Ответ сервиса превысил допустимый размер.")
    except urllib.error.HTTPError as error:
        raise ValueError(f"Сервис вернул HTTP {error.code}. Проверьте адрес, ключ, модель и лимиты.") from None
    except OSError:
        raise ValueError("Сервис не ответил. Проверьте подключение и адрес.") from None


def connection(config, profile):
    llm = config.get("llm") or {}
    cfg = (llm.get("connections") or {}).get(profile.get("connection", "")) or {}
    if cfg.get("provider") != "openai":
        raise ValueError("Выберите сохранённое OpenAI-совместимое подключение.")
    endpoint = llm_connections.endpoint(cfg)
    origin = urllib.parse.urlsplit(endpoint)
    if origin.scheme != "https" and origin.hostname not in ("127.0.0.1", "::1", "localhost"):
        raise ValueError("Для облачного сервиса требуется HTTPS.")
    return endpoint.removesuffix("/chat/completions"), llm_connections.api_key(cfg)


def _model(profile, field):
    value = str(profile.get(field) or "").strip()
    if not value or len(value) > 160 or any(ord(char) < 32 for char in value):
        raise ValueError("Укажите ID модели и, для речи, ID голоса.")
    return value


def speech(text, config):
    profile = (config.get("tts") or {}).get("cloud") or {}
    url, key = connection(config, profile)
    model, voice = _model(profile, "model"), _model(profile, "voice")
    if profile.get("protocol") == "alibaba":
        base = urllib.parse.urlsplit(url)
        if not ALIBABA_WORKSPACE.fullmatch(base.hostname or "") or base.scheme != "https" or base.port not in (None, 443):
            raise ValueError("Для Alibaba TTS укажите адрес рабочей области Сингапура или Пекина в подключении.")
        address = f"{base.scheme}://{base.netloc}/api/v1/services/audio/tts/SpeechSynthesizer"
        payload = {"model": model, "input": {"text": text[:1800], "voice": voice, "format": "wav",
                                            "sample_rate": 24000, "language_hints": ["ru"]}}
        data = json.loads(_read(address, payload, key, limit=1_000_000, timeout=12))
        audio = urllib.parse.urlsplit(str(data.get("output", {}).get("audio", {}).get("url") or ""))
        if (audio.scheme != "https" or audio.username or audio.password or audio.port not in (None, 443)
                or not (audio.hostname or "").endswith(".aliyuncs.com")):
            raise ValueError("Alibaba не вернула аудио по допустимому адресу.")
        raw = _read(audio.geturl(), limit=8_000_000, timeout=12)
    else:
        raw = _read(url + "/audio/speech", {"model": model, "voice": voice, "input": text[:1800],
                                            "response_format": "wav"}, key, limit=8_000_000, timeout=12)
    from scipy.io import wavfile
    from voice import pcm16

    rate, pcm = wavfile.read(io.BytesIO(raw))
    if not 8000 <= rate <= 48000 or not len(pcm):
        raise ValueError("Сервис вернул неподдерживаемый WAV.")
    return rate, pcm16(pcm)


def image(prompt, config):
    if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 2000:
        raise ValueError("Опишите изображение текстом до 2000 знаков.")
    profile = config.get("image_generation") or {}
    url, key = connection(config, profile)
    payload = {"model": _model(profile, "model"), "prompt": prompt.strip(), "n": 1}
    host = urllib.parse.urlsplit(url).hostname or ""
    if ALIBABA_IMAGE_WORKSPACE.fullmatch(host):
        payload["response_format"] = "b64_json"
    data = json.loads(_read(url + "/images/generations", payload, key, limit=16_000_000, timeout=100))
    try:
        encoded = data["data"][0]["b64_json"]
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, KeyError, TypeError, IndexError):
        raise ValueError("Провайдер должен вернуть изображение в формате PNG/Base64.") from None
    if len(raw) > 10_000_000 or raw[:16] != b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR":
        raise ValueError("Провайдер вернул неподдерживаемый файл изображения.")
    if not all(1 <= int.from_bytes(raw[i:i + 4], "big") <= 4096 for i in (16, 20)):
        raise ValueError("Сервис вернул недопустимые размеры изображения.")
    tasks.check()
    folder = ROOT / "data" / "generated"
    folder.mkdir(parents=True, exist_ok=True)
    filename = folder / f"{uuid.uuid4().hex}.png"
    with filename.open("xb") as output:
        output.write(raw)
    return {"file": str(filename), "png": encoded}
