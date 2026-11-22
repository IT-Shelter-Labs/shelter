"""Сервер голоса Джарвиса: Qwen3-TTS с клонированием и потоковой отдачей.

Работает в своём окружении (.venv-tts) с CUDA-сборкой torch, чтобы основному
ассистенту не нужны были ни видеокарта, ни гигабайты зависимостей.

    POST /stream {"text": "..."} -> сырой PCM16 моно, частота в X-Sample-Rate.
                                    Звук идёт порциями по мере генерации.
    GET  /health                 -> {"ready": true, "sample_rate": 24000, ...}

Оба адреса требуют Authorization: Bearer <локальный ключ из secrets/tts.token>.
Клиент voice.py и voice_benchmark.py подставляют его автоматически.

Ускорение — faster-qwen3-tts: CUDA-графы вместо пошагового запуска ядер,
первый звук примерно через треть секунды.
"""

from shelter_core.paths import ROOT_DIR

import argparse
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from shelter_core.local_http import send_json, token_matches
from shelter_core import tts_auth

STATE = {"ready": False, "error": "", "sample_rate": 0}
LOCK = threading.Lock()          # видеокарта одна: фразы генерируются по очереди
MODEL = None
ARGS = None
AUTH_TOKEN = ""
PROFILES = None


def watch_parent(pid):
    """Выйти вместе с ассистентом: иначе модель останется висеть в видеопамяти."""
    if os.name == "nt":
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x00100000, False, pid)   # SYNCHRONIZE
        if handle:
            ctypes.windll.kernel32.WaitForSingleObject(handle, 0xFFFFFFFF)
        os._exit(0)
    while True:
        try:
            os.kill(pid, 0)
        except OSError:
            os._exit(0)
        time.sleep(2.0)


def resolve(model_id, *, allow_download=True):
    """Локальная копия модели, если она уже скачана: старт не зависит от сети."""
    from shelter_core import voice_assets
    if os.path.isdir(model_id):
        if voice_assets.missing(model_id):
            raise RuntimeError("В выбранной локальной модели отсутствуют файлы")
        return model_id
    existing = voice_assets.cached(model_id)
    if existing is not None:
        return str(existing)
    cache = voice_assets.hub_cache()
    from huggingface_hub import snapshot_download
    try:
        path = snapshot_download(model_id, local_files_only=True, cache_dir=cache)
    except Exception as error:
        path = getattr(error, "snapshot_path", "") or ""
    if path and not voice_assets.missing(path):
        return path
    if not allow_download or model_id not in voice_assets.OFFICIAL:
        raise RuntimeError("Модель отсутствует в локальном кэше")
    STATE["phase"] = "downloading"
    print("Восстанавливаю файлы модели голоса…", flush=True)
    files = voice_assets.missing(path) if path else voice_assets.REQUIRED
    from huggingface_hub import hf_hub_download
    for file in files:
        hf_hub_download(model_id, file, force_download=bool(path and os.path.exists(os.path.join(path, file))),
                        token=False, endpoint="https://huggingface.co", cache_dir=cache)
    path = snapshot_download(model_id, local_files_only=True, cache_dir=cache, allow_patterns=list(voice_assets.REQUIRED))
    if voice_assets.missing(path):
        raise RuntimeError("Не все файлы модели удалось восстановить")
    STATE["phase"] = "loading"
    return path


def clone_args(text, sampling=None):
    """sampling — переопределение выборки из запроса (для сравнения настроек)."""
    sampling = sampling or {}
    defaults = PROFILES.sampling if PROFILES is not None and sampling.get("model_profile")=="jarvis" else {}
    reference = sampling.get("reference") or ARGS.reference
    reference_text = sampling.get("reference_text", ARGS.reference_text if reference == ARGS.reference else "")
    return dict(text=text, language=ARGS.language, ref_audio=reference,
                ref_text=reference_text, xvec_only=not reference_text,
                temperature=sampling.get("temperature", defaults.get("temperature", ARGS.temperature)),
                top_p=sampling.get("top_p", defaults.get("top_p", ARGS.top_p)))


ROOT = ROOT_DIR


