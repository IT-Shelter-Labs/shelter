"""Audit manually generated audio and export only reviewed takes. No training/network.

python tools/check_jarvis_corpus.py
python tools/check_jarvis_corpus.py --export --reference J0002 --rate 22050
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PACK = ROOT / 'datasets' / 'jarvis_voice_v1'
EXTENSIONS = {'.wav', '.mp3', '.flac', '.ogg'}


def load_plan(pack):
    rows = [json.loads(line) for line in (pack/'corpus.jsonl').read_text(encoding='utf8').splitlines() if line.strip()]
    seen = set()
    for row in rows:
        if row['id'] in seen or row['split'] not in ('train','validation','test'):
            raise ValueError('Повреждён план записей')
        seen.add(row['id'])
    return rows


def read_review(path, known):
    result = {}
    with path.open(encoding='utf-8-sig', newline='') as f:
        for row in csv.DictReader(f):
            ident = row.get('id','').strip()
            if ident not in known or ident in result:
                raise ValueError('Неизвестный или повторный ID в проверке: '+ident)
            if row.get('decision','') not in ('pending','approved','reject'):
                raise ValueError('Решение для '+ident+': pending, approved или reject')
            if any(c in row.get('actual_text','') for c in '<>[]|\n\r'):
                raise ValueError('В расшифровке не должно быть тегов и переносов: '+ident)
            result[ident] = row
    return result


def inspect(pack, raw, review):
    import numpy as np
    import soundfile as sf
    rows = load_plan(pack)
    choices = read_review(review, {r['id'] for r in rows})
    raw = raw.resolve(strict=True)
    files = {}
    unknown = []
    for path in raw.iterdir():
        if not path.is_file() or path.suffix.lower() not in EXTENSIONS:
            continue
        # Do not follow a link outside the explicitly selected recordings directory.
        if not path.resolve().is_relative_to(raw):
            unknown.append(path.name+' (ссылка за пределы папки)')
            continue
        files.setdefault(path.stem.upper(),[]).append(path)
    known = {r['id'] for r in rows}
    unknown.extend(p.name for ident, paths in files.items() if ident not in known for p in paths)
    audited = []
    hashes = {}
    for row in rows:
        item = {'id':row['id'],'split':row['split'],'decision':choices.get(row['id'],{}).get('decision','pending'),
                'path':None,'issues':[],'seconds':0}
        paths = files.get(row['id'],[])
        if not paths:
            item['issues'].append('missing')
        elif len(paths)>1:
            item['issues'].append('multiple_takes: оставьте один выбранный файл с этим ID')
        else:
            path = paths[0]
            item['path'] = str(path)
            try:
                info=sf.info(path)
                if info.duration>25 or info.duration<2 or path.stat().st_size>100*1024*1024:
                    item['seconds']=round(info.duration,3)
                    item['issues'].append('duration_outside_2_to_25_seconds_or_file_too_large')
                    audited.append(item)
                    continue
                audio, rate = sf.read(path,dtype='float32',always_2d=True)
                seconds = len(audio)/rate
                peak = float(np.max(np.abs(audio))) if len(audio) else 0
                rms = float(np.sqrt(np.mean(audio.mean(axis=1)**2))) if len(audio) else 0
                clip_fraction = float(np.mean(np.abs(audio)>=.999)) if len(audio) else 0
                item.update(seconds=round(seconds,3),rate=rate,channels=audio.shape[1],peak=round(peak,4),rms=round(rms,5))
                if not np.isfinite(audio).all():item['issues'].append('non_finite_audio')
                if not 2<=seconds<=25:item['issues'].append('duration_outside_2_to_25_seconds')
                if rms<.003:item['issues'].append('silence_or_too_quiet')
                if clip_fraction>.001:item['issues'].append('clipping')
                # Hash decoded PCM: the same recording in a different container is still a duplicate.
                pcm=np.clip(audio,-1,1)
                digest=hashlib.sha256(str(rate).encode()+str(audio.shape).encode()+(pcm*32767).astype('<i2').tobytes()).hexdigest()
                if digest in hashes:
                    item['issues'].append('duplicate_audio_of_'+hashes[digest]['id'])
                    hashes[digest]['issues'].append('duplicate_audio_of_'+item['id'])
                else:hashes[digest]=item
                item['sha256_pcm']=digest
            except Exception as error:
                item['issues'].append('decode_error: '+str(error))
        audited.append(item)
    return rows, choices, audited, unknown


def export(pack, rows, choices, audited, output, reference, rate):
    import soundfile as sf
    selected = [i for i in audited if i['decision']=='approved']
    if not selected:raise ValueError('Нет принятых на слух записей. Отметьте decision=approved в review.csv.')
    invalid = [i for i in selected if i['issues']]
    if invalid:raise ValueError('Сначала исправьте аудио: '+', '.join(i['id'] for i in invalid))
    ref = next((i for i in selected if i['id']==reference),None)
    if ref is None or ref['split']!='train':raise ValueError('Reference должен быть принятой записью из train.')
    output = output.resolve()
    protected = [pack/'source.tsv',pack/'corpus.jsonl',pack/'review.csv']
    if output in [p.resolve() for p in protected]:raise ValueError('Выберите отдельную папку экспорта')
    # A new directory prevents accidentally retaining stale training takes after rejection.
    output.mkdir(parents=True,exist_ok=False)
    wavdir = output/'wavs';wavdir.mkdir()
    mapping = {r['id']:r for r in rows}
    normalized = {}
    converter = shutil.which('ffmpeg')
    for item in selected:
        source=Path(item['path'])
        target=wavdir/(item['id']+'.wav')
        if converter:
            subprocess.run([converter,'-nostdin','-v','error','-protocol_whitelist','file,pipe',
                            '-i',str(source),'-ac','1','-ar',str(rate),'-c:a','pcm_s16le',str(target)],
                           check=True,capture_output=True,timeout=30,
                           creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        else:
            import numpy as np
            from scipy.signal import resample_poly
            import math
            audio,source_rate=sf.read(source,dtype='float32',always_2d=True)
            audio=audio.mean(axis=1)
            divisor=math.gcd(source_rate,rate)
            if source_rate!=rate:audio=resample_poly(audio,rate//divisor,source_rate//divisor)
            sf.write(target,np.clip(audio,-1,1),rate,subtype='PCM_16')
        info=sf.info(target)
        if info.channels!=1 or info.samplerate!=rate:raise RuntimeError('Не удалось привести WAV к выбранному формату')
        normalized[item['id']]=target
    counts={}
    refpath=str(normalized[reference])
    for split in ('train','validation','test'):
        items=[i for i in selected if i['split']==split and i['id']!=reference]
        counts[split]=len(items)
        with (output/(split+'.csv')).open('w',encoding='utf8',newline='') as f:
            writer=csv.writer(f,delimiter='|')
            for item in items:
                text=choices[item['id']].get('actual_text','').strip() or mapping[item['id']]['text']
                writer.writerow([(Path('wavs')/(item['id']+'.wav')).as_posix(),text])
        with (output/(split+'_qwen.jsonl')).open('w',encoding='utf8') as f:
            for item in items:
                text=choices[item['id']].get('actual_text','').strip() or mapping[item['id']]['text']
                f.write(json.dumps({'audio':str(normalized[item['id']]),'text':text,'ref_audio':refpath},ensure_ascii=False)+'\n')
    provenance={'speaker':'jarvis','planned_source_voice_id':'3fc339d7c6474b11a221708e2a7b1c4b',
                'planned_source_engine':'Fish Audio Drama 3','source_settings_verified':False,'rate':rate,'reference':reference,'counts':counts,
                'audio_minutes':round(sum(i['seconds'] for i in selected)/60,2),
                'note':'Only manually approved takes. No model training performed. Voice and service usage rights must be verified separately.'}
    (output/'manifest.json').write_text(json.dumps(provenance,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    return provenance


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--pack',type=Path,default=DEFAULT_PACK)
    p.add_argument('--audio',type=Path)
    p.add_argument('--review',type=Path)
    p.add_argument('--export',action='store_true')
    p.add_argument('--reference',default='J0002')
    p.add_argument('--rate',type=int,choices=[22050,24000],default=22050)
    p.add_argument('--output',type=Path)
    args=p.parse_args()
    pack=args.pack.resolve(strict=True)
    rows,choices,audited,unknown=inspect(pack,args.audio or pack/'audio_raw',args.review or pack/'review.csv')
    summary={'planned':len(rows),'with_audio':sum(bool(r['path']) for r in audited),
             'approved':sum(r['decision']=='approved' for r in audited),
             'approved_with_issues':sum(r['decision']=='approved' and bool(r['issues']) for r in audited),
             'unknown_files':unknown,'audio':audited}
    (pack/'audio_audit.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    if args.export:
        summary['export']=export(pack,rows,choices,audited,args.output or pack/'prepared',args.reference,args.rate)
    print(json.dumps({k:v for k,v in summary.items() if k!='audio'},ensure_ascii=True,indent=2))


if __name__=='__main__':main()
