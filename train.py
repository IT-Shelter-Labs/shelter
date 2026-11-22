"""Обучение классификатора звука банки."""

import argparse
import glob
import os
import random

import joblib
import numpy as np
from scipy.io import wavfile
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import precision_score, recall_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from features import WINDOW_SECONDS, extract_features

SR = 32000
MODEL_PATH = "models/can_model.pkl"


def load_wav(path):
    sr, x = wavfile.read(path)
    if x.ndim > 1:
        x = x[:, 0]
    if x.dtype == np.int16:
        x = x.astype(np.float32) / 32768.0
    else:
        x = x.astype(np.float32)
    if sr != SR:
        print(f"  !! {os.path.basename(path)}: {sr} Гц вместо {SR}, пропускаю")
        return None
    return x


def session_of(path):
    """Сессия записи = префикс даты в имени: positive_20260816_171658.wav."""
    parts = os.path.basename(path).split("_")
    return parts[1] if len(parts) >= 3 and parts[1].isdigit() else os.path.basename(path)


def augment(w, noise_pool, rng):
    n = len(w)

    # Сдвиг события внутри окна: хвост обнуляем, а не заворачиваем.
    shift = int(rng.uniform(-0.4, 0.4) * SR)
    a = np.roll(w, shift)
    if shift > 0:
        a[:shift] = 0.0
    elif shift < 0:
        a[shift:] = 0.0

    a = a * (10.0 ** (rng.uniform(-12.0, 12.0) / 20.0))

    if noise_pool:
        noise = noise_pool[rng.randrange(len(noise_pool))]
        noise = noise[:n] if len(noise) >= n else np.pad(noise, (0, n - len(noise)))
        snr = rng.uniform(0.0, 20.0)
        ps = float(np.mean(a ** 2)) + 1e-12
        pn = float(np.mean(noise ** 2)) + 1e-12
        a = a + noise * np.sqrt(ps / (pn * 10.0 ** (snr / 10.0)))

    return np.clip(a, -1.0, 1.0)


def split_by_session(files, rng):
    """Одна сессия целиком уходит либо в train, либо в test."""
    sessions = sorted({session_of(f) for f in files})
    if len(sessions) < 2:
        return None, None
    rng.shuffle(sessions)
    n_test = max(1, len(sessions) // 3)
    test_sessions = set(sessions[:n_test])
    train = [f for f in files if session_of(f) not in test_sessions]
    test = [f for f in files if session_of(f) in test_sessions]
    if not train or not test:
        return None, None
    return train, test


def split_by_file(files, rng):
    """Запасной вариант: сессия одна, делим по файлам. Оценка будет завышена."""
    files = list(files)
    rng.shuffle(files)
    n_test = max(1, len(files) // 3)
    return files[n_test:], files[:n_test]


def pr_table(y, proba):
    print(f"\n  {'порог':>6}  {'precision':>9}  {'recall':>7}  {'ложных':>7}")
    best = None
    for t in np.arange(0.05, 1.0, 0.05):
        pred = (proba >= t).astype(int)
        fp = int(((pred == 1) & (y == 0)).sum())
        p = precision_score(y, pred, zero_division=0)
        r = recall_score(y, pred, zero_division=0)
        print(f"  {t:6.2f}  {p:9.3f}  {r:7.3f}  {fp:7d}")
        if p >= 0.99 and r > 0 and best is None:
            best = (t, p, r)
    return best


def main():
    parser = argparse.ArgumentParser(description="Обучение классификатора звука банки")
    parser.add_argument("--aug", type=int, default=8,
                        help="вариантов аугментации на позитивный файл")
    parser.add_argument("--aug-neg", type=int, default=1,
                        help="вариантов аугментации на негативный файл")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    rng = random.Random(args.seed)

    pos_files = sorted(glob.glob("data/positive/*.wav"))
    neg_files = sorted(glob.glob("data/negative/*.wav"))
    if not pos_files or not neg_files:
        print("Нет данных: нужны wav в data/positive и data/negative")
        return
    print(f"Файлов: позитивов {len(pos_files)}, негативов {len(neg_files)}")

    pos_tr, pos_te = split_by_session(pos_files, rng)
    if pos_tr is None:
        pos_tr, pos_te = split_by_file(pos_files, rng)
        print("  !! позитивы записаны в одну сессию — делю по файлам.")
        print("  !! аугментации одного события попадут и в train, и в test:")
        print("  !! метрики ниже завышены, реальное качество хуже.")
    neg_tr, neg_te = split_by_session(neg_files, rng)
    if neg_tr is None:
        neg_tr, neg_te = split_by_file(neg_files, rng)

    print(f"Train: {len(pos_tr)} поз / {len(neg_tr)} нег")
    print(f"Test:  {len(pos_te)} поз / {len(neg_te)} нег")

    # Шум для подмешивания берём только из обучающих негативов.
    noise_pool = [w for w in (load_wav(f) for f in neg_tr) if w is not None]

    def build(files, label, n_aug, augmented):
        X, y = [], []
        for f in files:
            w = load_wav(f)
            if w is None:
                continue
            X.append(extract_features(w, SR))
            y.append(label)
            for _ in range(n_aug if augmented else 0):
                X.append(extract_features(augment(w, noise_pool, rng), SR))
                y.append(label)
        return X, y

    print("\nСчитаю признаки...")
    Xtr, ytr = [], []
    for files, label, n_aug in ((pos_tr, 1, args.aug), (neg_tr, 0, args.aug_neg)):
        X, y = build(files, label, n_aug, True)
        Xtr += X
        ytr += y
    # Тест без аугментации: оцениваем на том, что реально записано.
    Xte, yte = [], []
    for files, label in ((pos_te, 1), (neg_te, 0)):
        X, y = build(files, label, 0, False)
        Xte += X
        yte += y

    Xtr, ytr = np.array(Xtr), np.array(ytr)
    Xte, yte = np.array(Xte), np.array(yte)
    print(f"Обучающих векторов: {len(ytr)} (позитивных {int(ytr.sum())})")
    print(f"Тестовых векторов:  {len(yte)} (позитивных {int(yte.sum())})")

    model = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", LogisticRegression(class_weight="balanced", max_iter=2000)),
    ])
    model.fit(Xtr, ytr)

    proba = model.predict_proba(Xte)[:, 1]
    best = pr_table(yte, proba)
    print()
    if best is None:
        print("  Порога с precision >= 0.99 нет. Это почти всегда значит, что")
        print("  не хватает негативов — добирайте их, а не крутите модель.")
    else:
        print(f"  РЕКОМЕНДОВАННЫЙ ПОРОГ: {best[0]:.2f} "
              f"(precision {best[1]:.3f}, recall {best[2]:.3f})")
        print("  Впишите его в config.yaml -> detector.threshold")

    os.makedirs("models", exist_ok=True)
    joblib.dump(model, MODEL_PATH)
    print(f"\nМодель сохранена: {MODEL_PATH}")


if __name__ == "__main__":
    main()