def reference_from(data):
    """Образец голоса персонажа из запроса — только файл внутри проекта."""
    path = str(data.get("reference") or "")
    if not path:
        return {}
    full = os.path.realpath(os.path.join(ROOT, path))
    if not full.startswith(os.path.realpath(ROOT) + os.sep) or not os.path.isfile(full):
        raise ValueError("образец голоса не найден")
    return {"reference": full, "reference_text": str(data.get("reference_text") or "")[:600]}


def sampling_from(data):
    out = reference_from(data)
    profile = data.get("model_profile", "default")
    if profile not in ("default", "jarvis"):
        raise ValueError("неизвестный профиль голоса")
    out["model_profile"] = profile
    for key, low, high in (("temperature", 0.1, 1.5), ("top_p", 0.1, 1.0)):
        if key in data:
            out[key] = min(max(float(data[key]), low), high)
    return out


def stream(text, sampling=None):
    """Порции звука float32 по мере генерации."""
    if PROFILES is not None:
        PROFILES.select((sampling or {}).get("model_profile", "default"))
        STATE["active_voice_profile"] = PROFILES.active
    if ARGS.speaker:
        waves, sample_rate = MODEL.generate_custom_voice(text=text, language=ARGS.language, speaker=ARGS.speaker)
        STATE["sample_rate"] = sample_rate
        yield waves[0]
        return
    for chunk, sample_rate, _timing in MODEL.generate_voice_clone_streaming(
            chunk_size=PROFILES.sampling.get("chunk", ARGS.chunk) if PROFILES is not None and PROFILES.active=="jarvis" else ARGS.chunk,
            **clone_args(text, sampling)):
        STATE["sample_rate"] = sample_rate
        yield chunk


def pcm16(chunk):
    import numpy as np
    return (np.clip(chunk, -1.0, 1.0) * 32767).astype("<i2")


def load():
    from shelter_core.background_process import hide_child_consoles
    from shelter_core.voice_assets import present
    hide_child_consoles()
    global MODEL, PROFILES
    try:
        STATE["phase"] = "loading"
        import torch

        if not torch.cuda.is_available():
            raise RuntimeError("нет CUDA: клонированному голосу нужна видеокарта NVIDIA")
        started = time.perf_counter()
        if ARGS.speaker:
            from qwen_tts import Qwen3TTSModel
            MODEL = Qwen3TTSModel.from_pretrained(resolve(ARGS.model, allow_download=not ARGS.no_download), device_map="cuda:0", dtype=torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16)
        else:
            from faster_qwen3_tts import FasterQwen3TTS
            base = resolve(ARGS.model, allow_download=not ARGS.no_download)
            MODEL = FasterQwen3TTS.from_pretrained(base)
            if ARGS.jarvis_adapter:
                from shelter_core.tts_profiles import ModelProfiles
                if all(present(os.path.join(ARGS.jarvis_adapter, name)) for name in ("manifest.json", "adapter.safetensors")):
                    PROFILES = ModelProfiles(MODEL.model.model, base, ARGS.jarvis_adapter)
                    STATE["jarvis_revision"] = PROFILES.revision
                else:
                    STATE["warning"] = "missing_adapter"
        # Первая генерация захватывает CUDA-графы и разбирает образец голоса.
        # Без прогрева эти секунды достались бы первой реплике.
        for _ in stream("Системы готовы, сэр."):
            pass
        if PROFILES is not None:
            for _ in stream("Системы готовы, сэр.", {"model_profile": "jarvis"}):
                pass
        STATE["ready"] = True
        STATE["phase"] = "ready"
        print(f"готово за {time.perf_counter() - started:.1f} с, "
              f"VRAM {torch.cuda.max_memory_allocated() / 2**30:.2f} ГБ", flush=True)
    except Exception as error:
        STATE["error"] = f"{type(error).__name__}: {error}"
        STATE["phase"] = "error"
        print("ошибка загрузки:", STATE["error"], flush=True)


