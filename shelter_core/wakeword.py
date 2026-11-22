"""Слово-обращение без vosk: потоковый keyword spotter sherpa-onnx.

Модель — маленький русский zipformer (alphacep, 22 МБ). Декодер ищет только
заданные слова, поэтому стоит 2–3 % одного ядра против ~25 % у vosk и не
требует обучения: любое своё имя («Пятница», «Компьютер») работает сразу.

На синтезированных голосах (8 голосов × 3 фразы, 14 похожих фраз без имени):
KWS 20/24 без ложных, vosk 16/24 и одно ложное.
"""

from shelter_core.paths import ROOT_DIR

import os
import threading

ROOT = ROOT_DIR
MODEL_DIR = os.path.join(ROOT, "models", "kws-ru")
FILES = ("tokens.txt", "bpe.model", "encoder.int8.onnx", "decoder.onnx", "joiner.int8.onnx")
SR = 16000
BOOST = 2.0

# Как «Джарвис» слышит модель у разных людей и голосов — без этих вариантов
# одно каноническое написание ловилось вдвое реже.
VARIANTS = {
    "джарвис": ["джарвис", "жарвис", "джарвиз", "джервис", "джарвес", "джарвиш", "чарвис", "дарвис"],
}


def available():
    if not all(os.path.isfile(os.path.join(MODEL_DIR, f)) for f in FILES):
        return False
    try:
        import sentencepiece  # noqa: F401
        import sherpa_onnx  # noqa: F401
    except Exception:
        return False
    return True


def threshold(sensitivity):
    """Чувствительность 0…1 (как в приложении) -> порог KWS. 0.5 -> 0.1 — лучший на проверке."""
    s = min(max(float(sensitivity), 0.0), 1.0)
    return round(max(0.25 - 0.3 * s, 0.03), 3)


def tag(text):
    return text.strip().lower().replace(" ", "_")


def keyword_lines(words, quick=(), sensitivity=0.5):
    """Строки keywords-файла: «▁д жа р ви с :2.0 #0.1 @w:джарвис».

    w: — обращение (все варианты написания под одним тегом первого слова),
    q: — быстрые команды без имени («пауза», «дальше»).
    """
    import sentencepiece as spm

    sp = spm.SentencePieceProcessor(model_file=os.path.join(MODEL_DIR, "bpe.model"))
    with open(os.path.join(MODEL_DIR, "tokens.txt"), encoding="utf-8") as f:
        vocab = {line.split()[0] for line in f if line.strip()}
    th = threshold(sensitivity)
    lines, seen = [], set()

    def add(text, label, strict=False):
        text = text.strip().lower()
        if not text or text in seen:
            return
        pieces = sp.encode(text, out_type=str)
        if not pieces or any(p not in vocab for p in pieces):
            return                         # латиница и прочее, чего модель не знает
        seen.add(text)
        # Быстрые слова короткие и частые в разговоре — им порог построже.
        t = min(th + 0.15, 0.5) if strict else th
        lines.append(f"{' '.join(pieces)} :{BOOST} #{t} @{label}")

    words = [w.strip().lower() for w in words if w and w.strip()]
    if words:
        main = tag(words[0])
        for word in words:
            for variant in VARIANTS.get(word, [word]):
                add(variant, "w:" + main)
    for phrase in quick:
        add(phrase, "q:" + tag(phrase), strict=True)
    return lines


class Spotter:
    """Один экземпляр модели; потоки (stream) — на каждый источник звука."""

    def __init__(self, words, quick=(), sensitivity=0.5, keywords_file=None):
        import sherpa_onnx

        lines = keyword_lines(words, quick, sensitivity)
        if not any(line.split("@")[-1].startswith("w:") for line in lines):
            raise RuntimeError("слово-обращение не из русских букв — модель его не знает")
        path = keywords_file or os.path.join(ROOT, "data", "kws_keywords.txt")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        join = lambda name: os.path.join(MODEL_DIR, name)
        self._kws = sherpa_onnx.KeywordSpotter(
            tokens=join("tokens.txt"), encoder=join("encoder.int8.onnx"), decoder=join("decoder.onnx"),
            joiner=join("joiner.int8.onnx"), keywords_file=path, num_threads=1, max_active_paths=4,
            keywords_score=BOOST, keywords_threshold=threshold(sensitivity))
        self._lock = threading.Lock()
        self.count = len(lines)

    def stream(self):
        return self._kws.create_stream()

    def feed(self, stream, x16):
        """Кусок звука 16 кГц float32 -> список сработавших тегов («w:джарвис», «q:пауза»)."""
        hits = []
        with self._lock:
            stream.accept_waveform(SR, x16)
            while self._kws.is_ready(stream):
                self._kws.decode_stream(stream)
                result = self._kws.get_result(stream)
                if result:
                    hits.append(result)
                    self._kws.reset_stream(stream)
        return hits

    def reset(self, stream):
        with self._lock:
            self._kws.reset_stream(stream)
