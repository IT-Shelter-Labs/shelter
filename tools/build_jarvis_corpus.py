"""Build original Russian scripts and an offline Fish Audio generation worksheet."""
import argparse
import csv
import hashlib
import html
import itertools
import json
from collections import Counter, defaultdict
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / 'datasets' / 'jarvis_voice_v1'
VOICE_ID = '3fc339d7c6474b11a221708e2a7b1c4b'
VOICE_URL = 'https://fish.audio/ru/app/text-to-speech/?modelId=' + VOICE_ID
STYLES = {
    'neutral': '[calm, measured, restrained]',
    'question': '[calm, attentive, conversational]',
    'firm': '[calm, firm, controlled]',
    'warm': '[calm, subtly warm, restrained]',
    'dry': '[dry, understated, calm]',
}
LABELS = {'neutral':'Спокойно', 'question':'Уточнение', 'firm':'Предупреждение',
          'warm':'Сдержанно тепло', 'dry':'Сухая ирония'}


def generated():
    rows = []
    def add(category, text, family, note=''):
        rows.append(dict(category=category, text=text, family=family, notes=note))
    times = ['в семь часов утра','в восемь часов тридцать минут','в девять часов пятнадцать минут',
             'в десять часов сорок минут','в одиннадцать часов пять минут','в двенадцать часов дня',
             'в тринадцать часов двадцать минут','в четырнадцать часов пятьдесят минут',
             'в пятнадцать часов десять минут','в шестнадцать часов сорок пять минут',
             'в семнадцать часов тридцать минут','в восемнадцать часов двадцать пять минут',
             'в девятнадцать часов десять минут','в двадцать часов тридцать пять минут',
             'в двадцать один час','в двадцать два часа пятнадцать минут',
             'в двадцать три часа пятьдесят минут','в полночь','в половине восьмого утра','в четверть десятого вечера']
    for i, value in enumerate(times):
        add('time',f'Встреча начнётся {value}. Напоминание прозвучит немного раньше.',f'time-{i}')
        add('time',f'Следующее событие запланировано {value}. Оставить это время?',f'time-{i}')
    dates = ['первое января','седьмое февраля','восьмое марта','двенадцатое апреля',
             'девятое мая','двадцать второе июня','третье июля','девятнадцатое августа',
             'первое сентября','четырнадцатое октября','пятнадцатое ноября','тридцать первое декабря',
             'двадцать пятое января','двадцать восьмое февраля','тридцатое марта','второе апреля',
             'двадцать первое мая','шестнадцатое июня','двадцать седьмое июля','тринадцатое августа']
    for i, value in enumerate(dates):
        add('dates',f'В календаре выбрано {value}. Проверьте месяц перед сохранением события.',f'date-{i}')
        add('dates',f'Дата следующего осмотра — {value}. При необходимости её можно перенести.',f'date-{i}')
    percent = ['один процент','два процента','три процента','четыре процента','пять процентов',
               'семь процентов','десять процентов','одиннадцать процентов','двенадцать процентов',
               'пятнадцать процентов','двадцать процентов','двадцать один процент',
               'двадцать два процента','двадцать пять процентов','тридцать три процента',
               'сорок процентов','пятьдесят процентов','семьдесят пять процентов',
               'девяносто девять процентов','сто процентов']
    for i, value in enumerate(percent):
        add('percent',f'Текущий заряд батареи — {value}. Оставшееся время зависит от нагрузки.',f'percent-{i}')
        add('percent',f'На индикаторе отображается {value}. Это значение получено при последнем измерении.',f'percent-{i}')
    durations = ['две секунды','три секунды','пять секунд','десять секунд','пятнадцать секунд',
                 'тридцать секунд','сорок пять секунд','одну минуту','две минуты','пять минут',
                 'одиннадцать минут','двадцать одну минуту','двадцать две минуты','полчаса',
                 'сорок минут','один час','два часа','полтора часа','три часа','четыре часа']
    for i, value in enumerate(durations):
        add('durations',f'Я напомню об этой задаче через {value}. Название можно уточнить позже.',f'duration-{i}')
        add('durations',f'Сигнал прозвучит через {value}. Отменить ожидание можно голосовой командой.',f'duration-{i}')
    room_values = ['в кабинете','в гостиной','в спальне','на кухне','в прихожей','в мастерской']
    levels = ['десять процентов','двадцать пять процентов','сорок процентов','пятьдесят процентов','семьдесят пять процентов','сто процентов']
    for i, (room, level) in enumerate(itertools.product(room_values, levels)):
        add('home_values',f'Яркость лампы {room} установлена на {level}. Изменить оттенок света?',f'light-{i//2}')
    measures = ['двадцать два градуса','двадцать один градус','минус семь градусов','тридцать восемь градусов',
                'пять вольт','двенадцать вольт','двести двадцать вольт','пятьдесят герц',
                'шестьдесят герц','два с половиной метра','три сантиметра','пять миллиметров',
                'полтора килограмма','семьсот граммов','один литр','два с половиной литра',
                'пять метров в секунду','двадцать километров в час','одна тысяча рублей','двести пятьдесят рублей']
    for i, value in enumerate(measures):
        add('measures',f'В отчёте указано значение: {value}. Единицы измерения приведены полностью.',f'measure-{i}')
        add('measures',f'Записанное значение — {value}. Сравните его с исходными данными.',f'measure-{i}')
    resources = ['один гигабайт','два гигабайта','четыре гигабайта','восемь гигабайт','шестнадцать гигабайт',
                 'тридцать два гигабайта','шестьдесят четыре гигабайта','сто двадцать восемь гигабайт',
                 'двести пятьдесят шесть гигабайт','пятьсот двенадцать гигабайт',
                 'один мегабайт','два мегабайта','семь мегабайт','девяносто мегабайт',
                 'один терабайт','два терабайта','четыреста килобайт','семнадцать килобайт',
                 'пятьсот мегабайт','одна тысяча двадцать четыре мегабайта']
    for i, value in enumerate(resources):
        add('resources',f'Объём выбранных данных — {value}. Перед копированием проверим свободное место.',f'memory-{i}')
        add('resources',f'В свойствах отображается {value}. Это объём, а не скорость передачи.',f'memory-{i}')
    terms = [('браузер','страницами'),('архиватор','архивами'),('редактор','документами'),
             ('терминал','командами'),('планировщик','событиями'),('проигрыватель','аудиозаписями'),
             ('календарь','встречами'),('диспетчер','процессами'),('анализатор','измерениями'),
             ('проводник','папками'),('менеджер','загрузками'),('каталог','приложениями'),
             ('переключатель','режимами'),('мастер настройки','параметрами'),('обработчик','запросами'),
             ('интерфейс','устройствами'),('модуль связи','соединениями'),('просмотрщик','изображениями')]
    for i, (term, obj) in enumerate(terms):
        add('terms',f'Выбран {term} для работы с {obj}. Уточните, какое действие выполнить.',f'term-{i}')
        add('terms',f'Этот {term} уже открыт. Переключиться на него или продолжить здесь?',f'term-{i}')
    # Deliberate phonetic variety outside the assistant's repetitive command vocabulary.
    places = [('На берегу реки','шумела высокая трава'),('В маленькой мастерской','пахло древесиной'),
              ('На тихой станции','ожидали пассажиры'),('В вечернем саду','зажглись фонари'),
              ('На широком проспекте','остановился трамвай'),('В старой библиотеке','сохранились редкие книги'),
              ('За стеклянной дверью','работала выставка'),('Возле горной тропы','журчал ручей'),
              ('На открытой террасе','собрались гости'),('Под высокой аркой','раздавалось эхо')]
    endings = ['К вечеру стало заметно прохладнее.','Скоро начался небольшой дождь.',
               'Вдалеке послышались негромкие шаги.','До заката оставалось около часа.']
    for i, ((place, action), end) in enumerate(itertools.product(places, endings)):
        add('prose',f'{place} {action}. {end}',f'prose-{i//4}')
    sequences = ['ноль, один, два, три','четыре, пять, шесть, семь','восемь, девять, ноль, один',
                 'два, четыре, шесть, восемь','один, три, пять, семь','девять, семь, пять, три',
                 'шесть, ноль, четыре, два','восемь, один, шесть, ноль','пять, два, девять, четыре',
                 'три, восемь, один, семь']
    for i, value in enumerate(sequences):
        add('digits',f'Учебная последовательность цифр: {value}. Это вымышленный пример для проверки дикции.',f'digits-{i}')
    return rows


