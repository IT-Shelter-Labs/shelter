"""Repeatable Russian speech evaluation, without playing audio or touching settings.

python voice_benchmark.py --engine piper --limit 12
python voice_benchmark.py --engine silero --limit 12
Listen to WAVs and fill listening.csv: ASR alone cannot judge stress or intonation.
"""
import argparse
import csv
from datetime import datetime
import json
from pathlib import Path
import statistics
import time

CASES = [
    ("greeting", "Добрый день, сэр. Все системы работают в штатном режиме."),
    ("time", "Напоминание на 18:45, следующий таймер через 21 минуту."),
    ("percent", "Осталось 25% заряда, загрузка процессора 7%."),
    ("memory", "Свободно 16 ГБ памяти и 512 МБ места."),
    ("date", "Встреча состоится 14.11.2026."),
    ("negative", "За окном минус 12 градусов, ветер 3 метра в секунду."),
    ("decimal", "Температура датчика 21,5 градуса."),
    ("stress", "Он звонит по средам. Договоры уже готовы."),
    ("homograph", "В старом замке сломался дверной замок."),
    ("question", "Вы хотите продолжить? Какое напоминание поставить на завтра?"),
    ("exclamation", "Готово! Отличная работа, сэр. Продолжим?"),
    ("names", "Джарвис открыл Firefox и Visual Studio Code."),
    ("long", "Сначала я проверю расписание, затем напомню о встрече и включу свет в кабинете. Если устройство не ответит, я сообщу об этом и не стану утверждать, что задача выполнена."),
    ("yo", "Учётная запись защищена. Всё ещё идёт проверка."),
    ("units", "Датчик показывает 220 вольт и 50 герц."),
    ("money", "В списке покупок 125 рублей и 3 копейки."),
    ("count", "Одна задача выполнена, две задачи ожидают, пять задач отменены."),
    ("context", "Это относится только к текущему проекту. Личные предпочтения я сохраню отдельно."),
    ("pause", "Сэр, одну секунду… Проверка завершена. Можно продолжать."),
    ("numbers", "Номера обращений: 101, 1204 и 20500."),
]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--engine", choices=["piper", "silero", "clone"], required=True)
    p.add_argument("--config", default="config.public.yaml")
    p.add_argument("--limit", type=int, default=len(CASES))
    p.add_argument("--output")
    args = p.parse_args()
    import yaml
    import voice
    import speech_text
    from scipy.io import wavfile
    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8")) or {}
    tts = cfg.get("tts") or {}
    voice.ENGINE = args.engine
    voice.SPEAKER = tts.get("speaker", "aidar")
    voice.PIPER_VOICE = (tts.get("piper") or {}).get("voice", "ruslan")
    voice.PIPER_SPEED = (tts.get("piper") or {}).get("speed", 1)
    voice.SILERO_MODEL = (tts.get("silero") or {}).get("model", "v5_6_ru")
    voice.STRESS = tts.get("stress") or {}
    speech_text.PRONUNCIATIONS = tts.get("pronunciations") or {}
    out = Path(args.output or f"data/voice-benchmark/{datetime.now():%Y%m%d-%H%M%S}-{args.engine}").resolve()
    out.mkdir(parents=True, exist_ok=True)
    voice.TTS_CACHE = str(out / "cache")
    voice.configure_cache(cfg)
    if args.engine == "clone":
        voice.CLONE_URL = f"http://127.0.0.1:{(tts.get('clone') or {}).get('port',8766)}"
        if not voice.clone_ready():
            raise RuntimeError("Сначала запустите выбранный голос Qwen в Джарвисе")
    results = []
    for id, text in CASES[:max(1, args.limit)]:
        start = time.perf_counter()
        first = None
        parts, rate = [], 0
        for rate, part in voice.synthesize_chunks(text):
            if first is None:
                first = time.perf_counter() - start
            parts.append(part)
        import numpy as np
        audio = np.concatenate(parts) if parts else np.zeros(0, dtype=np.int16)
        if not rate or not len(audio):
            raise RuntimeError("Голос не вернул звук: " + id)
        elapsed = time.perf_counter() - start
        wavfile.write(out / f"{id}.wav", rate, audio)
        results.append({"id":id, "text":text, "prepared":speech_text.prepare_for_speech(text), "seconds":round(len(audio)/rate,3), "first_audio":round(first,3), "generation":round(elapsed,3), "rtf":round(elapsed/(len(audio)/rate),3)})
        print(id, results[-1]["rtf"], flush=True)
    (out / "results.json").write_text(json.dumps({"engine":args.engine,"model":voice.SILERO_MODEL if args.engine=="silero" else voice.PIPER_VOICE if args.engine=="piper" else tts.get("clone",{}).get("model"),"results":results},ensure_ascii=False,indent=2),encoding="utf-8")
    with (out / "listening.csv").open("w",encoding="utf-8-sig",newline="") as f:
        writer=csv.writer(f);writer.writerow(["id","text","произношение 1-5","ударения 1-5","интонация 1-5","примечание"])
        writer.writerows([r["id"],r["text"],"","","",""] for r in results)
    print(json.dumps({"folder":str(out),"cases":len(results),"median_rtf":round(statistics.median(r["rtf"] for r in results),3)},ensure_ascii=False))


if __name__ == "__main__":
    main()
