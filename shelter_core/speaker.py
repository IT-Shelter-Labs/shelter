"""Узнавание хозяина по голосу (по желанию): чужой голос не командует компьютером.

Защита от «Джарвис, выключи компьютер» из голосового чата, доната на стриме,
YouTube или от гостей. Хозяин один раз читает вслух три фразы — Джарвис
запоминает отпечаток голоса (192 числа) в data/voice/owner.json, только на
этом компьютере. Дальше каждая фраза для Джарвиса сверяется с отпечатком
(~20 мс на процессоре, модель CAM++ из 3D-Speaker, 27 МБ).

Режимы: soft — гостю можно спросить погоду, новости, что играет, а действия —
только хозяину; strict — гостя Джарвис не слушает вовсе.
"""

from shelter_core.paths import ROOT_DIR

import json
import os
import threading
import time

import numpy as np

ROOT = ROOT_DIR
MODEL_NAME = "3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx"
MODEL = os.path.join(ROOT, "models", "speaker", MODEL_NAME)
OWNER = os.path.join(ROOT, "data", "voice", "owner.json")
SR = 16000
MIN_SECONDS = 1.0            # короче — отпечаток ненадёжен, решаем в пользу человека
# Гостю (режим soft) можно только узнавать, не действовать.
GUEST_TOOLS = ("weather", "search", "media")
GUEST_TAGS = ("weather", "search", "nowplaying", "timers")

_extractor = None
_owner = None
_lock = threading.Lock()


def available():
    return os.path.exists(MODEL)


def _model():
    global _extractor
    with _lock:
        if _extractor is None:
            import sherpa_onnx
            _extractor = sherpa_onnx.SpeakerEmbeddingExtractor(
                sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=MODEL, num_threads=1))
        return _extractor


def embedding(samples):
    """float32 16 кГц -> нормированный отпечаток голоса."""
    extractor = _model()
    stream = extractor.create_stream()
    stream.accept_waveform(SR, np.asarray(samples, dtype=np.float32))
    stream.input_finished()
    vector = np.asarray(extractor.compute(stream), dtype=np.float32)
    return vector / max(1e-9, float(np.linalg.norm(vector)))


def _speech(samples):
    """Только звучащие куски — паузы и тишина портят отпечаток."""
    samples = np.asarray(samples, dtype=np.float32)
    frame = SR // 50
    frames = [samples[i:i + frame] for i in range(0, len(samples) - frame, frame)]
    if not frames:
        return samples
    energy = np.array([float(np.sqrt(np.mean(f * f))) for f in frames])
    keep = energy > max(1e-4, float(np.percentile(energy, 90)) * 0.1)
    return np.concatenate([f for f, k in zip(frames, keep) if k]) if keep.any() else samples


def enroll(samples):
    """Запомнить хозяина по записи ~12 с: отпечатки трёх кусков усредняются."""
    voiced = _speech(samples)
    if len(voiced) < SR * 4:
        raise RuntimeError("слишком мало речи — прочитайте все три фразы")
    parts = np.array_split(voiced, 3)
    vectors = [embedding(part) for part in parts]
    owner = np.mean(vectors, axis=0)
    owner /= max(1e-9, float(np.linalg.norm(owner)))
    # Насколько куски похожи друг на друга — грубая проверка, что говорил один человек.
    consistency = float(min(v @ owner for v in vectors))
    os.makedirs(os.path.dirname(OWNER), exist_ok=True)
    with open(OWNER, "w", encoding="utf-8") as file:
        json.dump({"model": MODEL_NAME, "embedding": [round(float(x), 6) for x in owner],
                   "created": time.strftime("%Y-%m-%d %H:%M"), "consistency": round(consistency, 3)}, file)
    global _owner
    _owner = owner
    return {"seconds": round(len(voiced) / SR, 1), "consistency": round(consistency, 2)}


def owner():
    global _owner
    if _owner is None:
        try:
            with open(OWNER, encoding="utf-8") as file:
                data = json.load(file)
            if data.get("model") == MODEL_NAME:
                _owner = np.asarray(data["embedding"], dtype=np.float32)
        except (OSError, ValueError, KeyError):
            return None
    return _owner


def enrolled():
    return os.path.exists(OWNER) and owner() is not None


def forget():
    global _owner
    _owner = None
    if os.path.exists(OWNER):
        os.replace(OWNER, OWNER + ".old")


def score(samples):
    """Похожесть на хозяина 0..1; None — сравнить не с чем или фраза слишком короткая."""
    reference = owner()
    voiced = _speech(samples)
    if reference is None or len(voiced) < SR * MIN_SECONDS or not available():
        return None
    return float(embedding(voiced) @ reference)


def is_owner(samples, config):
    """True/False; если проверка выключена или не с чем сравнивать — True."""
    cfg = (config.get("wake") or {}).get("owner") or {}
    if not cfg.get("enabled") or not enrolled() or not available():
        return True
    value = score(samples)
    if value is None:
        return True
    return value >= float(cfg.get("threshold", 0.46))
