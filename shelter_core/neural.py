"""Запуск сервера клонирования голоса (tts_server.py).

Тяжёлая модель живёт в отдельном процессе со своим окружением: основному
ассистенту не нужны ни CUDA-сборка torch, ни гигабайты зависимостей, а без
видеокарты он просто работает на записях и запасном голосе.
"""

from shelter_core.paths import ROOT_DIR

import os
import shutil
import subprocess
import sys
import threading
import time
from shelter_core import tts_auth
from shelter_core.process_runtime import service_options

ROOT = ROOT_DIR
_process = None
_installer = None
_stop = threading.Event()
_state = {"phase": "idle", "reason": ""}


def _set(phase, reason=""):
    global _state
    _state = {"phase": phase, "reason": reason}


def status():
    return dict(_state)


def _python(config):
    from shelter_core.setup_tool import clone_python
    given = ((config.get("tts") or {}).get("clone") or {}).get("python")
    if given:
        path = os.path.join(ROOT, given)
        return path if os.path.isfile(path) else None
    return clone_python()


def _nvidia():
    candidates = [shutil.which("nvidia-smi"), os.path.join(os.environ.get("WINDIR", ""), "System32", "nvidia-smi.exe")]
    for path in candidates:
        try:
            if path and os.path.isfile(path) and subprocess.run(
                [path, "-L"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=8, **service_options()).returncode == 0:
                return True
        except (OSError, subprocess.TimeoutExpired):
            continue
    return False


def _healthy(python):
    try:
        return subprocess.run([python, "-c", "import torch, torchaudio, faster_qwen3_tts, soundfile, huggingface_hub"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30,
                              **service_options()).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def boot(config, voice, on_ready):
    """Repair only a selected, built-in voice; never replace custom assets."""
    global _installer
    from shelter_core import voice_assets
    cfg = (config.get("tts") or {}).get("clone") or {}
    _set("checking")
    _stop.clear()
    try:
        reference = cfg.get("reference") or ""
        if not cfg.get("speaker") and not voice_assets.present(os.path.join(ROOT, reference)):
            _set("error", "reference")
            return
        python = _python(config)
        if not python or not _healthy(python):
            if (cfg.get("python") or cfg.get("model", voice_assets.BASE) not in voice_assets.OFFICIAL
                    or os.name != "nt" or cfg.get("auto_repair", True) is False or config.get("repair_components", True) is False):
                _set("error", "runtime")
                return
            if not _nvidia():
                _set("error", "gpu")
                return
            if _stop.is_set():
                return
            _set("repairing")
            os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
            with open(os.path.join(ROOT, "logs", "voice_repair.log"), "ab") as log:
                _installer = subprocess.Popen([sys.executable, "-u", os.path.join(ROOT, "setup_tool.py"),
                                               "install", "clone-runtime"], cwd=ROOT, stdout=log,
                                              stderr=subprocess.STDOUT, **service_options())
            expiry = time.monotonic() + 2700
            while _installer.poll() is None and not _stop.wait(0.5):
                if time.monotonic() >= expiry:
                    _installer.terminate()
                    _set("error", "repair")
                    return
            if _stop.is_set():
                return
            if _installer.returncode or not _python(config) or not _healthy(_python(config)):
                _set("error", "repair")
                return
        if _stop.is_set():
            return
        adapter = cfg.get("jarvis_adapter") or ""
        if (adapter and os.path.normcase(os.path.abspath(os.path.join(ROOT, adapter)))
                == os.path.normcase(os.path.abspath(os.path.join(ROOT, voice_assets.JARVIS_ADAPTER)))
                and not voice_assets.present(os.path.join(ROOT, adapter, "adapter.safetensors"))
                and cfg.get("auto_repair", True) is not False and config.get("repair_components", True) is not False):
            _set("downloading")
            try:
                from shelter_core import setup_tool
                setup_tool.install("jarvis-voice")
            except (OSError, ValueError, RuntimeError) as error:
                print(f">> JARVIS VOICE DOWNLOAD // {error}", flush=True)
        if _stop.is_set():
            return
        _set("loading")
        voice.CLONE_URL = start(config)
        if not voice.CLONE_URL:
            _set("error", "runtime")
            return
        deadline = time.monotonic() + 300
        last_phase = "loading"
        ready_once = False
        missed_health = 0
        while not _stop.is_set():
            if not loading():
                _set("error", "server")
                return
            health = voice.clone_health(0.7)
            missed_health = 0 if health else missed_health + 1
            phase = health.get("phase")
            if health.get("ready"):
                _set("ready", "adapter" if health.get("warning") == "missing_adapter" else "")
                if not ready_once:
                    ready_once = True
                    on_ready()
            elif health.get("error"):
                _set("error", "model")
                return
            elif ready_once and missed_health >= 3:
                _set("error", "server")
            elif phase in ("downloading", "loading") and phase != last_phase:
                last_phase = phase
                deadline = time.monotonic() + (2700 if phase == "downloading" else 300)
                _set(phase)
            elif not ready_once and time.monotonic() >= deadline:
                _set("error", "timeout")
                return
            _stop.wait(1.0 if not ready_once else 2.0)
    except Exception as error:
        print(f">> VOICE RECOVERY ERROR // {error}", flush=True)
        _set("error", "repair" if _state["phase"] == "repairing" else "server")


def start(config):
    """Поднять сервер в фоне и вернуть его адрес; пустая строка, если нечем."""
    global _process
    cfg = (config.get("tts") or {}).get("clone") or {}
    python = _python(config)
    reference = cfg.get("reference", "")
    if not cfg.get("speaker") and (not reference or not os.path.exists(os.path.join(ROOT, reference) if not os.path.isabs(reference) else reference)):
        print(">> VOICE CLONE OFF  //  нет образца голоса — выберите его в приложении: «Слух и голос»")
        return ""
    if not python:
        print(">> VOICE CLONE OFF  //  нет окружения .venv-tts — см. README, раздел про голос")
        return ""
    port = int(cfg.get("port", 8766))
    # Windows embeddable Python ignores the script directory as an import path.
    # Add the application directory explicitly, including for previously installed runtimes.
    bootstrap = ("import runpy, sys; sys.path.insert(0, sys.argv.pop(1)); "
                 "runpy.run_module('shelter_core.tts_server', run_name='__main__')")
    command = [python, "-u", "-c", bootstrap, ROOT,
               "--port", str(port), "--parent", str(os.getpid()),
               "--model", cfg.get("model", "Qwen/Qwen3-TTS-12Hz-0.6B-Base"),
               "--reference", reference,
               "--reference-text", cfg.get("reference_text", ""),
               "--speaker", cfg.get("speaker", ""),
               "--language", cfg.get("language", "Russian"),
               "--chunk", str(int(cfg.get("chunk", 6))),
               "--temperature", str(float(cfg.get("temperature", 0.7))),
               "--top-p", str(float(cfg.get("top_p", 1.0)))]
    if cfg.get("jarvis_adapter"):
        command += ["--jarvis-adapter", os.path.join(ROOT, cfg["jarvis_adapter"])]
    if config.get("repair_components", True) is False or cfg.get("auto_repair", True) is False:
        command.append("--no-download")
    try:
        auth_token = tts_auth.token()
    except (OSError, RuntimeError) as error:
        print(f">> VOICE CLONE OFF  //  {error}")
        return ""
    os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
    log = open(os.path.join(ROOT, "logs", "tts_server.log"), "w", encoding="utf-8")
    # UTF-8 явно: иначе Windows пишет лог в cp1251, и кириллица там нечитаема.
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1", **{tts_auth.TOKEN_ENV: auth_token})
    try:
        _process = subprocess.Popen(
            command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, env=env,
            **service_options())
    finally:
        log.close()  # the child owns duplicated handles
    return f"http://127.0.0.1:{port}"


def loading():
    """Сервер запущен и ещё грузит модель (а не упал)."""
    return _process is not None and _process.poll() is None


def wait_ready(probe, timeout=240.0):
    """Дождаться загрузки модели. False — сервер умер или не успел."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _process is None or _process.poll() is not None:
            print(">> VOICE CLONE OFF  //  сервер не запустился, подробности в logs/tts_server.log")
            return False
        if probe(1.0):
            return True
        time.sleep(1.0)
    return False


def stop():
    global _process
    _stop.set()
    if _installer is not None and _installer.poll() is None:
        _installer.terminate()
    if _process is not None and _process.poll() is None:
        _process.terminate()
        try:
            _process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            _process.kill()
            _process.wait(timeout=2)
    _process = None
