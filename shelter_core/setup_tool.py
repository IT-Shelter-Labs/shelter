"""Проверка и установка компонентов Джарвиса — для мастера в приложении.

    python setup_tool.py check
    python setup_tool.py install packages vosk gigaam vad piper:ruslan ollama model:gemma4:e4b

Пишет по строке JSON на событие (stdout), приложение показывает прогресс:
    {"component": "gigaam", "stage": "download", "done": 1234, "total": 5678}
    {"component": "gigaam", "status": "ok"}
    {"component": "ollama", "status": "error", "message": "..."}

Интернет — через системный прокси (как у браузера): в России многим нужен VPN.
Локальные адреса (Ollama) — напрямую, см. netfix.py.
"""

from shelter_core.paths import ROOT_DIR

import importlib
import importlib.util
from contextlib import contextmanager
import hashlib
import json
import os
import shutil
import subprocess
from shelter_core.process_runtime import service_options
import sys
import tarfile
import time
import urllib.request
import zipfile
from pathlib import Path

from shelter_core import netfix  # noqa: F401
from shelter_core import voice_assets

ROOT = ROOT_DIR
MODELS = os.path.join(ROOT, "models")
DOWNLOADS = os.path.join(MODELS, "_download")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
SHERPA = "https://github.com/k2-fsa/sherpa-onnx/releases/download"

# Модель аниме-персонажа: пример pixiv из three-vrm (лицензия VRM 1.0 — распространение
# разрешено), закреплена на коммит и проверяется по sha256.
AVATAR_URL = ("https://raw.githubusercontent.com/pixiv/three-vrm/5a3242b66124386c32b085c6693d9059040e72e5/"
              "packages/three-vrm/examples/models/VRM1_Constraint_Twist_Sample.vrm")
AVATAR_SHA256 = "12c2b97e95e700783a6a550dc0eee2d7880aeedccef9ae67bc4c5a2f0f2631a2"
AVATAR_PATH = os.path.join("avatars", "anime.vrm")

ARCHIVES = {
    "vosk": ("https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip", "vosk-ru"),
    "gigaam": (f"{SHERPA}/asr-models/sherpa-onnx-nemo-transducer-giga-am-v3-russian-2025-12-16.tar.bz2",
               "gigaam-v3"),
    # Слово-обращение: маленький потоковый zipformer (alphacep) как keyword spotter.
    "kws": (f"{SHERPA}/asr-models/sherpa-onnx-streaming-zipformer-small-ru-vosk-int8-2025-08-16.tar.bz2",
            "kws-ru"),
}
PIPER_VOICES = ("ruslan", "dmitri", "denis", "irina")
OLLAMA_ARCHIVE = ("https://github.com/ollama/ollama/releases/download/v0.40.17/"
                  "ollama-windows-amd64.zip")
OLLAMA_SHA256 = "3dd80f6e3a9699f2eadf4ac418f00529cee594df9557541806eda1f1f3f5588a"
OLLAMA_LOCAL = os.path.join(ROOT, "runtime", "ollama", "ollama.exe")
OLLAMA_URL = "http://127.0.0.1:11434"


def emit(**event):
    print(json.dumps(event, ensure_ascii=False), flush=True)


@contextmanager
def install_lock(component):
    """Same lock for background startup repair and manual setup, released on exit."""
    directory = Path(DOWNLOADS)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (component + ".lock")
    with path.open("a+b") as lock:
        if lock.tell() == 0:
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        if os.name == "nt":
            import msvcrt
            acquire = lambda: msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            release = lambda: msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            acquire = lambda: fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            release = lambda: fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        deadline = time.monotonic() + 2700
        while True:
            try:
                acquire()
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("Установка компонента уже идёт")
                time.sleep(0.5)
        try:
            yield
        finally:
            lock.seek(0)
            release()


# ------------------------------------------------------------- проверка

def ollama_executable():
    if os.name == "nt" and os.path.isfile(OLLAMA_LOCAL):
        return OLLAMA_LOCAL
    found = shutil.which("ollama")
    if found:
        return found
    path = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Ollama", "ollama.exe")
    return path if os.path.exists(path) else None


def ollama_environment(exe, host="127.0.0.1:11434"):
    env = {**os.environ, "OLLAMA_HOST": host}
    if os.name == "nt" and os.path.normcase(exe) == os.path.normcase(OLLAMA_LOCAL):
        env["OLLAMA_MODELS"] = os.path.join(MODELS, "ollama")
    return env


def _ollama_alive():
    try:
        with urllib.request.urlopen(OLLAMA_URL + "/api/version", timeout=2) as response:
            return json.loads(response.read()).get("version")
    except (OSError, ValueError):
        return None


