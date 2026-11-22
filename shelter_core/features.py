"""Признаки из аудиоокна. Общий код для collect/train/detector."""

import librosa
import numpy as np

WINDOW_SECONDS = 2.0


def extract_features(wave: np.ndarray, sr: int = 32000) -> np.ndarray:
    """Окно 2.0 с -> вектор признаков фиксированной длины (64 x 5 = 320)."""
    n = int(WINDOW_SECONDS * sr)
    w = np.asarray(wave, dtype=np.float32).ravel()
    w = w[:n] if w.size >= n else np.pad(w, (0, n - w.size))

    # Нормировка по пику: детектор не должен зависеть от громкости и
    # расстояния до микрофона.
    w = w / (np.max(np.abs(w)) + 1e-9)

    mel = librosa.feature.melspectrogram(
        y=w, sr=sr, n_fft=1024, hop_length=512, n_mels=64, fmin=200, fmax=16000
    )
    db = librosa.power_to_db(mel)
    delta = np.diff(db, axis=1)

    # Дельты кодируют форму огибающей: резкая атака щелчка и медленное
    # затухание шипения. Этим банка и отличается от стука.
    return np.concatenate([
        db.mean(axis=1), db.std(axis=1), db.max(axis=1),
        delta.mean(axis=1), delta.std(axis=1),
    ])
