"""Запись датасета: окна по 2 секунды в data/<label>/."""

import argparse
import os
import select
import sys
import time

if os.name == "nt":
    import msvcrt

import numpy as np
import sounddevice as sd
import yaml
from scipy.io import wavfile

from shelter_core.features import WINDOW_SECONDS

CONFIG_PATH = "config.yaml"


def load_audio_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    audio = cfg.get("audio") or {}
    return int(audio.get("sample_rate", 32000)), audio.get("device")


def record(sample_rate, device):
    x = sd.rec(int(WINDOW_SECONDS * sample_rate), samplerate=sample_rate,
               channels=1, dtype="float32", device=device)
    sd.wait()
    return x[:, 0].copy()


def save(w, label, sample_rate):
    folder = os.path.join("data", label)
    os.makedirs(folder, exist_ok=True)
    # Префикс даты в имени = сессия записи, по нему train.py делит train/test.
    path = os.path.join(folder, f"{label}_{time.strftime('%Y%m%d_%H%M%S')}.wav")
    wavfile.write(path, sample_rate, (np.clip(w, -1.0, 1.0) * 32767).astype(np.int16))
    return path


def report(w, path, sample_rate):
    peak = float(np.max(np.abs(w)))
    at = int(np.argmax(np.abs(w))) / sample_rate
    if peak >= 0.99:
        note = "  !! КЛИППИНГ, убавьте гейн"
    elif peak < 0.05:
        note = "  !! слишком тихо"
    else:
        note = ""
    print(f"  {os.path.basename(path)}   пик {peak:.3f} на {at:.2f} с{note}")


def is_quit(ch):
    """getch отдаёт байт в кодировке консоли: на русской раскладке q — это 'й'."""
    if ch == b"\x1b":
        return True
    for enc in ("cp866", "cp1251"):
        try:
            if ch.decode(enc).lower() in "qй":
                return True
        except UnicodeDecodeError:
            pass
    return False


def read_key(block=True):
    """Один символ без Enter; при block=False вернуть None, если ввода нет."""
    if os.name == "nt":
        return msvcrt.getch() if block or msvcrt.kbhit() else None
    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        if not block and not select.select([sys.stdin], [], [], 0)[0]:
            return None
        return sys.stdin.buffer.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
def main():
    parser = argparse.ArgumentParser(description="Запись датасета для детектора банки")
    parser.add_argument("--label", required=True, choices=["positive", "negative"])
    parser.add_argument("--continuous", action="store_true",
                        help="писать подряд кусками по 2 с (для фонового шума)")
    args = parser.parse_args()

    sample_rate, device = load_audio_config()
    print(f"Устройство: {sd.query_devices(device, 'input')['name']}")
    print(f"Метка: {args.label}, окно {WINDOW_SECONDS:.0f} с, {sample_rate} Гц")

    saved = 0
    if args.continuous:
        print("Пишу непрерывно. q или Esc — стоп.\n")
        while True:
            ch = read_key(block=False)
            if ch is not None and is_quit(ch):
                break
            w = record(sample_rate, device)
            report(w, save(w, args.label, sample_rate), sample_rate)
            saved += 1
    else:
        print("Пробел — записать 2 с, q или Esc — выход.\n")
        while True:
            ch = read_key()
            if is_quit(ch):
                break
            if ch != b" ":
                continue
            w = record(sample_rate, device)
            report(w, save(w, args.label, sample_rate), sample_rate)
            saved += 1

    print(f"\nЗаписано файлов: {saved}")


if __name__ == "__main__":
    main()
