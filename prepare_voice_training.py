"""Prepare a clean single-speaker Qwen dataset; does not start GPU training.

Input metadata.csv: relative_audio_path|exact_transcript. Audio stays in place.
python prepare_voice_training.py DATASET_DIR --reference reference.wav --output data/voice-training
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path


def prepare(folder, reference, output):
    import soundfile
    folder = Path(folder).resolve(strict=True)
    reference = (folder / reference).resolve(strict=True)
    ref_info = soundfile.info(reference)
    if ref_info.channels != 1 or not 2 <= ref_info.duration <= 25:
        raise ValueError("Образец диктора: моно, 2–25 секунд")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    records, total, seen = [], 0, set()
    with (folder / "metadata.csv").open(encoding="utf-8-sig", newline="") as file:
        for index, row in enumerate(csv.reader(file, delimiter="|"), 1):
            if len(row) != 2 or not row[1].strip():
                raise ValueError(f"Строка {index}: нужны путь|точный текст")
            path = (folder / row[0]).resolve(strict=True)
            if not path.is_relative_to(folder) or not reference.is_relative_to(folder):
                raise ValueError("Аудио должно находиться внутри папки датасета")
            info = soundfile.info(path)
            if info.channels != 1 or not 2 <= info.duration <= 25:
                raise ValueError(f"{path.name}: нужна моно-запись длительностью 2–25 секунд")
            fingerprint = hashlib.sha256(path.read_bytes()).hexdigest()
            if fingerprint in seen or path == reference:
                continue
            seen.add(fingerprint)
            records.append({"audio":str(path),"text":row[1].strip(),"ref_audio":str(reference)})
            total += info.duration
    if len(records) < 20:
        raise ValueError("Для пробного разделения нужно хотя бы 20 разных записей; это не гарантия достаточного объёма для хорошего голоса")
    # Stable hash split keeps a recording out of both partitions across reruns.
    test = [r for r in records if int(hashlib.sha256(r["text"].encode()).hexdigest()[:8],16)%10==0]
    if not test:
        test=records[-2:]
    test_texts={r["text"] for r in test}
    train=[r for r in records if r["text"] not in test_texts]
    if len(train) < 10 or not test:
        raise ValueError("Слишком мало разных фраз для разделения на обучение и проверку")
    for name, items in (("train_raw.jsonl",train),("holdout_raw.jsonl",test)):
        (output/name).write_text("\n".join(json.dumps(r,ensure_ascii=False) for r in items)+"\n",encoding="utf-8")
    result={"train":len(train),"holdout":len(test),"minutes":round(total/60,1),"reference":str(reference),"instructions":"https://github.com/QwenLM/Qwen3-TTS/tree/main/finetuning"}
    (output/"manifest.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("folder");p.add_argument("--reference",required=True);p.add_argument("--output",default="data/voice-training")
    a=p.parse_args();print(json.dumps(prepare(a.folder,a.reference,a.output),ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