def build(count=600):
    with (PACK/'source.tsv').open(encoding='utf8',newline='') as f:
        seeds=list(csv.DictReader(f,delimiter='|'))
    for i,row in enumerate(seeds):
        row['family']='original-'+str(i)
        if 'замок' in row['text']:row['family']='homograph-zamok'
    pools=defaultdict(list)
    for row in generated():pools[row['category']].append(row)
    balanced=[]
    while any(pools.values()):
        for group in pools.values():
            if group:balanced.append(group.pop(0))
    rows=seeds+balanced
    if count < len(seeds) or count>len(rows): raise ValueError(f'count must be {len(seeds)}..{len(rows)}')
    rows=rows[:count]
    seen=set()
    for i,row in enumerate(rows,1):
        key=re.sub(r'\W+',' ',row['text'].lower()).strip()
        if key in seen:raise ValueError('Duplicate transcript: '+row['text'])
        seen.add(key)
        category=row['category']
        style='dry' if category=='dry' else 'warm' if category=='warm' else 'firm' if category=='errors' else 'question' if row['text'].endswith('?') else 'neutral'
        # A baseline without directions helps detect a tag that changes the timbre.
        prefix='' if i%5==0 and style=='neutral' else STYLES[style]+' '
        prompt=prefix+row['text']
        # Only a few scoped tags. Never claim that lexical Russian stress is controlled.
        if category=='long' and i%3==0:
            prompt=prompt.replace('. ','. [pause] ',1)
        if category in ('digits','measures') and i%4==0:
            prompt=prefix+'<slow>'+row['text']+'</slow>'
        family_hash=int(hashlib.sha256(('jarvis-v1|'+row['family']).encode()).hexdigest()[:8],16)%20
        split='test' if family_hash==0 else 'validation' if family_hash==1 else 'train'
        if category=='pilot' or row['family']=='homograph-zamok':split='train'
        row.update(id=f'J{i:04d}',generation_text=prompt,style=style,split=split,
                   audio_file=f'J{i:04d}.wav',voice_id=VOICE_ID,engine='Drama 3',
                   phase='pilot' if category=='pilot' else 'main',status='not_generated')
        if len(prompt)>450:raise ValueError('Prompt exceeds conservative UI budget: '+row['id'])
        if re.search(r'[\d<>\[\]|]',row['text']):raise ValueError('Training transcript must be plain spoken words: '+row['id'])
    return rows