def ollama_models():
    try:
        with urllib.request.urlopen(OLLAMA_URL + "/api/tags", timeout=3) as response:
            return [m["name"] for m in json.loads(response.read()).get("models", [])]
    except (OSError, ValueError):
        return []


def check():
    packages = []
    required = ["vosk", "sherpa_onnx", "sounddevice", "soundfile", "scipy", "yaml", "ruamel.yaml", "psutil",
                "websocket", "sentencepiece", "pymorphy3"]
    if os.name == "nt":
        # Новые пакеты попадают сюда — после обновления мастер предложит доустановить.
        required += ["pycaw", "winrt.windows.media.control", "winrt.windows.media.ocr",
                     "winrt.windows.graphics.imaging", "winrt.windows.storage.streams"]
    for module in required:
        try:
            importlib.import_module(module)
        except Exception:
            packages.append(module)
    piper = [v for v in PIPER_VOICES if model_complete(os.path.join(MODELS, "piper", v), "piper")]
    clone_ready = bool(clone_python() and voice_assets.cached(CLONE_MODEL))
    return {
        "packages": {"ok": not packages, "missing": packages},
        "vosk": {"ok": model_complete(os.path.join(MODELS, "vosk-ru"), "vosk")},
        "gigaam": {"ok": model_complete(os.path.join(MODELS, "gigaam-v3"), "gigaam")},
        "vad": {"ok": os.path.exists(os.path.join(MODELS, "silero_vad.onnx"))},
        "kws": {"ok": model_complete(os.path.join(MODELS, "kws-ru"), "kws")},
        "avatar": {"ok": os.path.isfile(os.path.join(MODELS, AVATAR_PATH))},
        "aec": {"ok": all(importlib.util.find_spec(m) is not None for m in ("soundcard", "livekit.rtc"))},
        "speaker": {"ok": os.path.exists(os.path.join(MODELS, "speaker",
                                                      "3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx"))},
        "piper": {"ok": bool(piper), "voices": piper},
        "ollama": {"ok": bool(ollama_executable() or _ollama_alive()), "running": bool(_ollama_alive()),
                   "models": ollama_models()},
        "clone": {"ok": clone_ready},
        "silero": {"ok": importlib.util.find_spec("torch") is not None and os.path.isfile(os.path.join(MODELS, "silero", "v5_6_ru.pt"))},
    }


def model_complete(folder, kind):
    folder = Path(folder)
    valid = lambda p: p.is_file() and p.stat().st_size > 0
    if kind == "vosk":
        return all(valid(folder / name) for name in ("am/final.mdl", "conf/model.conf", "graph/HCLr.fst", "graph/Gr.fst"))
    if kind == "gigaam":
        return valid(folder / "tokens.txt") and all(any(valid(folder / (name + suffix)) for suffix in
                   (".onnx", ".int8.onnx")) for name in ("encoder", "decoder", "joiner"))
    if kind == "kws":
        return all(valid(folder / name) for name in
                   ("tokens.txt", "bpe.model", "encoder.int8.onnx", "decoder.onnx", "joiner.int8.onnx"))
    if kind == "piper":
        return valid(folder / "tokens.txt") and any(valid(p) for p in folder.glob("*.onnx")) and (folder / "espeak-ng-data").is_dir()
    return False


# -------------------------------------------------------------- загрузка

def download(component, url, path, attempts=4):
    """Скачать с прогрессом; при обрыве связи — ещё несколько попыток."""
    for attempt in range(1, attempts + 1):
        try:
            return _download_once(component, url, path)
        except OSError as error:
            if attempt == attempts:
                raise RuntimeError(f"не удалось скачать {url.rsplit('/', 1)[-1]}: {error}") from error
            emit(component=component, stage="retry", text=f"обрыв связи, попытка {attempt + 1} из {attempts}")
            time.sleep(2 * attempt)


def _download_once(component, url, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "Jarvis-Setup/2.0"})
    with urllib.request.urlopen(request, timeout=60) as response, open(path + ".part", "wb") as out:
        total = int(response.headers.get("Content-Length") or 0)
        done, last = 0, 0.0
        while True:
            chunk = response.read(1 << 18)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if time.monotonic() - last > 0.25:
                emit(component=component, stage="download", done=done, total=total)
                last = time.monotonic()
    if total and done != total:
        raise OSError("Файл скачан не полностью")
    os.replace(path + ".part", path)
    emit(component=component, stage="download", done=done, total=total or done)


