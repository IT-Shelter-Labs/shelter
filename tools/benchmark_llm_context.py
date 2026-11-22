"""Read-only local inference benchmark. Never runs tools or writes user memory."""
import json
from pathlib import Path
import statistics
import sys
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from shelter_core import context_engine
from shelter_core import llm

OPENER=urllib.request.build_opener(urllib.request.ProxyHandler({}))
CASES=[
    ('acknowledgement',[{'role':'user','content':'Какой сыр тебе нравится?'},
        {'role':'assistant','content':'У меня нет личных предпочтений, сэр, я всего лишь ассистент.'}],
        'понял'),
    ('repair',[{'role':'user','content':'понял'},
        {'role':'assistant','content':'Я принял к сведению ваши пожелания, сэр.'}],
        'Какие пожелания? Я же ничего не говорил.'),
    ('recent_fact',[{'role':'user','content':'В этом разговоре мой кодовый проект называется Ландыш, а дедлайн — пятница.'},
        {'role':'assistant','content':'Понял, сэр.'}], 'Как называется проект и когда дедлайн?'),
    ('negation',[{'role':'user','content':'Я не люблю кофе, пью зелёный чай без сахара.'},
        {'role':'assistant','content':'Учту в этом разговоре.'}], 'Какой напиток я предпочитаю?'),
    ('unknown',[], 'Какой у меня любимый фильм? Я его ещё не называл.'),
]


def request(model,history,question):
    cfg={'context':8192,'max_tokens':150,'temperature':.2}
    messages=context_engine.build(llm.DEFAULT_SYSTEM+llm.DIALOGUE_RULES,question,cfg,fallback=history)[0]
    payload={'model':model,'messages':messages,'stream':True,'think':False,'keep_alive':'3m',
             'options':{'num_ctx':8192,'num_predict':150,'temperature':.2}}
    start=time.perf_counter();first=None;chunks=[];last={}
    req=urllib.request.Request('http://127.0.0.1:11434/api/chat',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
    with OPENER.open(req,timeout=100) as response:
        for line in response:
            row=json.loads(line)
            if row.get('error'):raise ValueError(row['error'])
            value=(row.get('message') or {}).get('content','')
            if value:
                if first is None:first=time.perf_counter()-start
                chunks.append(value)
            last=row
    return {'first_text_s':round(first,3) if first is not None else None,
            'total_s':round(time.perf_counter()-start,3),'answer':''.join(chunks),
            'tokens':last.get('eval_count'),'tokens_per_s':round(last.get('eval_count',0)/(last.get('eval_duration',1)/1e9),2),
            'prompt_tokens':last.get('prompt_eval_count'),'load_s':round(last.get('load_duration',0)/1e9,3)}


def main():
    results=[];path=ROOT/'reports/llm-context-benchmark.json'
    for model in sys.argv[1:] or ['gemma4:e4b','qwen3.5:4b','qwen3.5:9b']:
        records=[]
        for name,history,question in CASES:
            try:record={'case':name,**request(model,history,question)}
            except Exception as error:record={'case':name,'error':str(error)}
            records.append(record)
            print(model,name,record.get('first_text_s'),record.get('answer',record.get('error')),flush=True)
            path.write_text(json.dumps(results+[{'model':model,'cases':records}],ensure_ascii=False,indent=2),encoding='utf8')
        times=[r['first_text_s'] for r in records[1:] if r.get('first_text_s') is not None]
        results.append({'model':model,'warm_first_text_median_s':statistics.median(times) if times else None,'cases':records})
        path.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')

if __name__=='__main__':main()