def write(rows):
    PACK.mkdir(parents=True,exist_ok=True)
    (PACK/'audio_raw').mkdir(exist_ok=True)
    (PACK/'audio_raw'/'PUT_AUDIO_HERE.txt').write_text('Сохраняйте сюда записи с именами J0001.wav, J0002.wav и так далее. MP3 тоже поддерживается проверкой. Один файл — одна реплика.\n',encoding='utf8')
    (PACK/'corpus.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf8')
    fields=['id','audio_file','category','phase','style','split','text','generation_text','notes']
    with (PACK/'generation_plan.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');writer.writeheader();writer.writerows(rows)
    review=PACK/'review.csv'
    if not review.exists():
        with review.open('w',encoding='utf-8-sig',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=['id','decision','actual_text','comment']);writer.writeheader()
            writer.writerows({'id':r['id'],'decision':'pending','actual_text':'','comment':''} for r in rows)
    for name,selection in [('01_PILOT_20.md',rows[:20]),('ALL_SCRIPTS.md',rows)]:
        text='# Тексты для генерации Джарвиса\n\nОдин блок — один запрос Fish Audio. Заголовки и примечания в поле генерации не вставлять.\n\n'
        for r in selection:
            text+=f"## {r['id']} → {r['audio_file']}\n\n```text\n{r['generation_text']}\n```\n\n"
            if r['notes']:text+='Проверить на слух: '+r['notes']+'\n\n'
        (PACK/name).write_text(text,encoding='utf8')
    summary={'clips':len(rows),'unique_transcripts':len(set(r['text'] for r in rows)),
             'words':sum(len(r['text'].split()) for r in rows),
             'generation_characters':sum(len(r['generation_text']) for r in rows),
             'max_prompt_characters':max(len(r['generation_text']) for r in rows),
             'splits':dict(Counter(r['split'] for r in rows)),
             'styles':dict(Counter(r['style'] for r in rows)),
             'categories':dict(Counter(r['category'] for r in rows))}
    summary['estimated_speech_minutes_130_to_155_wpm']=[round(summary['words']/155),round(summary['words']/130)]
    (PACK/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    template=(ROOT/'tools'/'jarvis_corpus_worksheet.html').read_text(encoding='utf8')
    payload=json.dumps(rows,ensure_ascii=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    (PACK/'OPEN_ME.html').write_text(template.replace('__CORPUS_DATA__',payload).replace('__VOICE_URL__',html.escape(VOICE_URL,quote=True)),encoding='utf8')
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--count',type=int,default=600)
    result=write(build(parser.parse_args().count))
    print(json.dumps(result,ensure_ascii=True,indent=2))
