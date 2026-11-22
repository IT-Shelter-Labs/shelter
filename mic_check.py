"""Проверка микрофона для мастера в окне: уровень, шум, контрольная фраза.

Берём звук из того же буфера, что слушает Джарвис (второй поток микрофона не
открывается), и ничего не сохраняем на диск. Числа — ориентир по одной записи,
а не «процент качества»: окно объясняет, что они значат.
"""

import difflib
import re
import time

import numpy as np


def _db(x):
    return round(float(20 * np.log10(np.sqrt(np.mean(np.square(x))) + 1e-9)), 1) if x.size else -90.0


def record(cap, seconds):
    """Подождать seconds и взять их из кольцевого буфера захвата."""
    if cap is None or getattr(cap, "stream", None) is None:
        raise RuntimeError("микрофон не открыт — проверьте устройство или перезапустите Джарвиса")
    seconds = max(1.0, min(float(getattr(cap, "buffer_len", 0) / max(1, cap.sample_rate)) - 0.2, float(seconds)))   # не длиннее буфера захвата
    time.sleep(seconds + 0.15)
    return cap.get_window(seconds, 0.0), int(cap.sample_rate)


def _to16k(samples, rate):
    if rate == 16000:
        return samples.astype(np.float32)
    from native_runtime import resample_poly
    divisor = int(np.gcd(16000, rate))
    return resample_poly(samples, 16000 // divisor, rate // divisor).astype(np.float32)


def _words(text):
    return re.findall(r"[а-яёa-z0-9]+", str(text).lower().replace("ё", "е"))


def analyze(samples, rate, phase, expected="", noise_db=None):
    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
    level = _db(samples)
    clipped = float(np.mean(np.abs(samples) > 0.98)) if samples.size else 0.0
    result = {"phase": phase, "db": level, "peak_db": round(float(20 * np.log10(peak + 1e-9)), 1), "clipped": round(clipped * 100, 2),
              "advice": [], "text": "", "matched": None}
    if phase == "noise":
        if level > -42:
            result["advice"].append("Вокруг шумно (вентилятор, музыка, клавиатура) — Джарвис может слышать лишнее. Помогут фильтр шума и микрофон ближе ко рту.")
        if level < -85:
            result["advice"].append("Почти полная тишина — возможно, микрофон выключен или выбран не тот.")
        return result
    # Громкость речи — по самой громкой половине секундных кусков (паузы не тянут вниз).
    chunks = [samples[i:i + rate // 2] for i in range(0, len(samples), rate // 2) if len(samples[i:i + rate // 2])]
    loud = sorted((_db(c) for c in chunks), reverse=True)[:max(1, len(chunks) // 2)]
    speech = round(float(np.mean(loud)), 1)
    result["speech_db"] = speech
    if noise_db is not None:
        result["snr"] = round(speech - float(noise_db), 1)
        if result["snr"] < 10:
            result["advice"].append("Голос почти не громче фона. Говорите ближе к микрофону или уберите шум.")
    if speech < -42:
        result["advice"].append("Голос очень тихий. Поднимите громкость микрофона в Windows: Параметры → Звук → Ввод.")
    if clipped > 0.005:
        result["advice"].append("Звук перегружен (хрипит). Уменьшите громкость микрофона в Windows.")
    import asr
    text = asr.transcribe(_to16k(samples, rate)) if asr._recognizer is not None else ""
    result["engine"] = "GigaAM" if asr._recognizer is not None else ""
    result["text"] = text
    if not result["engine"]:
        result["advice"].append("Точное распознавание GigaAM не загружено — проверка текста недоступна, но команды работают через vosk.")
    if expected:
        want, got = _words(expected), _words(text)
        hits = sum(1 for w in want if any(difflib.SequenceMatcher(None, w, g).ratio() >= 0.8 for g in got))
        result["matched"] = {"words": hits, "of": len(want)}
        if result["engine"] and want and hits < len(want) * 0.6:
            result["advice"].append("Многие слова распознаны неверно. Проверьте, что выбран тот микрофон, в который вы говорите.")
    return result


def run(cap, phase, seconds, expected="", noise_db=None):
    samples, rate = record(cap, seconds)
    return analyze(samples, rate, phase, expected, noise_db)