def _safe_extract(archive, target):
    """Распаковать, не выпуская файлы за пределы папки и без ссылок."""
    target = os.path.abspath(target)
    if archive.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            for name in z.namelist():
                path = os.path.abspath(os.path.join(target, name))
                if not path.startswith(target + os.sep):
                    raise RuntimeError(f"подозрительный путь в архиве: {name}")
            z.extractall(target)
        return
    with tarfile.open(archive, "r:*") as t:
        members = t.getmembers()
        for m in members:
            path = os.path.abspath(os.path.join(target, m.name))
            if not path.startswith(target + os.sep) or not (m.isfile() or m.isdir()):
                raise RuntimeError(f"подозрительный элемент архива: {m.name}")
        t.extractall(target, members=members)


def install_archive(component, url, folder):
    final = os.path.join(MODELS, folder)
    if model_complete(final, component.split(":")[0]):
        return
    name = url.rsplit("/", 1)[-1]
    archive = os.path.join(DOWNLOADS, name)
    if not os.path.exists(archive):
        download(component, url, archive)
    emit(component=component, stage="extract")
    staging = os.path.join(DOWNLOADS, component.replace(":", "-") + "-unpack")
    shutil.rmtree(staging, ignore_errors=True)
    _safe_extract(archive, staging)
    inner = [os.path.join(staging, d) for d in os.listdir(staging)]
    source = inner[0] if len(inner) == 1 and os.path.isdir(inner[0]) else staging
    os.makedirs(os.path.dirname(final), exist_ok=True)
    if not model_complete(source, component.split(":")[0]):
        raise RuntimeError("Архив не содержит всех файлов модели")
    if os.path.exists(final):
        backup = final + ".incomplete"
        if os.path.exists(backup):
            raise RuntimeError(f"Уже есть резервная копия незавершённой модели: {backup}")
        os.replace(final, backup)
    shutil.move(source, final)
    shutil.rmtree(staging, ignore_errors=True)
    os.remove(archive)                    # архив больше не нужен