class Handler(BaseHTTPRequestHandler):
    # HTTP/1.0: без Content-Length тело заканчивается закрытием соединения —
    # так звук можно отдавать порциями, не зная заранее его длины.
    protocol_version = "HTTP/1.0"

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, _format, *_args):
        return

    def _json(self, status, data):
        # Windows can reset the TCP connection if an early error closes it
        # while a small POST body is still arriving. Drain only a bounded body;
        # never invoke synthesis or wait indefinitely for an unauthorised peer.
        if self.command == "POST" and status >= 400 and not getattr(self, "_body_read", False):
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if 0 < length <= 65537:
                    previous = self.connection.gettimeout()
                    try:
                        self.connection.settimeout(.25)
                        self.rfile.read(length)
                    finally:
                        self.connection.settimeout(previous)
            except (OSError, ValueError):
                pass
            self._body_read = True
        try:
            send_json(self, status, data)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def _authorized(self):
        supplied = self.headers.get("Authorization", "").removeprefix("Bearer ")
        if token_matches(supplied, AUTH_TOKEN):
            return True
        self._json(403, {"error": "нужен ключ голосового сервера"})
        return False

    def do_GET(self):
        if self._authorized():
            self._json(200, STATE)

    def _read_text(self):
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= 65536:
            raise ValueError("неверный размер запроса")
        body = self.rfile.read(length)
        self._body_read = True
        data = json.loads(body)
        if not isinstance(data, dict):
            raise ValueError("нужен JSON-объект")
        text = str(data.get("text", "")).strip()
        if not text or len(text) > 600:
            raise ValueError("пустой или слишком длинный текст")
        self._sampling = sampling_from(data)
        return text

    def do_POST(self):
        if not self._authorized():
            return
        if self.path != "/stream":
            self._json(404, {"error": "not found"})
            return
        if not STATE["ready"]:
            self._json(503, {"error": "not ready"})
            return
        try:
            text = self._read_text()
        except (ValueError, TypeError) as error:
            self._json(400, {"error": str(error)})
            return

        self._stream_response(text)

    def _stream_response(self, text):
        started = time.perf_counter()
        first = None
        produced = 0
        with LOCK:
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("X-Sample-Rate", str(STATE["sample_rate"]))
            self.end_headers()
            try:
                for chunk in stream(text, getattr(self, "_sampling", None)):
                    pcm = pcm16(chunk)
                    self.wfile.write(pcm.tobytes())
                    self.wfile.flush()
                    produced += len(pcm)
                    if first is None:
                        first = time.perf_counter() - started
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                return          # ассистента перебили — дальше генерировать незачем
        total = time.perf_counter() - started
        audio = produced / max(STATE["sample_rate"], 1)
        print(f"первый звук {first or 0:4.2f} с | {total:4.2f} с на {audio:4.1f} с звука | {text}",
              flush=True)


def main():
    global ARGS, AUTH_TOKEN
    parser = argparse.ArgumentParser(description="Сервер голоса Джарвиса")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--model", default="Qwen/Qwen3-TTS-12Hz-0.6B-Base")
    parser.add_argument("--no-download", action="store_true")
    parser.add_argument("--reference", default="")
    parser.add_argument("--reference-text", default="")
    parser.add_argument("--jarvis-adapter", default="", help="локальный профиль дообученного голоса Джарвиса")
    parser.add_argument("--speaker", default="", help="имя диктора своей дообученной CustomVoice-модели; пусто для Base")
    parser.add_argument("--language", default="Russian")
    # 0.9 (по умолчанию в Qwen) — живее, но голос и ударения «гуляют» от фразы к фразе.
    parser.add_argument("--temperature", type=float, default=0.9)
    parser.add_argument("--top-p", type=float, default=1.0)
    parser.add_argument("--chunk", type=int, default=6,
                        help="кадров на порцию: меньше — раньше первый звук, но меньше запас")
    parser.add_argument("--parent", type=int, default=0)
    ARGS = parser.parse_args()
    AUTH_TOKEN = tts_auth.token()

    if ARGS.parent:
        threading.Thread(target=watch_parent, args=(ARGS.parent,), daemon=True).start()
    threading.Thread(target=load, daemon=True).start()
    # Только локальный адрес: синтез не должен быть доступен из сети.
    server = ThreadingHTTPServer(("127.0.0.1", ARGS.port), Handler)
    server.daemon_threads = True
    server.serve_forever()


if __name__ == "__main__":
    main()
