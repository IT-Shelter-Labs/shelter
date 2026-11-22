"""Двухступенчатый детектор звука банки: onset-гейт + классификатор."""

import collections
import csv
import os
import queue
import time

import joblib
import numpy as np
from scipy import signal
from scipy.io import wavfile

from audio import LISTENING, SPEAKING
from features import extract_features

HP_CUTOFF = 2000.0
STEP = 256              # шаг оценки RMS
NOISE_SECONDS = 5.0     # окно медианы шумового пола
WAIT_AFTER_ONSET = 1.7  # ждём, пока шипение доиграет
MIN_FLOOR = 3e-5        # чтобы в полной тишине не делить на ноль
EVENTS_CSV = "logs/events.csv"
CLIPS_DIR = "logs/clips"


def is_armed(config):
    """Разрешён ли сейчас звуковой триггер.

    По умолчанию случайный похожий звук ничего не запускает: пользователь
    должен сначала обратиться к Jarvis. Флаг в конфиге оставляет возможность
    делать фоновые триггеры в пользовательских сборках.
    """
    return not bool(config.get("requires_wake", True)) or LISTENING.is_set()


def log_event(proba, fired):
    os.makedirs("logs", exist_ok=True)
    new = not os.path.exists(EVENTS_CSV)
    with open(EVENTS_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["timestamp", "proba", "fired"])
        w.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), f"{proba:.4f}", int(fired)])


def save_clip(wave, sr, proba):
    os.makedirs(CLIPS_DIR, exist_ok=True)
    # Несколько срабатываний в одну секунду не должны перезаписывать клип.
    stamp = time.strftime("%Y%m%d_%H%M%S")
    millis = int(time.time_ns() // 1_000_000 % 1000)
    path = os.path.join(CLIPS_DIR, f"{stamp}_{millis:03d}_{proba:.2f}.wav")
    wavfile.write(path, sr, (np.clip(wave, -1.0, 1.0) * 32767).astype(np.int16))
    return path


def run(cap, config, events, stop):
    cfg = config["detector"]
    model = joblib.load(cfg["model_path"])
    threshold = float(cfg["threshold"])
    onset_factor = float(cfg["onset_factor"])
    cooldown = float(cfg["cooldown"])          # после срабатывания
    refractory = float(cfg.get("refractory", 2.0))  # между соседними onset
    log_clip = float(cfg["log_clip_threshold"])
    sr = cap.sample_rate


    sos = signal.butter(4, HP_CUTOFF, btype="highpass", fs=sr, output="sos")
    zi = np.zeros((sos.shape[0], 2))

    history = collections.deque(maxlen=int(NOISE_SECONDS * sr / STEP))
    last_onset = 0.0
    last_fire = 0.0
    classify_at = None
    sleeping = True

    gate = "WAKE WORD REQUIRED" if cfg.get("requires_wake", True) else "ALWAYS ACTIVE"
    print(f">> CAN DETECTOR STANDBY  //  {gate}  //  threshold {threshold}  "
          f"onset x{onset_factor}  cooldown {cooldown:g}s")

    while not stop.is_set():
        if classify_at is not None and time.monotonic() >= classify_at:
            classify_at = None
            # Сеанс мог закончиться за WAIT_AFTER_ONSET, пока дожидались
            # хвоста звука. В таком случае классификацию и событие отменяем.
            if not is_armed(cfg):
                continue
            wave = cap.get_window(0.3, WAIT_AFTER_ONSET)
            proba = float(model.predict_proba(
                extract_features(wave, sr).reshape(1, -1))[0, 1])
            fired = proba >= threshold
            # В консоль только событие: все вероятности и так пишутся в CSV.
            log_event(proba, fired)
            if fired:
                print(f">> CAN DETECTED  //  {proba:.2f}")
            if proba >= log_clip:
                save_clip(wave, sr, proba)
            if fired:
                last_fire = time.monotonic()
                events.put(("can_opened", None))
            continue

        try:
            block = cap.det_queue.get(timeout=0.1)
        except queue.Empty:
            continue
        if SPEAKING.is_set():
            continue

        # Не взведён — не тратим процессор на фильтрацию. При взведении
        # шумовой пол восстанавливается из кольцевого буфера за один проход.
        if not is_armed(cfg):
            sleeping = True
            continue
        if sleeping:
            sleeping = False
            recent = cap.get_window(3.5, 0.0)
            past, zi = signal.sosfilt(sos, recent, zi=np.zeros((sos.shape[0], 2)))
            usable = len(past) // STEP * STEP
            history.clear()
            if usable:
                history.extend(np.sqrt(np.mean(
                    past[:usable].reshape(-1, STEP) ** 2, axis=1)).tolist())
            while not cap.det_queue.empty():      # эти блоки уже учтены в окне
                cap.det_queue.get_nowait()
            continue

        filtered, zi = signal.sosfilt(sos, block, zi=zi)
        for i in range(0, len(filtered) - STEP + 1, STEP):
            seg = filtered[i:i + STEP]
            rms = float(np.sqrt(np.mean(seg ** 2)))
            history.append(rms)

            if len(history) < history.maxlen // 5 or classify_at is not None:
                continue
            floor = max(float(np.median(history)), MIN_FLOOR)
            # Для интервалов используем монотонные часы: ручная смена времени
            # или синхронизация Windows не должны ломать cooldown детектора.
            now = time.monotonic()
            if (rms > floor * onset_factor
                    and now - last_onset > refractory
                    and now - last_fire > cooldown
                    and is_armed(cfg)):
                last_onset = now
                classify_at = now + WAIT_AFTER_ONSET