def install_avatar():
    import hashlib
    path = os.path.join(MODELS, AVATAR_PATH)
    if os.path.isfile(path):
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = path + ".part"
    download("avatar", AVATAR_URL, temporary)
    with open(temporary, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    if digest != AVATAR_SHA256:
        os.remove(temporary)
        raise RuntimeError("модель персонажа повреждена при загрузке")
    os.replace(temporary, path)


def install_packages():
    emit(component="packages", stage="pip")
    lock = os.path.join(ROOT, "requirements-lock.windows.txt")
    requirements = lock if os.name == "nt" and os.path.isfile(lock) else os.path.join(ROOT, "requirements.txt")
    process = subprocess.Popen(
        [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-warn-script-location", "--no-cache-dir",
         "-r", requirements],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
    tail = []
    for raw in process.stdout:
        line = raw.decode("utf-8", "replace").strip()
        if line:
            tail = (tail + [line])[-8:]
            if line.startswith(("Collecting", "Downloading", "Installing", "Successfully")):
                emit(component="packages", stage="pip", text=line[:120])
    if process.wait():
        raise RuntimeError("pip не смог установить пакеты:\n" + "\n".join(tail))


def install_ollama():
    if ollama_executable() or _ollama_alive():
        return
    if os.name != "nt":
        raise RuntimeError("Установите Ollama для Linux с ollama.com, затем повторите проверку")
    with install_lock("ollama"):
        if ollama_executable() or _ollama_alive():
            return
        archive = os.path.join(DOWNLOADS, "ollama-windows-amd64.zip")
        if not os.path.isfile(archive):
            download("ollama", OLLAMA_ARCHIVE, archive)
        with open(archive, "rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        if digest != OLLAMA_SHA256:
            os.remove(archive)
            raise RuntimeError("Архив Ollama не прошёл проверку целостности. Повторите загрузку.")
        emit(component="ollama", stage="extract")
        staging = os.path.join(DOWNLOADS, "ollama-unpack")
        shutil.rmtree(staging, ignore_errors=True)
        _safe_extract(archive, staging)
        if not os.path.isfile(os.path.join(staging, "ollama.exe")):
            raise RuntimeError("В архиве отсутствует исполняемый файл Ollama.")
        destination = os.path.dirname(OLLAMA_LOCAL)
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        shutil.rmtree(destination, ignore_errors=True)
        os.replace(staging, destination)
        os.remove(archive)


def pull_model(name):
    component = "model:" + name
    if not _ollama_alive():
        exe = ollama_executable()
        if not exe:
            raise RuntimeError("сначала нужна Ollama")
        subprocess.Popen([exe, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         env=ollama_environment(exe), **service_options(breakaway=True))
        for _ in range(30):
            if _ollama_alive():
                break
            time.sleep(1)
        else:
            raise RuntimeError("Ollama не запустилась. Проверьте раздел «Система и диагностика».")
    tag = name if ":" in name.rsplit("/", 1)[-1] else name + ":latest"
    if tag in ollama_models():
        return
    for attempt in range(3):
        try:
            _pull_model_once(name, component)
            return
        except (OSError, RuntimeError) as error:
            detail = str(error).lower()
            transient = isinstance(error, TimeoutError) or any(
                marker in detail for marker in ("timeout", "timed out", "connection reset", "unexpected eof",
                                                "поток загрузки оборвался", "temporarily unavailable",
                                                "502", "503", "504"))
            if not transient:
                raise
            if attempt == 2:
                raise RuntimeError("Ollama не смогла завершить загрузку. Проверьте доступ к "
                                   "registry.ollama.ai, перезапустите Ollama после изменения VPN "
                                   "или прокси и повторите загрузку.") from error
            emit(component=component, stage="retry", text=f"Сбой сети Ollama. Повтор {attempt + 2} из 3…")
            time.sleep(2 ** (attempt + 1))


def _pull_model_once(name, component):
    request = urllib.request.Request(OLLAMA_URL + "/api/pull", method="POST",
                                     data=json.dumps({"name": name, "stream": True}).encode(),
                                     headers={"Content-Type": "application/json"})
    last = 0.0
    with urllib.request.urlopen(request, timeout=3600) as response:
        for line in response:
            event = json.loads(line or b"{}")
            if event.get("error"):
                raise RuntimeError(event["error"])
            if time.monotonic() - last > 0.3 and event.get("total"):
                emit(component=component, stage="download", done=event.get("completed", 0), total=event["total"])
                last = time.monotonic()
            if event.get("status") == "success":
                return
    raise RuntimeError("поток загрузки оборвался до подтверждения Ollama")


PYTHON_EMBED = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip"
GET_PIP = "https://bootstrap.pypa.io/get-pip.py"
TORCH_INDEX = "https://download.pytorch.org/whl/cu128"
CLONE_MODEL = voice_assets.BASE
CLONE_MODEL_BYTES = 2_520_000_000      # для полосы прогресса: размер весов на Hugging Face


def clone_python():
    """Python голосового сервера: своё окружение разработчика или скачанное мастером."""
    name = "python.exe" if os.name == "nt" else "python"
    for path in (os.path.join(ROOT, ".venv-tts", "Scripts" if os.name == "nt" else "bin", name),
                 os.path.join(ROOT, "runtime-tts", name)):
        if os.path.exists(path):
            return path
    return None


def _pip(python, args, component):
    process = subprocess.Popen([python, "-m", "pip", "install", "--disable-pip-version-check", "--no-cache-dir",
                                "--no-warn-script-location", *args],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
    tail = []
    for raw in process.stdout:
        line = raw.decode("utf-8", "replace").strip()
        if line:
            tail = (tail + [line])[-8:]
            if line.startswith(("Collecting", "Downloading", "Installing", "Successfully")):
                emit(component=component, stage="pip", text=line[:120])
    if process.wait():
        raise RuntimeError("pip не смог установить пакеты:\n" + "\n".join(tail))


def _cache_size(folder):
    total = 0
    for base, _, files in os.walk(folder):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(base, name))
            except OSError:
                pass
    return total


def install_clone(model=CLONE_MODEL, *, runtime_only=False):
    """Голос Джарвиса: отдельный Python с PyTorch (CUDA) и моделью Qwen3-TTS, ~5 ГБ.
    Отдельно от ядра: без видеокарты ядро о гигабайтах CUDA и не узнает."""
    python = clone_python()
    if python is None:
        if os.name != "nt":
            raise RuntimeError("Создайте отдельное окружение голоса по инструкции для Linux")
        runtime = os.path.join(ROOT, "runtime-tts")
        archive = os.path.join(DOWNLOADS, "python-embed.zip")
        if not os.path.exists(archive):
            download("clone", PYTHON_EMBED, archive)
        emit(component="clone", stage="extract")
        _safe_extract(archive, runtime)
        os.remove(archive)
        for name in os.listdir(runtime):
            if name.endswith("._pth"):
                path = os.path.join(runtime, name)
                lines = open(path, encoding="utf-8").read().replace("#import site", "import site").splitlines()
                open(path, "w", encoding="utf-8").write("\n".join(["Lib\\site-packages"] + lines))
        python = os.path.join(runtime, "python.exe")
    if subprocess.run([python, "-m", "pip", "--version"], creationflags=NO_WINDOW,
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20).returncode:
        get_pip = os.path.join(DOWNLOADS, "get-pip-tts.py")
        download("clone", GET_PIP, get_pip)
        subprocess.run([python, get_pip, "--no-warn-script-location"],
                       check=True, creationflags=NO_WINDOW, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.remove(get_pip)
    emit(component="clone", stage="pip", text="PyTorch для видеокарты (≈2.6 ГБ)…")
    _pip(python, ["torch", "torchaudio", "--index-url", TORCH_INDEX], "clone")
    _pip(python, ["-r", os.path.join(ROOT, "requirements-tts.txt")], "clone")
    if runtime_only:
        return

    # Модель голоса: скачивается в кэш Hugging Face; прогресс — по размеру кэша.
    cache = voice_assets.hub_cache() / ("models--" + model.replace("/", "--"))
    process = subprocess.Popen(
        [python, "-c", "import sys; sys.path.insert(0,sys.argv[1]); from tts_server import resolve; resolve(sys.argv[2])", ROOT, model],
        creationflags=NO_WINDOW, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    while process.poll() is None:
        emit(component="clone", stage="download", done=_cache_size(cache), total=CLONE_MODEL_BYTES)
        time.sleep(1.0)
    if process.returncode:
        raise RuntimeError("не удалось скачать модель голоса; проверьте сеть и свободное место")


def install(component):
    lock = ("voice-runtime" if component in ("clone", "clone:1.7b", "clone-runtime") else
            component.replace(":", "-") if component in ARCHIVES or component == "vad" or
            component in {"piper", *("piper:" + name for name in PIPER_VOICES)} else None)
    if lock:
        with install_lock("piper-ruslan" if lock == "piper" else lock):
            return _install(component)
    return _install(component)


def _install(component):
    if component == "clone":
        install_clone()
    elif component == "clone-runtime":
        install_clone(runtime_only=True)
    elif component == "clone:1.7b":
        install_clone("Qwen/Qwen3-TTS-12Hz-1.7B-Base")
    elif component == "silero":
        if importlib.util.find_spec("torch") is None:
            _pip(sys.executable, ["torch", "--index-url", "https://download.pytorch.org/whl/cpu"], "silero")
        path = os.path.join(MODELS, "silero", "v5_6_ru.pt")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not os.path.isfile(path):
            download("silero", "https://models.silero.ai/models/tts/ru/v5_6_ru.pt", path)
    elif component == "packages":
        install_packages()
    elif component == "avatar":
        install_avatar()
    elif component == "aec":
        # «Пользуюсь колонками»: WebRTC AEC3 (livekit, ~10 МБ) + запись колонок (soundcard).
        _pip(sys.executable, ["livekit==1.2.1", "soundcard==0.4.6"], "aec")
    elif component in ARCHIVES:
        install_archive(component, *ARCHIVES[component])
    elif component == "vad":
        path = os.path.join(MODELS, "silero_vad.onnx")
        if not voice_assets.present(path):
            download("vad", f"{SHERPA}/asr-models/silero_vad.onnx", path)
    elif component == "speaker":
        # Узнавание хозяина: CAM++ (3D-Speaker) — на русских голосах отличает людей
        # заметно лучше английских моделей VoxCeleb (проверено при выборе).
        from shelter_core import speaker
        if not os.path.exists(speaker.MODEL):
            download("speaker", f"{SHERPA}/speaker-recongition-models/{speaker.MODEL_NAME}", speaker.MODEL)
    elif component.startswith("piper"):
        voice = component.split(":", 1)[1] if ":" in component else "ruslan"
        if voice not in PIPER_VOICES:
            raise RuntimeError(f"нет такого голоса: {voice}")
        install_archive(component, f"{SHERPA}/tts-models/vits-piper-ru_RU-{voice}-medium.tar.bz2",
                        os.path.join("piper", voice))
    elif component == "ollama":
        install_ollama()
    elif component.startswith("model:"):
        pull_model(component.split(":", 1)[1])
    else:
        raise RuntimeError(f"неизвестный компонент: {component}")


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("check", "install"):
        print(__doc__)
        return 2
    if sys.argv[1] == "check":
        print(json.dumps(check(), ensure_ascii=False))
        return 0
    failed = 0
    for component in sys.argv[2:]:
        emit(component=component, status="start")
        try:
            install(component)
            emit(component=component, status="ok")
        except Exception as error:
            failed += 1
            emit(component=component, status="error", message=str(error)[:600])
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
